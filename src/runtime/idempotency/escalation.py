"""
RT-007 Idempotency Key 与副作用边界 — 升级处理器

本模块实现升级逻辑（REQ-RT-007 §7.3）

设计原则：
- 对账3次失败后升级到 ESCALATED 状态
- 记录升级原因和上下文
- 通知人工处理（告警、工单、日志）
- 阻止后续自动重试

核心流程：
1. escalate()：升级到人工处理
2. 记录升级事件
3. 发送通知（告警、工单）

集成点：
- 与对账器集成（reconciler.py）
- 与告警系统集成（阶段2）
- 与工单系统集成（阶段2）
"""

from typing import Any

from ..common.types import utc_now
from .models import IdempotencyKey
from .storage import IdempotencyStorage
from .types import IdempotencyStatus


class EscalationReason:
    """升级原因枚举"""
    
    RECONCILIATION_EXHAUSTED = "RECONCILIATION_EXHAUSTED"  # 对账重试耗尽
    COMPENSATION_FAILED = "COMPENSATION_FAILED"            # 补偿失败
    MANUAL_REQUEST = "MANUAL_REQUEST"                      # 人工请求
    UNKNOWN_ERROR = "UNKNOWN_ERROR"                        # 未知错误


class IdempotencyEscalationHandler:
    """升级处理器（REQ-RT-007 §7.3）
    
    负责升级逻辑：
    - 升级到 ESCALATED 状态
    - 记录升级原因和上下文
    - 发送通知（告警、工单）
    - 阻止后续自动重试
    
    Example:
        handler = IdempotencyEscalationHandler(storage)
        
        # 升级到人工处理
        handler.escalate(
            key_id="idem-001",
            reason=EscalationReason.RECONCILIATION_EXHAUSTED,
            context={"attempts": 3, "last_outcome": "STILL_UNKNOWN"},
        )
    """
    
    def __init__(self, storage: IdempotencyStorage) -> None:
        """初始化升级处理器
        
        Args:
            storage: 幂等键存储
        """
        self.storage = storage
    
    def escalate(
        self,
        key_id: str,
        reason: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """升级到人工处理（REQ-RT-007 §7.3）
        
        将幂等键状态更新为 ESCALATED，记录升级原因和上下文，
        发送通知（告警、工单）。
        
        Args:
            key_id: 幂等键 ID
            reason: 升级原因（见 EscalationReason）
            context: 升级上下文（可选）
        
        Returns:
            是否成功升级
        """
        key = self.storage.get(key_id)
        if key is None:
            return False
        
        # 1. 更新状态为 ESCALATED
        updated = self.storage.update_status(key_id, IdempotencyStatus.ESCALATED)
        if not updated:
            return False
        
        # 2. 记录升级事件
        self._record_escalation(key, reason, context)
        
        # 3. 发送通知
        self._send_notification(key, reason, context)
        
        return True
    
    def _record_escalation(
        self,
        key: IdempotencyKey,
        reason: str,
        context: dict[str, Any] | None,
    ) -> None:
        """记录升级事件
        
        Args:
            key: 幂等键
            reason: 升级原因
            context: 升级上下文
        """
        # MVP: 简单日志记录（生产环境应该持久化到事件存储）
        escalation_event = {
            "event_type": "IDEMPOTENCY_ESCALATED",
            "key_id": key.key_id,
            "organization_id": key.organization_id,
            "workflow_id": key.workflow_id,
            "step_id": key.step_id,
            "action_type": key.action_type,
            "reason": reason,
            "context": context or {},
            "escalated_at": utc_now().isoformat(),
        }
        
        # MVP: 仅打印日志
        print(f"[ESCALATION] {escalation_event}")
        
        # 生产环境需要：
        # 1. 持久化到事件存储
        # 2. 发送到消息队列
        # 3. 触发告警
    
    def _send_notification(
        self,
        key: IdempotencyKey,
        reason: str,
        context: dict[str, Any] | None,
    ) -> None:
        """发送通知（告警、工单）
        
        Args:
            key: 幂等键
            reason: 升级原因
            context: 升级上下文
        """
        # MVP: 简单日志通知（生产环境需要集成告警和工单系统）
        notification = {
            "title": f"幂等键升级: {key.key_id}",
            "severity": "HIGH",
            "reason": reason,
            "key_id": key.key_id,
            "organization_id": key.organization_id,
            "workflow_id": key.workflow_id,
            "step_id": key.step_id,
            "action_type": key.action_type,
            "context": context or {},
        }
        
        # MVP: 仅打印通知
        print(f"[NOTIFICATION] {notification}")
        
        # 生产环境需要：
        # 1. 发送告警（PagerDuty, Opsgenie）
        # 2. 创建工单（Jira, Linear）
        # 3. 发送邮件/Slack 通知
    
    def can_retry(self, key_id: str) -> bool:
        """检查是否可以重试
        
        ESCALATED 状态的键不能自动重试，必须人工介入。
        
        Args:
            key_id: 幂等键 ID
        
        Returns:
            是否可以重试
        """
        key = self.storage.get(key_id)
        if key is None:
            return False
        
        # ESCALATED 状态不能自动重试
        if key.status == IdempotencyStatus.ESCALATED:
            return False
        
        # FAILED_FINAL 状态不能重试
        if key.status == IdempotencyStatus.FAILED_FINAL:
            return False
        
        # SUCCEEDED 状态不需要重试
        if key.status == IdempotencyStatus.SUCCEEDED:
            return False
        
        return True
    
    def resolve_manual(
        self,
        key_id: str,
        resolution: IdempotencyStatus,
        notes: str | None = None,
    ) -> bool:
        """人工解决升级的幂等键
        
        Args:
            key_id: 幂等键 ID
            resolution: 解决后的状态（SUCCEEDED / FAILED_FINAL）
            notes: 解决说明
        
        Returns:
            是否成功解决
        """
        key = self.storage.get(key_id)
        if key is None:
            return False
        
        # 只能解决 ESCALATED 状态的键
        if key.status != IdempotencyStatus.ESCALATED:
            return False
        
        # 更新状态
        updated = self.storage.update_status(
            key_id,
            resolution,
            expected_status=IdempotencyStatus.ESCALATED,
        )
        
        if not updated:
            return False
        
        # 记录解决事件
        resolution_event = {
            "event_type": "IDEMPOTENCY_RESOLVED",
            "key_id": key_id,
            "resolution": resolution.value,
            "notes": notes,
            "resolved_at": utc_now().isoformat(),
        }
        
        print(f"[RESOLUTION] {resolution_event}")
        
        return True
