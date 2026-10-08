"""
单元测试：src/runtime/idempotency/models.py

测试覆盖：
- IdempotencyKey 数据模型（字段验证、业务方法）
- IdempotencyResult 数据模型
- LeaseAcquisition 数据模型
- ReconciliationAttempt 数据模型（包含指数退避计算）

验收标准：
- 数据模型序列化/反序列化正确
- 业务方法逻辑正确（租约检查、状态判断）
- 指数退避计算符合 REQ-RT-007 §6.2 要求
"""

from datetime import datetime, timedelta

import pytest

from src.runtime.common.types import utc_now
from src.runtime.idempotency.models import (
    IdempotencyKey,
    IdempotencyResult,
    LeaseAcquisition,
    ReconciliationAttempt,
)
from src.runtime.idempotency.types import IdempotencyScope, IdempotencyStatus


class TestIdempotencyKey:
    """冒烟 + 边界 + 异常：IdempotencyKey 数据模型"""

    def test_smoke_create_minimal_key(self) -> None:
        """冒烟：创建最小幂等键"""
        key = IdempotencyKey(
            key_id="idem-019401c2-5c3f-7890-abcd-ef1234567890",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123...",
            created_by="user-001",
        )

        assert key.key_id == "idem-019401c2-5c3f-7890-abcd-ef1234567890"
        assert key.scope == IdempotencyScope.STEP_SCOPE  # 默认值
        assert key.status == IdempotencyStatus.RESERVED  # 默认值
        assert key.organization_id == "org-001"
        assert key.workflow_id == "wf-001"
        assert key.step_id == "step-001"
        assert key.intent_instance_id == "intent-001"
        assert key.request_digest == "sha256:abc123..."

    def test_smoke_is_lease_valid_when_not_expired(self) -> None:
        """冒烟：租约有效性检查（未过期）"""
        future_time = utc_now() + timedelta(hours=1)
        key = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            lease_token="executor-001",
            lease_expires_at=future_time,
        )

        assert key.is_lease_valid() is True

    def test_boundary_is_lease_valid_when_expired(self) -> None:
        """边界：租约过期时无效"""
        past_time = utc_now() - timedelta(hours=1)
        key = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            lease_token="executor-001",
            lease_expires_at=past_time,
        )

        assert key.is_lease_valid() is False

    def test_boundary_is_lease_valid_when_no_token(self) -> None:
        """边界：无租约令牌时无效"""
        key = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            lease_token=None,
            lease_expires_at=None,
        )

        assert key.is_lease_valid() is False

    def test_smoke_is_terminal_delegates_to_status_enum(self) -> None:
        """冒烟：终态判断委托给枚举类"""
        key_succeeded = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            status=IdempotencyStatus.SUCCEEDED,
        )
        assert key_succeeded.is_terminal() is True

        key_executing = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            status=IdempotencyStatus.EXECUTING,
        )
        assert key_executing.is_terminal() is False

    def test_smoke_is_retryable_delegates_to_status_enum(self) -> None:
        """冒烟：可重试判断委托给枚举类"""
        key_retryable = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            status=IdempotencyStatus.FAILED_RETRYABLE,
        )
        assert key_retryable.is_retryable() is True

        key_succeeded = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            status=IdempotencyStatus.SUCCEEDED,
        )
        assert key_succeeded.is_retryable() is False

    def test_smoke_requires_reconciliation_delegates_to_status_enum(self) -> None:
        """冒烟：对账需求判断委托给枚举类"""
        key_unknown = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            status=IdempotencyStatus.OUTCOME_UNKNOWN,
        )
        assert key_unknown.requires_reconciliation() is True

        key_succeeded = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            status=IdempotencyStatus.SUCCEEDED,
        )
        assert key_succeeded.requires_reconciliation() is False

    def test_smoke_can_acquire_lease_when_no_existing_lease(self) -> None:
        """冒烟：无租约时可以获取"""
        key = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            lease_token=None,
        )

        assert key.can_acquire_lease("executor-001") is True

    def test_smoke_can_acquire_lease_when_same_holder_renews(self) -> None:
        """冒烟：当前持有者可以续约"""
        future_time = utc_now() + timedelta(hours=1)
        key = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            lease_token="executor-001",
            lease_expires_at=future_time,
        )

        assert key.can_acquire_lease("executor-001") is True

    def test_boundary_cannot_acquire_lease_when_held_by_another(self) -> None:
        """边界：其他执行者持有未过期租约时不能获取"""
        future_time = utc_now() + timedelta(hours=1)
        key = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            lease_token="executor-001",
            lease_expires_at=future_time,
        )

        assert key.can_acquire_lease("executor-002") is False

    def test_boundary_can_acquire_lease_when_expired(self) -> None:
        """边界：租约过期时可以接管（但需先核查状态）"""
        past_time = utc_now() - timedelta(hours=1)
        key = IdempotencyKey(
            key_id="idem-test",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            task_id="task-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request_digest="sha256:abc123",
            created_by="user-001",
            lease_token="executor-001",
            lease_expires_at=past_time,
        )

        # 租约过期，允许接管（但调用者需先核查前次执行状态）
        assert key.can_acquire_lease("executor-002") is True


class TestIdempotencyResult:
    """冒烟：IdempotencyResult 数据模型"""

    def test_smoke_create_result_for_new_operation(self) -> None:
        """冒烟：新操作的结果"""
        result = IdempotencyResult(
            key_id="idem-test",
            status=IdempotencyStatus.RESERVED,
            is_duplicate=False,
            should_execute=True,
        )

        assert result.key_id == "idem-test"
        assert result.status == IdempotencyStatus.RESERVED
        assert result.is_duplicate is False
        assert result.should_execute is True
        assert result.cached_result is None
        assert result.conflict_reason is None

    def test_smoke_create_result_for_duplicate_with_cached_result(self) -> None:
        """冒烟：重复操作且有缓存结果"""
        result = IdempotencyResult(
            key_id="idem-test",
            status=IdempotencyStatus.SUCCEEDED,
            is_duplicate=True,
            should_execute=False,
            cached_result={"output": "previous result"},
        )

        assert result.is_duplicate is True
        assert result.should_execute is False
        assert result.cached_result == {"output": "previous result"}

    def test_smoke_create_result_for_conflict(self) -> None:
        """冒烟：冲突结果（同键不同摘要）"""
        result = IdempotencyResult(
            key_id="idem-test",
            status=IdempotencyStatus.CONFLICT,
            is_duplicate=False,
            should_execute=False,
            conflict_reason="Same key but different request_digest",
        )

        assert result.status == IdempotencyStatus.CONFLICT
        assert result.should_execute is False
        assert result.conflict_reason is not None


class TestLeaseAcquisition:
    """冒烟：LeaseAcquisition 数据模型"""

    def test_smoke_successful_lease_acquisition(self) -> None:
        """冒烟：成功获取租约"""
        future_time = utc_now() + timedelta(minutes=30)
        lease = LeaseAcquisition(
            acquired=True,
            lease_token="executor-001",
            lease_expires_at=future_time,
        )

        assert lease.acquired is True
        assert lease.lease_token == "executor-001"
        assert lease.lease_expires_at == future_time
        assert lease.conflict_holder is None

    def test_smoke_failed_lease_acquisition_with_conflict(self) -> None:
        """冒烟：获取租约失败（有冲突持有者）"""
        lease = LeaseAcquisition(
            acquired=False,
            conflict_holder="executor-002",
        )

        assert lease.acquired is False
        assert lease.conflict_holder == "executor-002"
        assert lease.lease_token is None
        assert lease.lease_expires_at is None


class TestReconciliationAttempt:
    """冒烟 + 边界：ReconciliationAttempt 数据模型和指数退避"""

    def test_smoke_create_reconciliation_attempt(self) -> None:
        """冒烟：创建对账尝试记录"""
        attempt = ReconciliationAttempt(
            attempt_number=1,
            outcome="STILL_UNKNOWN",
            error_code="TIMEOUT",
            error_message="Query timeout after 5s",
        )

        assert attempt.attempt_number == 1
        assert attempt.outcome == "STILL_UNKNOWN"
        assert attempt.error_code == "TIMEOUT"
        assert attempt.attempted_at is not None

    def test_smoke_calculate_next_retry_with_exponential_backoff(self) -> None:
        """冒烟：指数退避计算（REQ-RT-007 §6.2）"""
        now = utc_now()

        # 第1次重试：约 1s（2^0 * 1s）
        next_retry_1 = ReconciliationAttempt.calculate_next_retry(
            attempt_number=1, base_delay_seconds=1.0
        )
        assert (next_retry_1 - now).total_seconds() >= 0.75  # 1s - 25% jitter
        assert (next_retry_1 - now).total_seconds() <= 1.25  # 1s + 25% jitter

        # 第2次重试：约 2s（2^1 * 1s）
        next_retry_2 = ReconciliationAttempt.calculate_next_retry(
            attempt_number=2, base_delay_seconds=1.0
        )
        assert (next_retry_2 - now).total_seconds() >= 1.5  # 2s - 25% jitter
        assert (next_retry_2 - now).total_seconds() <= 2.5  # 2s + 25% jitter

        # 第3次重试：约 4s（2^2 * 1s）
        next_retry_3 = ReconciliationAttempt.calculate_next_retry(
            attempt_number=3, base_delay_seconds=1.0
        )
        assert (next_retry_3 - now).total_seconds() >= 3.0  # 4s - 25% jitter
        assert (next_retry_3 - now).total_seconds() <= 5.0  # 4s + 25% jitter

    def test_boundary_attempt_number_validation(self) -> None:
        """边界：尝试次数必须在 1-4 之间"""
        # 有效范围
        for attempt_num in [1, 2, 3, 4]:
            attempt = ReconciliationAttempt(
                attempt_number=attempt_num,
                outcome="STILL_UNKNOWN",
            )
            assert attempt.attempt_number == attempt_num

        # 无效范围（应该抛出验证错误）
        with pytest.raises(Exception):  # Pydantic ValidationError
            ReconciliationAttempt(
                attempt_number=0,  # 小于 1
                outcome="STILL_UNKNOWN",
            )

        with pytest.raises(Exception):  # Pydantic ValidationError
            ReconciliationAttempt(
                attempt_number=5,  # 大于 4
                outcome="STILL_UNKNOWN",
            )
