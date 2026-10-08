"""
单元测试：src/runtime/idempotency/escalation.py

测试覆盖：
- IdempotencyEscalationHandler 升级逻辑
- 升级到 ESCALATED 状态
- 记录升级原因和上下文
- 阻止自动重试
- 人工解决

验收标准：
- 升级后状态为 ESCALATED
- ESCALATED 状态的键不能自动重试
- 人工解决后可以转到 SUCCEEDED 或 FAILED_FINAL
"""

import pytest

from src.runtime.idempotency.escalation import EscalationReason, IdempotencyEscalationHandler
from src.runtime.idempotency.models import IdempotencyKey
from src.runtime.idempotency.storage import InMemoryIdempotencyStorage
from src.runtime.idempotency.types import IdempotencyScope, IdempotencyStatus


def create_test_key(key_id: str = "idem-001", status: IdempotencyStatus = IdempotencyStatus.OUTCOME_UNKNOWN) -> IdempotencyKey:
    """创建测试幂等键"""
    return IdempotencyKey(
        key_id=key_id,
        scope=IdempotencyScope.STEP_SCOPE,
        organization_id="org-001",
        project_id="proj-001",
        repository_id="repo-001",
        task_id="task-001",
        workflow_id="wf-001",
        step_id="step-001",
        intent_instance_id="intent-001",
        action_type="TOOL_CALL",
        request_digest="sha256:abc123",
        status=status,
        action_id="action-001",
        created_by="test-user",
    )


class TestIdempotencyEscalationHandler:
    """冒烟 + 边界：IdempotencyEscalationHandler 升级逻辑"""

    def test_smoke_escalate(self) -> None:
        """冒烟：升级到 ESCALATED 状态"""
        storage = InMemoryIdempotencyStorage()
        handler = IdempotencyEscalationHandler(storage)
        
        key = create_test_key()
        storage.reserve(key)
        
        # 升级
        escalated = handler.escalate(
            key_id="idem-001",
            reason=EscalationReason.RECONCILIATION_EXHAUSTED,
            context={"attempts": 3, "last_outcome": "STILL_UNKNOWN"},
        )
        
        assert escalated is True
        
        # 检查状态
        updated_key = storage.get("idem-001")
        assert updated_key is not None
        assert updated_key.status == IdempotencyStatus.ESCALATED

    def test_boundary_escalate_nonexistent_key(self) -> None:
        """边界：升级不存在的键失败"""
        storage = InMemoryIdempotencyStorage()
        handler = IdempotencyEscalationHandler(storage)
        
        escalated = handler.escalate(
            key_id="nonexistent",
            reason=EscalationReason.RECONCILIATION_EXHAUSTED,
        )
        
        assert escalated is False

    def test_smoke_cannot_retry_escalated(self) -> None:
        """冒烟：ESCALATED 状态的键不能自动重试"""
        storage = InMemoryIdempotencyStorage()
        handler = IdempotencyEscalationHandler(storage)
        
        key = create_test_key(status=IdempotencyStatus.ESCALATED)
        storage.reserve(key)
        
        can_retry = handler.can_retry("idem-001")
        
        assert can_retry is False

    def test_smoke_can_retry_retryable(self) -> None:
        """冒烟：FAILED_RETRYABLE 状态的键可以重试"""
        storage = InMemoryIdempotencyStorage()
        handler = IdempotencyEscalationHandler(storage)
        
        key = create_test_key(status=IdempotencyStatus.FAILED_RETRYABLE)
        storage.reserve(key)
        
        can_retry = handler.can_retry("idem-001")
        
        assert can_retry is True

    def test_boundary_cannot_retry_final_states(self) -> None:
        """边界：FAILED_FINAL 和 SUCCEEDED 状态不能重试"""
        storage = InMemoryIdempotencyStorage()
        handler = IdempotencyEscalationHandler(storage)
        
        # FAILED_FINAL
        key1 = create_test_key(key_id="idem-001", status=IdempotencyStatus.FAILED_FINAL)
        storage.reserve(key1)
        assert handler.can_retry("idem-001") is False
        
        # SUCCEEDED
        key2 = create_test_key(key_id="idem-002", status=IdempotencyStatus.SUCCEEDED)
        storage.reserve(key2)
        assert handler.can_retry("idem-002") is False

    def test_smoke_resolve_manual(self) -> None:
        """冒烟：人工解决升级的键"""
        storage = InMemoryIdempotencyStorage()
        handler = IdempotencyEscalationHandler(storage)
        
        key = create_test_key(status=IdempotencyStatus.ESCALATED)
        storage.reserve(key)
        
        # 人工解决为 SUCCEEDED
        resolved = handler.resolve_manual(
            key_id="idem-001",
            resolution=IdempotencyStatus.SUCCEEDED,
            notes="手动确认操作成功",
        )
        
        assert resolved is True
        
        # 检查状态
        updated_key = storage.get("idem-001")
        assert updated_key is not None
        assert updated_key.status == IdempotencyStatus.SUCCEEDED

    def test_boundary_cannot_resolve_non_escalated(self) -> None:
        """边界：只能解决 ESCALATED 状态的键"""
        storage = InMemoryIdempotencyStorage()
        handler = IdempotencyEscalationHandler(storage)
        
        key = create_test_key(status=IdempotencyStatus.RESERVED)
        storage.reserve(key)
        
        # 尝试解决非 ESCALATED 状态的键
        resolved = handler.resolve_manual(
            key_id="idem-001",
            resolution=IdempotencyStatus.SUCCEEDED,
        )
        
        assert resolved is False

    def test_boundary_resolve_nonexistent_key(self) -> None:
        """边界：解决不存在的键失败"""
        storage = InMemoryIdempotencyStorage()
        handler = IdempotencyEscalationHandler(storage)
        
        resolved = handler.resolve_manual(
            key_id="nonexistent",
            resolution=IdempotencyStatus.SUCCEEDED,
        )
        
        assert resolved is False
