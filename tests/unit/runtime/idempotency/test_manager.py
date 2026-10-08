"""
单元测试：src/runtime/idempotency/manager.py

测试覆盖：
- IdempotencyManager 核心管理逻辑
- 预留操作（唯一约束）
- 冲突检测（同键不同摘要）
- 重复识别（同键同摘要）
- 租约管理
- 状态迁移

验收标准：
- 重复提交同一幂等键 + 相同参数时只产生一次副作用
- 重复提交同一幂等键 + 不同参数时拒绝
- 并发提交同一幂等键时恰好一个成功
"""

import threading

import pytest

from src.runtime.idempotency.generator import IdempotencyKeyGenerator
from src.runtime.idempotency.manager import IdempotencyManager
from src.runtime.idempotency.storage import InMemoryIdempotencyStorage
from src.runtime.idempotency.types import IdempotencyScope, IdempotencyStatus


class TestIdempotencyManager:
    """冒烟 + 边界：IdempotencyManager 核心管理逻辑"""

    def test_smoke_reserve_new_operation(self) -> None:
        """冒烟：预留新操作"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        request_digest = "sha256:abc123"
        
        result = manager.reserve(
            key_id=key_id,
            request_digest=request_digest,
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        assert result.is_duplicate is False
        assert result.should_execute is True
        assert result.status == IdempotencyStatus.RESERVED

    def test_smoke_duplicate_same_digest(self) -> None:
        """冒烟：重复提交（同键同摘要）返回既有结果"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        request_digest = "sha256:abc123"
        
        # 第一次预留
        result1 = manager.reserve(
            key_id=key_id,
            request_digest=request_digest,
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        assert result1.should_execute is True
        
        # 第二次预留（同键同摘要）
        result2 = manager.reserve(
            key_id=key_id,
            request_digest=request_digest,
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        assert result2.is_duplicate is True
        assert result2.should_execute is False

    def test_boundary_conflict_different_digest(self) -> None:
        """边界：冲突（同键不同摘要）拒绝"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        
        # 第一次预留
        result1 = manager.reserve(
            key_id=key_id,
            request_digest="sha256:abc123",
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        assert result1.should_execute is True
        
        # 第二次预留（同键不同摘要）
        result2 = manager.reserve(
            key_id=key_id,
            request_digest="sha256:xyz789",  # 不同摘要
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        assert result2.is_duplicate is False
        assert result2.should_execute is False
        assert result2.status == IdempotencyStatus.CONFLICT

    def test_smoke_acquire_lease(self) -> None:
        """冒烟：获取租约"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        
        # 预留操作
        manager.reserve(
            key_id=key_id,
            request_digest="sha256:abc123",
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        # 获取租约
        lease = manager.acquire_lease(key_id, executor_id="worker-001")
        
        assert lease["acquired"] is True
        assert lease["lease_token"] == "worker-001"
        assert "lease_expires_at" in lease

    def test_boundary_cannot_acquire_lease_when_held_by_another(self) -> None:
        """边界：租约被其他执行者持有时不能获取"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        
        # 预留操作
        manager.reserve(
            key_id=key_id,
            request_digest="sha256:abc123",
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        # worker-001 获取租约
        lease1 = manager.acquire_lease(key_id, executor_id="worker-001")
        assert lease1["acquired"] is True
        
        # worker-002 尝试获取租约
        lease2 = manager.acquire_lease(key_id, executor_id="worker-002")
        
        assert lease2["acquired"] is False
        assert lease2["reason"] == "LEASE_HELD_BY_ANOTHER"

    def test_smoke_release_lease(self) -> None:
        """冒烟：释放租约"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        
        # 预留操作
        manager.reserve(
            key_id=key_id,
            request_digest="sha256:abc123",
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        # 获取租约
        lease = manager.acquire_lease(key_id, executor_id="worker-001")
        assert lease["acquired"] is True
        
        # 释放租约
        released = manager.release_lease(key_id, lease_token="worker-001")
        
        assert released is True

    def test_smoke_update_status(self) -> None:
        """冒烟：更新状态"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        
        # 预留操作
        manager.reserve(
            key_id=key_id,
            request_digest="sha256:abc123",
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        # 更新状态
        updated = manager.update_status(key_id, IdempotencyStatus.SUCCEEDED)
        
        assert updated is True
        status = manager.get_status(key_id)
        assert status == IdempotencyStatus.SUCCEEDED

    def test_boundary_update_status_with_cas(self) -> None:
        """边界：CAS 更新状态"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        
        # 预留操作
        manager.reserve(
            key_id=key_id,
            request_digest="sha256:abc123",
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        # CAS 更新：RESERVED → SUCCEEDED
        updated = manager.update_status(
            key_id,
            IdempotencyStatus.SUCCEEDED,
            expected_status=IdempotencyStatus.RESERVED,
        )
        
        assert updated is True
        status = manager.get_status(key_id)
        assert status == IdempotencyStatus.SUCCEEDED

    def test_boundary_update_status_cas_fails(self) -> None:
        """边界：CAS 更新失败（期望状态不匹配）"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        
        # 预留操作
        manager.reserve(
            key_id=key_id,
            request_digest="sha256:abc123",
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        # CAS 更新：期望 SUCCEEDED（实际是 RESERVED）
        updated = manager.update_status(
            key_id,
            IdempotencyStatus.FAILED_FINAL,
            expected_status=IdempotencyStatus.SUCCEEDED,
        )
        
        assert updated is False
        status = manager.get_status(key_id)
        assert status == IdempotencyStatus.RESERVED  # 状态未变

    def test_smoke_get_status(self) -> None:
        """冒烟：查询状态"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        
        # 预留操作
        manager.reserve(
            key_id=key_id,
            request_digest="sha256:abc123",
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        status = manager.get_status(key_id)
        
        assert status == IdempotencyStatus.RESERVED

    def test_boundary_get_status_nonexistent_key(self) -> None:
        """边界：查询不存在的键返回 None"""
        manager = IdempotencyManager()
        
        status = manager.get_status("nonexistent")
        
        assert status is None

    def test_smoke_get_key(self) -> None:
        """冒烟：获取完整幂等键信息"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        
        # 预留操作
        manager.reserve(
            key_id=key_id,
            request_digest="sha256:abc123",
            action_ref="action-001",
            scope=IdempotencyScope.STEP_SCOPE,
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
        )
        
        key = manager.get_key(key_id)
        
        assert key is not None
        assert key.key_id == key_id
        assert key.request_digest == "sha256:abc123"
        assert key.status == IdempotencyStatus.RESERVED

    def test_concurrent_reserve_only_one_is_new(self) -> None:
        """并发：并发预留同一键，只有一个是新操作"""
        manager = IdempotencyManager()
        key_id = "idem-001"
        request_digest = "sha256:abc123"
        results = []
        
        def reserve() -> None:
            result = manager.reserve(
                key_id=key_id,
                request_digest=request_digest,
                action_ref="action-001",
                scope=IdempotencyScope.STEP_SCOPE,
                organization_id="org-001",
                workflow_id="wf-001",
                step_id="step-001",
                intent_instance_id="intent-001",
                action_type="TOOL_CALL",
            )
            results.append(result)
        
        # 创建10个线程同时预留
        threads = [threading.Thread(target=reserve) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # 只有一个应该执行，其余都是重复
        should_execute_count = sum(1 for r in results if r.should_execute)
        duplicate_count = sum(1 for r in results if r.is_duplicate)
        
        assert should_execute_count == 1
        assert duplicate_count == 9
