"""
RT-007 Idempotency Key 与副作用边界 — 存储抽象层

本模块定义幂等键存储的抽象接口和 MVP 内存实现（REQ-RT-007 §5.3）

设计原则：
- 存储抽象层定义统一接口，便于后续替换为 PostgreSQL + Redis
- MVP 阶段使用内存实现（dict + threading.Lock）
- 模拟 PostgreSQL 的唯一约束和 CAS 操作
- 支持原子领取租约和状态迁移

后续集成：
- PostgreSQL：持久权威账本、唯一性约束、事务状态迁移
- Redis：24小时热键索引/结果缓存、短时并发协调
"""

import threading
from datetime import datetime
from typing import Protocol

from .models import IdempotencyKey
from .types import IdempotencyStatus


class IdempotencyStorage(Protocol):
    """幂等键存储接口（抽象协议）
    
    定义幂等键存储的统一接口，支持：
    - 原子插入（唯一约束）
    - 原子更新（CAS 操作）
    - 查询和状态检查
    - 租约管理
    
    实现类：
    - InMemoryIdempotencyStorage：MVP 内存实现
    - PostgreSQLIdempotencyStorage：生产 PostgreSQL 实现（待实现）
    - RedisIdempotencyStorage：热缓存优化（待实现）
    """
    
    def reserve(self, key: IdempotencyKey) -> bool:
        """预留幂等键（原子插入，唯一约束）
        
        Args:
            key: 幂等键对象
        
        Returns:
            是否成功预留（False 表示键已存在）
        """
        ...
    
    def get(self, key_id: str) -> IdempotencyKey | None:
        """获取幂等键
        
        Args:
            key_id: 幂等键 ID
        
        Returns:
            幂等键对象，不存在返回 None
        """
        ...
    
    def update_status(
        self,
        key_id: str,
        new_status: IdempotencyStatus,
        expected_status: IdempotencyStatus | None = None,
    ) -> bool:
        """更新状态（CAS 操作）
        
        Args:
            key_id: 幂等键 ID
            new_status: 新状态
            expected_status: 期望的当前状态（用于 CAS 检查）
        
        Returns:
            是否成功更新（False 表示 CAS 失败或键不存在）
        """
        ...
    
    def acquire_lease(
        self,
        key_id: str,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> bool:
        """原子获取租约
        
        Args:
            key_id: 幂等键 ID
            lease_token: 租约令牌
            lease_expires_at: 租约过期时间
        
        Returns:
            是否成功获取租约
        """
        ...
    
    def release_lease(self, key_id: str, lease_token: str) -> bool:
        """释放租约
        
        Args:
            key_id: 幂等键 ID
            lease_token: 租约令牌（必须匹配才能释放）
        
        Returns:
            是否成功释放
        """
        ...


class InMemoryIdempotencyStorage:
    """内存幂等键存储（MVP 实现）
    
    使用 dict + threading.Lock 实现：
    - 模拟 PostgreSQL 的唯一约束和 CAS 操作
    - 支持并发访问（线程安全）
    - 数据在进程重启后丢失（仅用于 MVP 测试）
    
    注意：
    - 本实现仅用于 MVP 阶段，生产环境必须使用 PostgreSQL
    - 不支持跨进程共享数据
    - 不支持持久化
    """
    
    def __init__(self) -> None:
        self._keys: dict[str, IdempotencyKey] = {}
        self._lock = threading.Lock()
    
    def reserve(self, key: IdempotencyKey) -> bool:
        """预留幂等键（原子插入，唯一约束）"""
        with self._lock:
            if key.key_id in self._keys:
                return False  # 键已存在，预留失败
            
            # 插入新键
            self._keys[key.key_id] = key.model_copy(deep=True)
            return True
    
    def get(self, key_id: str) -> IdempotencyKey | None:
        """获取幂等键"""
        with self._lock:
            key = self._keys.get(key_id)
            if key is None:
                return None
            # 返回副本，避免外部修改影响存储
            return key.model_copy(deep=True)
    
    def update_status(
        self,
        key_id: str,
        new_status: IdempotencyStatus,
        expected_status: IdempotencyStatus | None = None,
    ) -> bool:
        """更新状态（CAS 操作）"""
        with self._lock:
            key = self._keys.get(key_id)
            if key is None:
                return False  # 键不存在
            
            # CAS 检查：如果指定了期望状态，必须匹配
            if expected_status is not None and key.status != expected_status:
                return False  # CAS 失败
            
            # 更新状态
            key.status = new_status
            return True
    
    def acquire_lease(
        self,
        key_id: str,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> bool:
        """原子获取租约"""
        with self._lock:
            key = self._keys.get(key_id)
            if key is None:
                return False  # 键不存在
            
            # 检查是否可以获取租约（委托给模型方法）
            if not key.can_acquire_lease(lease_token):
                return False  # 租约被其他执行者持有
            
            # 获取租约
            key.lease_token = lease_token
            key.lease_expires_at = lease_expires_at
            return True
    
    def release_lease(self, key_id: str, lease_token: str) -> bool:
        """释放租约"""
        with self._lock:
            key = self._keys.get(key_id)
            if key is None:
                return False  # 键不存在
            
            # 检查租约令牌是否匹配
            if key.lease_token != lease_token:
                return False  # 令牌不匹配，不能释放
            
            # 释放租约
            key.lease_token = None
            key.lease_expires_at = None
            return True
    
    def update(self, key: IdempotencyKey) -> bool:
        """更新整个幂等键对象
        
        注意：这是一个便利方法，仅用于测试
        生产代码应该使用 update_status 等细粒度更新方法
        """
        with self._lock:
            if key.key_id not in self._keys:
                return False
            
            self._keys[key.key_id] = key.model_copy(deep=True)
            return True
    
    def clear(self) -> None:
        """清空所有数据（仅用于测试）"""
        with self._lock:
            self._keys.clear()
    
    def count(self) -> int:
        """返回存储的键数量（仅用于测试）"""
        with self._lock:
            return len(self._keys)
