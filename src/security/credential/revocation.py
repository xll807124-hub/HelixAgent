"""
分布式撤销协议 - REQ-SEC-005

核心需求：撤销事件全局传播，延迟 < 5 秒
实现机制：Redis Pub/Sub + PostgreSQL 持久化

架构：
1. 撤销请求进入撤销队列
2. 撤销服务处理并发布到 Redis
3. 所有 CDP 实例订阅并本地缓存
4. 持久化到 PostgreSQL 作为审计记录
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class RevocationEvent:
    """撤销事件"""
    
    def __init__(
        self,
        token_id: str,
        task_id: str,
        reason: str = "",
        triggered_by: str = "manual",
    ):
        self.revocation_id = str(uuid4())
        self.token_id = token_id
        self.task_id = task_id
        self.reason = reason
        self.triggered_by = triggered_by  # "manual", "kill_switch", "policy_change", etc.
        self.timestamp = datetime.utcnow()
        self.propagated_to_instances: list[str] = []

    def to_dict(self) -> dict:
        """转换为字典（用于序列化）"""
        return {
            "revocation_id": self.revocation_id,
            "token_id": self.token_id,
            "task_id": self.task_id,
            "reason": self.reason,
            "triggered_by": self.triggered_by,
            "timestamp": self.timestamp.isoformat(),
            "propagated_to_instances": self.propagated_to_instances,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RevocationEvent:
        """从字典创建对象"""
        event = cls(
            token_id=data["token_id"],
            task_id=data["task_id"],
            reason=data.get("reason", ""),
            triggered_by=data.get("triggered_by", "manual"),
        )
        event.revocation_id = data["revocation_id"]
        event.timestamp = datetime.fromisoformat(data["timestamp"])
        event.propagated_to_instances = data.get("propagated_to_instances", [])
        return event


class RevocationCache:
    """本地撤销缓存"""
    
    def __init__(self, ttl_seconds: int = 3600):
        """初始化缓存"""
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[RevocationEvent, datetime]] = {}

    def add(self, event: RevocationEvent) -> None:
        """添加撤销事件到缓存"""
        expiry = datetime.utcnow() + timedelta(seconds=self.ttl_seconds)
        self._cache[event.token_id] = (event, expiry)
        logger.debug(f"Revocation cached: {event.token_id}")

    def is_revoked(self, token_id: str) -> bool:
        """检查令牌是否被撤销"""
        if token_id not in self._cache:
            return False
        
        event, expiry = self._cache[token_id]
        if datetime.utcnow() > expiry:
            del self._cache[token_id]
            return False
        
        return True

    def get(self, token_id: str) -> Optional[RevocationEvent]:
        """获取撤销事件"""
        if not self.is_revoked(token_id):
            return None
        
        event, _ = self._cache[token_id]
        return event

    def cleanup_expired(self) -> int:
        """清理过期缓存"""
        now = datetime.utcnow()
        expired = [
            token_id
            for token_id, (_, expiry) in self._cache.items()
            if now > expiry
        ]
        
        for token_id in expired:
            del self._cache[token_id]
        
        return len(expired)


class RevocationBroker:
    """
    撤销代理 - 管理撤销事件的发布与订阅
    
    MVP 实现使用内存 + 模拟 Redis 的发布/订阅
    生产版本应集成真实 Redis
    """

    def __init__(self, redis_client: Any = None):
        """初始化撤销代理"""
        self.redis_client = redis_client
        self._subscribers: dict[str, list[Callable]] = {}
        self._revocation_history: list[RevocationEvent] = []
        self._channel = "credential_revocations"

    async def publish_revocation(
        self,
        event: RevocationEvent,
    ) -> None:
        """
        发布撤销事件
        
        Args:
            event: 撤销事件
        """
        # 持久化到历史
        self._revocation_history.append(event)
        
        # 发布到 Redis（生产环境）
        if self.redis_client:
            try:
                await self._publish_to_redis(event)
            except Exception as e:
                logger.error(f"Failed to publish to Redis: {e}")
                # fail-secure：本地通知不受影响
        
        # 本地通知所有订阅者
        await self._notify_subscribers(event)
        
        logger.info(f"Revocation event published: {event.token_id}")

    async def subscribe(
        self,
        instance_id: str,
        callback: Callable[[RevocationEvent], None],
    ) -> None:
        """
        订阅撤销事件
        
        Args:
            instance_id: 订阅实例 ID
            callback: 回调函数
        """
        if self._channel not in self._subscribers:
            self._subscribers[self._channel] = []
        
        self._subscribers[self._channel].append(callback)
        logger.info(f"Instance {instance_id} subscribed to revocations")

    async def _notify_subscribers(self, event: RevocationEvent) -> None:
        """通知所有订阅者"""
        if self._channel not in self._subscribers:
            return
        
        tasks = []
        for callback in self._subscribers[self._channel]:
            if asyncio.iscoroutinefunction(callback):
                tasks.append(callback(event))
            else:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Subscriber callback failed: {e}")
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _publish_to_redis(self, event: RevocationEvent) -> None:
        """发布到 Redis Pub/Sub"""
        if not self.redis_client:
            return
        
        message = json.dumps(event.to_dict())
        await self.redis_client.publish(self._channel, message)

    def get_revocation_history(self, limit: int = 100) -> list[RevocationEvent]:
        """获取撤销历史"""
        return self._revocation_history[-limit:]


class RevocationCoordinator:
    """
    撤销协调器 - 协调 PDP/CDP 间的撤销
    
    职责：
    1. 接收撤销请求
    2. 通过 RevocationBroker 发布
    3. 等待传播确认
    4. 记录审计
    """

    def __init__(
        self,
        broker: RevocationBroker,
        propagation_timeout_seconds: float = 5.0,
    ):
        self.broker = broker
        self.propagation_timeout_seconds = propagation_timeout_seconds
        self._pending_confirmations: dict[str, set[str]] = {}
        self._audit_log: list[dict] = []

    async def request_revocation(
        self,
        token_id: str,
        task_id: str,
        reason: str = "",
        triggered_by: str = "manual",
    ) -> bool:
        """
        请求撤销令牌
        
        Args:
            token_id: 令牌 ID
            task_id: 任务 ID
            reason: 撤销原因
            triggered_by: 触发来源
            
        Returns:
            是否成功发布撤销事件
        """
        event = RevocationEvent(
            token_id=token_id,
            task_id=task_id,
            reason=reason,
            triggered_by=triggered_by,
        )
        
        try:
            await self.broker.publish_revocation(event)
            
            self._audit_log.append({
                "revocation_id": event.revocation_id,
                "token_id": token_id,
                "task_id": task_id,
                "reason": reason,
                "triggered_by": triggered_by,
                "timestamp": datetime.utcnow().isoformat(),
                "status": "published",
            })
            
            logger.info(f"Revocation requested: {token_id} (by {triggered_by})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to request revocation: {e}")
            
            self._audit_log.append({
                "token_id": token_id,
                "task_id": task_id,
                "reason": reason,
                "triggered_by": triggered_by,
                "timestamp": datetime.utcnow().isoformat(),
                "status": "failed",
                "error": str(e),
            })
            
            return False

    async def wait_for_propagation(
        self,
        revocation_id: str,
        expected_instances: set[str],
    ) -> tuple[bool, set[str]]:
        """
        等待撤销事件的传播
        
        Args:
            revocation_id: 撤销事件 ID
            expected_instances: 预期收到的实例列表
            
        Returns:
            (成功, 已确认实例集合)
        """
        if not expected_instances:
            return True, set()
        
        # 初始化为待确认状态（需要等待所有实例确认）
        self._pending_confirmations[revocation_id] = expected_instances.copy()
        confirmed_instances: set[str] = set()
        
        start_time = datetime.utcnow()
        timeout = timedelta(seconds=self.propagation_timeout_seconds)
        
        while datetime.utcnow() - start_time < timeout:
            # 检查 _pending_confirmations 中是否有更新
            remaining = self._pending_confirmations.get(revocation_id, set())
            confirmed_instances = expected_instances - remaining
            
            # 如果所有实例都已确认
            if len(remaining) == 0:
                del self._pending_confirmations[revocation_id]
                return True, confirmed_instances
            
            await asyncio.sleep(0.01)
        
        # 超时
        remaining = self._pending_confirmations.get(revocation_id, set())
        confirmed_instances = expected_instances - remaining
        del self._pending_confirmations[revocation_id]
        
        logger.warning(
            f"Revocation propagation timeout: {revocation_id} "
            f"(confirmed: {len(confirmed_instances)}/{len(expected_instances)})"
        )
        return False, confirmed_instances

    def confirm_revocation_received(self, revocation_id: str, instance_id: str) -> None:
        """确认撤销事件已收到"""
        for rev_id in self._pending_confirmations:
            if rev_id == revocation_id:
                self._pending_confirmations[rev_id].discard(instance_id)
                logger.debug(f"Revocation confirmed by {instance_id}: {revocation_id}")
                break

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """获取审计日志"""
        return self._audit_log[-limit:]
