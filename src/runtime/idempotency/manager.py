"""
RT-007 Idempotency Key 与副作用边界 — 幂等键管理器

本模块实现幂等键的核心管理逻辑（REQ-RT-007 §5、§6）

设计原则：
- 原子领取租约（Fencing Lease Token）
- 冲突检测（同键不同摘要拒绝）
- 状态迁移（12态账本）
- 重复提交识别（同键同摘要返回既有结果）

核心流程：
1. reserve()：预留操作（PostgreSQL 插入，唯一约束）
2. acquire_lease()：原子领取执行租约
3. check_duplicate()：检查重复提交
4. update_status()：更新状态
5. get_status()：查询状态

集成点：
- 与 Action 执行流程集成（任务1.2.8）
- 与 Policy Gateway 集成（阶段1.3）
- 与事件存储集成（记录状态变更事件）
"""

from datetime import timedelta
from typing import Any

from ..common.types import utc_now
from .generator import IdempotencyKeyGenerator
from .models import IdempotencyKey, IdempotencyResult
from .storage import IdempotencyStorage, InMemoryIdempotencyStorage
from .types import IdempotencyScope, IdempotencyStatus


class IdempotencyManager:
    """幂等键管理器（REQ-RT-007 核心逻辑）
    
    负责幂等键的生命周期管理：
    - 生成幂等键
    - 预留操作（唯一约束）
    - 原子领取租约
    - 冲突检测
    - 状态迁移
    - 重复提交识别
    
    Example:
        manager = IdempotencyManager()
        
        # 1. 生成幂等键和请求摘要
        key_id = manager.generator.generate_key(...)
        request_digest = manager.generator.generate_request_digest(request)
        
        # 2. 预留操作
        result = manager.reserve(key_id, request_digest, action_ref)
        
        if result.is_new:
            # 3. 原子领取租约
            lease = manager.acquire_lease(key_id, executor_id="worker-001")
            
            if lease.acquired:
                # 4. 执行操作
                ...
                
                # 5. 更新状态
                manager.update_status(key_id, IdempotencyStatus.SUCCESS)
        else:
            # 重复提交，返回既有结果
            print(f"Duplicate: {result.cached_result_ref}")
    """
    
    def __init__(
        self,
        storage: IdempotencyStorage | None = None,
        generator: IdempotencyKeyGenerator | None = None,
    ) -> None:
        """初始化幂等键管理器
        
        Args:
            storage: 存储实现（默认使用内存实现）
            generator: 幂等键生成器（默认创建新实例）
        """
        self.storage = storage or InMemoryIdempotencyStorage()
        self.generator = generator or IdempotencyKeyGenerator()
    
    def reserve(
        self,
        key_id: str,
        request_digest: str,
        action_ref: str,
        scope: IdempotencyScope = IdempotencyScope.STEP_SCOPE,
        organization_id: str = "",
        workflow_id: str = "",
        step_id: str = "",
        intent_instance_id: str = "",
        action_type: str = "",
    ) -> IdempotencyResult:
        """预留操作（PostgreSQL 插入，唯一约束）
        
        Args:
            key_id: 幂等键 ID
            request_digest: 请求摘要
            action_ref: 动作引用
            scope: 幂等作用域
            organization_id: 组织 ID
            workflow_id: 工作流 ID
            step_id: 步骤 ID
            intent_instance_id: 意图实例 ID
            action_type: 动作类型
        
        Returns:
            IdempotencyResult：
            - is_duplicate=True：重复提交（同键同摘要），返回既有结果
            - should_execute=False：不应执行（返回缓存结果）
            - status=CONFLICT：冲突（同键不同摘要），拒绝
        """
        # 1. 检查是否已存在
        existing_key = self.storage.get(key_id)
        
        if existing_key is not None:
            # 键已存在，检查是否重复提交
            return self.check_duplicate(existing_key, request_digest)
        
        # 2. 创建新键
        new_key = IdempotencyKey(
            key_id=key_id,
            scope=scope,
            organization_id=organization_id,
            project_id=organization_id,  # MVP: 使用 org_id
            repository_id=organization_id,  # MVP: 使用 org_id
            task_id=workflow_id,  # MVP: 使用 workflow_id
            workflow_id=workflow_id,
            step_id=step_id,
            intent_instance_id=intent_instance_id,
            action_type=action_type,
            request_digest=request_digest,
            status=IdempotencyStatus.RESERVED,
            action_id=action_ref,
            created_by="system",  # MVP: 默认值
        )
        
        # 3. 原子插入（唯一约束）
        reserved = self.storage.reserve(new_key)
        
        if not reserved:
            # 插入失败（并发竞争），重新读取并检查
            existing_key = self.storage.get(key_id)
            if existing_key is None:
                # 理论上不应该发生，但防御性处理
                return IdempotencyResult(
                    key_id=key_id,
                    status=IdempotencyStatus.CONFLICT,
                    is_duplicate=False,
                    should_execute=False,
                    conflict_reason="Concurrent insertion conflict",
                )
            
            return self.check_duplicate(existing_key, request_digest)
        
        # 4. 成功预留
        return IdempotencyResult(
            key_id=key_id,
            status=IdempotencyStatus.RESERVED,
            is_duplicate=False,
            should_execute=True,
        )
    
    def check_duplicate(
        self,
        existing_key: IdempotencyKey,
        request_digest: str,
    ) -> IdempotencyResult:
        """检查重复提交（REQ-RT-007 §5.2）
        
        Args:
            existing_key: 已存在的幂等键
            request_digest: 请求摘要
        
        Returns:
            IdempotencyResult：
            - is_duplicate=True：同键同摘要（重复提交，返回既有结果）
            - status=CONFLICT：同键不同摘要（冲突，拒绝）
        """
        # 1. 检查请求摘要是否一致
        if existing_key.request_digest != request_digest:
            # 同键不同摘要，拒绝为 CONFLICT
            return IdempotencyResult(
                key_id=existing_key.key_id,
                status=IdempotencyStatus.CONFLICT,
                is_duplicate=False,
                should_execute=False,
                conflict_reason="Same key with different request digest",
            )
        
        # 2. 同键同摘要，返回既有结果
        cached_result = (
            {"result_ref": existing_key.result_ref}
            if existing_key.result_ref
            else None
        )
        return IdempotencyResult(
            key_id=existing_key.key_id,
            status=existing_key.status,
            is_duplicate=True,
            should_execute=False,
            cached_result=cached_result,
        )
    
    def acquire_lease(
        self,
        key_id: str,
        executor_id: str,
        lease_duration_seconds: int = 1800,  # 默认30分钟
    ) -> dict[str, Any]:
        """原子领取执行租约（REQ-RT-007 §5.3）
        
        Args:
            key_id: 幂等键 ID
            executor_id: 执行者 ID
            lease_duration_seconds: 租约时长（秒）
        
        Returns:
            租约结果：
            - acquired: 是否成功获取
            - lease_token: 租约令牌（成功时返回）
            - lease_expires_at: 租约过期时间（成功时返回）
            - reason: 失败原因（失败时返回）
        """
        # 1. 读取幂等键
        key = self.storage.get(key_id)
        
        if key is None:
            return {
                "acquired": False,
                "reason": "KEY_NOT_FOUND",
            }
        
        # 2. 检查是否可以获取租约
        if not key.can_acquire_lease(executor_id):
            return {
                "acquired": False,
                "reason": "LEASE_HELD_BY_ANOTHER",
                "current_holder": key.lease_token,
                "lease_expires_at": key.lease_expires_at,
            }
        
        # 3. 生成租约令牌和过期时间
        lease_token = executor_id  # 简化实现：使用 executor_id 作为令牌
        lease_expires_at = utc_now() + timedelta(seconds=lease_duration_seconds)
        
        # 4. 原子获取租约
        acquired = self.storage.acquire_lease(key_id, lease_token, lease_expires_at)
        
        if not acquired:
            return {
                "acquired": False,
                "reason": "ACQUIRE_FAILED",
            }
        
        # 5. 成功获取租约
        return {
            "acquired": True,
            "lease_token": lease_token,
            "lease_expires_at": lease_expires_at,
        }
    
    def release_lease(self, key_id: str, lease_token: str) -> bool:
        """释放租约
        
        Args:
            key_id: 幂等键 ID
            lease_token: 租约令牌
        
        Returns:
            是否成功释放
        """
        return self.storage.release_lease(key_id, lease_token)
    
    def update_status(
        self,
        key_id: str,
        new_status: IdempotencyStatus,
        result_ref: str | None = None,
        expected_status: IdempotencyStatus | None = None,
    ) -> bool:
        """更新状态（CAS 操作）
        
        Args:
            key_id: 幂等键 ID
            new_status: 新状态
            result_ref: 结果引用（可选）
            expected_status: 期望的当前状态（用于 CAS 检查）
        
        Returns:
            是否成功更新
        """
        # 1. 更新状态
        updated = self.storage.update_status(key_id, new_status, expected_status)
        
        if not updated:
            return False
        
        # 2. 如果提供了结果引用，更新结果引用
        if result_ref is not None:
            key = self.storage.get(key_id)
            if key is not None:
                key.result_ref = result_ref
                self.storage.update(key)  # type: ignore
        
        return True
    
    def get_status(self, key_id: str) -> IdempotencyStatus | None:
        """查询状态
        
        Args:
            key_id: 幂等键 ID
        
        Returns:
            状态枚举，键不存在返回 None
        """
        key = self.storage.get(key_id)
        return key.status if key is not None else None
    
    def get_key(self, key_id: str) -> IdempotencyKey | None:
        """获取幂等键完整信息
        
        Args:
            key_id: 幂等键 ID
        
        Returns:
            幂等键对象，不存在返回 None
        """
        return self.storage.get(key_id)
