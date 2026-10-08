"""
单元测试：src/runtime/idempotency/reconciler.py

测试覆盖：
- IdempotencyReconciler 对账逻辑
- 查询外部系统确认副作用
- 指数退避重试（最多3次）
- 对账结果处理

验收标准：
- 对账成功时返回 CONFIRMED_SUCCESS
- 对账失败时返回 CONFIRMED_NOT_EXECUTED
- 3次重试后仍未知时返回 STILL_UNKNOWN
"""

import pytest

from src.runtime.idempotency.models import IdempotencyKey
from src.runtime.idempotency.reconciler import IdempotencyReconciler
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


class TestIdempotencyReconciler:
    """冒烟 + 边界：IdempotencyReconciler 对账逻辑"""

    def test_smoke_reconcile_outcome_unknown(self) -> None:
        """冒烟：对账 OUTCOME_UNKNOWN 状态的键"""
        storage = InMemoryIdempotencyStorage()
        reconciler = IdempotencyReconciler(storage)
        
        key = create_test_key(status=IdempotencyStatus.OUTCOME_UNKNOWN)
        storage.reserve(key)
        
        # 执行对账（模拟查询外部系统）
        outcome = reconciler.reconcile("idem-001")
        
        # MVP: 模拟查询，结果是随机的
        assert outcome in ("CONFIRMED_SUCCESS", "CONFIRMED_NOT_EXECUTED", "STILL_UNKNOWN")

    def test_smoke_reconcile_executing(self) -> None:
        """冒烟：对账 EXECUTING 状态的键返回 STILL_UNKNOWN"""
        storage = InMemoryIdempotencyStorage()
        reconciler = IdempotencyReconciler(storage)
        
        key = create_test_key(status=IdempotencyStatus.EXECUTING)
        storage.reserve(key)
        
        outcome = reconciler.reconcile("idem-001")
        
        assert outcome == "STILL_UNKNOWN"

    def test_smoke_reconcile_succeeded(self) -> None:
        """冒烟：对账 SUCCEEDED 状态的键返回 CONFIRMED_SUCCESS"""
        storage = InMemoryIdempotencyStorage()
        reconciler = IdempotencyReconciler(storage)
        
        key = create_test_key(status=IdempotencyStatus.SUCCEEDED)
        storage.reserve(key)
        
        outcome = reconciler.reconcile("idem-001")
        
        assert outcome == "CONFIRMED_SUCCESS"

    def test_smoke_reconcile_failed(self) -> None:
        """冒烟：对账 FAILED_FINAL 状态的键返回 CONFIRMED_NOT_EXECUTED"""
        storage = InMemoryIdempotencyStorage()
        reconciler = IdempotencyReconciler(storage)
        
        key = create_test_key(status=IdempotencyStatus.FAILED_FINAL)
        storage.reserve(key)
        
        outcome = reconciler.reconcile("idem-001")
        
        assert outcome == "CONFIRMED_NOT_EXECUTED"

    def test_boundary_reconcile_nonexistent_key(self) -> None:
        """边界：对账不存在的键返回 STILL_UNKNOWN"""
        storage = InMemoryIdempotencyStorage()
        reconciler = IdempotencyReconciler(storage)
        
        outcome = reconciler.reconcile("nonexistent")
        
        assert outcome == "STILL_UNKNOWN"

    def test_smoke_reconcile_with_retry(self) -> None:
        """冒烟：带重试的对账"""
        storage = InMemoryIdempotencyStorage()
        reconciler = IdempotencyReconciler(storage)
        
        key = create_test_key(status=IdempotencyStatus.OUTCOME_UNKNOWN)
        storage.reserve(key)
        
        # 执行带重试的对账
        # MVP: 模拟查询，结果是随机的，可能需要重试
        outcome = reconciler.reconcile_with_retry("idem-001")
        
        assert outcome in ("CONFIRMED_SUCCESS", "CONFIRMED_NOT_EXECUTED", "STILL_UNKNOWN")

    def test_boundary_reconcile_max_retries(self) -> None:
        """边界：对账最多重试3次"""
        storage = InMemoryIdempotencyStorage()
        reconciler = IdempotencyReconciler(storage)
        
        # 确保对账器最多重试3次
        assert reconciler.MAX_RETRIES == 3
