"""
单元测试：src/runtime/idempotency/storage.py

测试覆盖：
- InMemoryIdempotencyStorage 存储操作
- 原子插入（唯一约束）
- 状态更新（CAS 操作）
- 租约管理
- 并发安全

验收标准：
- 并发调用 reserve() 只有一个成功
- CAS 操作正确检查期望状态
- 租约获取和释放正确
- 线程安全
"""

import threading
from datetime import timedelta

import pytest

from src.runtime.common.types import utc_now
from src.runtime.idempotency.models import IdempotencyKey
from src.runtime.idempotency.storage import InMemoryIdempotencyStorage
from src.runtime.idempotency.types import IdempotencyScope, IdempotencyStatus


def create_test_key(key_id: str = "idem-001", **kwargs) -> IdempotencyKey:
    """创建测试幂等键"""
    defaults = {
        "key_id": key_id,
        "scope": IdempotencyScope.STEP_SCOPE,
        "organization_id": "org-001",
        "project_id": "proj-001",
        "repository_id": "repo-001",
        "task_id": "task-001",
        "workflow_id": "wf-001",
        "step_id": "step-001",
        "intent_instance_id": "intent-001",
        "action_type": "TOOL_CALL",
        "request_digest": "sha256:abc123",
        "status": IdempotencyStatus.RESERVED,
        "action_id": "action-001",
        "created_by": "test-user",
    }
    defaults.update(kwargs)
    return IdempotencyKey(**defaults)


class TestInMemoryIdempotencyStorage:
    """冒烟 + 边界：InMemoryIdempotencyStorage 存储操作"""

    def test_smoke_reserve_new_key(self) -> None:
        """冒烟：预留新键"""
        storage = InMemoryIdempotencyStorage()
        key = create_test_key()
        
        reserved = storage.reserve(key)
        
        assert reserved is True
        assert storage.count() == 1

    def test_boundary_reserve_duplicate_key(self) -> None:
        """边界：预留重复键失败（唯一约束）"""
        storage = InMemoryIdempotencyStorage()
        key = create_test_key()
        
        # 第一次预留成功
        reserved1 = storage.reserve(key)
        assert reserved1 is True
        
        # 第二次预留失败
        reserved2 = storage.reserve(key)
        assert reserved2 is False
        assert storage.count() == 1

    def test_smoke_get_existing_key(self) -> None:
        """冒烟：获取已存在的键"""
        storage = InMemoryIdempotencyStorage()
        key = create_test_key()
        storage.reserve(key)
        
        retrieved = storage.get("idem-001")
        
        assert retrieved is not None
        assert retrieved.key_id == "idem-001"
        assert retrieved.status == IdempotencyStatus.RESERVED

    def test_boundary_get_nonexistent_key(self) -> None:
        """边界：获取不存在的键返回 None"""
        storage = InMemoryIdempotencyStorage()
        
        retrieved = storage.get("nonexistent")
        
        assert retrieved is None

    def test_smoke_update_status(self) -> None:
        """冒烟：更新状态"""
        storage = InMemoryIdempotencyStorage()
        key = create_test_key()
        storage.reserve(key)
        
        updated = storage.update_status("idem-001", IdempotencyStatus.SUCCEEDED)
        
        assert updated is True
        retrieved = storage.get("idem-001")
        assert retrieved is not None
        assert retrieved.status == IdempotencyStatus.SUCCEEDED

    def test_boundary_update_status_with_cas(self) -> None:
        """边界：CAS 更新状态（期望状态匹配）"""
        storage = InMemoryIdempotencyStorage()
        key = create_test_key()
        storage.reserve(key)
        
        # CAS 更新：期望 RESERVED → SUCCEEDED
        updated = storage.update_status(
            "idem-001",
            IdempotencyStatus.SUCCEEDED,
            expected_status=IdempotencyStatus.RESERVED,
        )
        
        assert updated is True
        retrieved = storage.get("idem-001")
        assert retrieved is not None
        assert retrieved.status == IdempotencyStatus.SUCCEEDED

    def test_boundary_update_status_cas_fails_when_status_mismatch(self) -> None:
        """边界：CAS 更新失败（期望状态不匹配）"""
        storage = InMemoryIdempotencyStorage()
        key = create_test_key()
        storage.reserve(key)
        
        # CAS 更新：期望 SUCCEEDED（实际是 RESERVED）→ FAILED_FINAL
        updated = storage.update_status(
            "idem-001",
            IdempotencyStatus.FAILED_FINAL,
            expected_status=IdempotencyStatus.SUCCEEDED,
        )
        
        assert updated is False
        retrieved = storage.get("idem-001")
        assert retrieved is not None
        assert retrieved.status == IdempotencyStatus.RESERVED  # 状态未变

    def test_smoke_acquire_lease(self) -> None:
        """冒烟：获取租约"""
        storage = InMemoryIdempotencyStorage()
        key = create_test_key()
        storage.reserve(key)
        
        lease_expires_at = utc_now() + timedelta(hours=1)
        acquired = storage.acquire_lease("idem-001", "worker-001", lease_expires_at)
        
        assert acquired is True
        retrieved = storage.get("idem-001")
        assert retrieved is not None
        assert retrieved.lease_token == "worker-001"
        assert retrieved.lease_expires_at == lease_expires_at

    def test_boundary_cannot_acquire_lease_when_held_by_another(self) -> None:
        """边界：租约被其他执行者持有时不能获取"""
        storage = InMemoryIdempotencyStorage()
        key = create_test_key()
        storage.reserve(key)
        
        # worker-001 获取租约
        lease_expires_at = utc_now() + timedelta(hours=1)
        acquired1 = storage.acquire_lease("idem-001", "worker-001", lease_expires_at)
        assert acquired1 is True
        
        # worker-002 尝试获取租约（失败）
        acquired2 = storage.acquire_lease("idem-001", "worker-002", lease_expires_at)
        assert acquired2 is False

    def test_smoke_release_lease(self) -> None:
        """冒烟：释放租约"""
        storage = InMemoryIdempotencyStorage()
        key = create_test_key()
        storage.reserve(key)
        
        # 获取租约
        lease_expires_at = utc_now() + timedelta(hours=1)
        storage.acquire_lease("idem-001", "worker-001", lease_expires_at)
        
        # 释放租约
        released = storage.release_lease("idem-001", "worker-001")
        
        assert released is True
        retrieved = storage.get("idem-001")
        assert retrieved is not None
        assert retrieved.lease_token is None
        assert retrieved.lease_expires_at is None

    def test_boundary_cannot_release_lease_with_wrong_token(self) -> None:
        """边界：令牌不匹配时不能释放租约"""
        storage = InMemoryIdempotencyStorage()
        key = create_test_key()
        storage.reserve(key)
        
        # worker-001 获取租约
        lease_expires_at = utc_now() + timedelta(hours=1)
        storage.acquire_lease("idem-001", "worker-001", lease_expires_at)
        
        # worker-002 尝试释放租约（失败）
        released = storage.release_lease("idem-001", "worker-002")
        
        assert released is False
        retrieved = storage.get("idem-001")
        assert retrieved is not None
        assert retrieved.lease_token == "worker-001"  # 租约仍然存在

    def test_concurrent_reserve_only_one_succeeds(self) -> None:
        """并发：多个线程同时预留，只有一个成功"""
        storage = InMemoryIdempotencyStorage()
        results = []
        
        def reserve_key() -> None:
            key = create_test_key()
            reserved = storage.reserve(key)
            results.append(reserved)
        
        # 创建10个线程同时预留
        threads = [threading.Thread(target=reserve_key) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # 只有一个成功
        assert sum(results) == 1
        assert storage.count() == 1
