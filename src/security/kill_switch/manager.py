"""
Kill Switch 核心管理器（src/security/kill_switch/manager.py）。

职责（SEC-009 §3.1）：
- 维护全局 IDLE/TRIGGERED/RECOVERING 状态
- 接受 trigger / recover / confirm 操作
- 提供 is_blocked 判定（被 Gate 调用）
- 写审计日志（kv 结构 + OTel 占位）
- 持久化到 InMemoryProjectionStorage（与 Task 共享；可扩展至 Redis）

设计原则：
- 单进程 MVP（用内存 + 持久化存储）
- 线程安全：asyncio.Lock（ActionExecutor 调用异步方法）
- 状态机不变量严格遵守（防止非法迁移）
- 二阶段恢复：recover_request → 30 分钟内 confirm_token 必须使用，否则过期
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from src.runtime.common.types import generate_entity_id
from src.security.kill_switch.models import (
    BlockReason,
    RecoveryConfirmEvent,
    RecoveryRequestEvent,
    StatusView,
    TriggerEvent,
)
from src.security.kill_switch.state import (
    KillSwitchScope,
    KillSwitchState,
    is_valid_transition,
)

logger = logging.getLogger(__name__)


# 二阶段恢复有效期（30 分钟）
RECOVERY_CONFIRM_WINDOW = timedelta(minutes=30)


class KillSwitchManager:
    """Kill Switch 状态机管理器（核心）。

    集成模式：
    - ActionExecutor 在执行工具前调用 `is_blocked(context)`
    - Admin API 调用 `trigger / request_recovery / confirm_recovery`
    - 状态变更通过 `add_audit_listener` 注册的回调写 OTel
    """

    def __init__(self) -> None:
        self._state: KillSwitchState = KillSwitchState.IDLE
        self._current_trigger: TriggerEvent | None = None
        self._current_recovery: RecoveryRequestEvent | None = None
        self._history: list[TriggerEvent] = []
        self._recovery_history: list[RecoveryConfirmEvent] = []
        self._lock = asyncio.Lock()
        self._audit_listeners: list = []
        self._total_triggers: int = 0

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_state(self) -> KillSwitchState:
        """当前状态（无锁读；状态机迁移通过 lock 串行化保证一致性）。"""
        return self._state

    def get_status(self) -> StatusView:
        """当前状态对外视图。"""
        last_updated = None
        if self._current_trigger:
            last_updated = self._current_trigger.triggered_at
        elif self._current_recovery:
            last_updated = self._current_recovery.requested_at
        return StatusView(
            state=self._state,
            current_trigger=self._current_trigger,
            current_recovery=self._current_recovery,
            total_triggers=self._total_triggers,
            last_updated_at=last_updated,
        )

    # ------------------------------------------------------------------
    # Gate 接口（被 ActionExecutor 调用）
    # ------------------------------------------------------------------

    def is_blocked(
        self,
        *,
        organization_id: str | None = None,
        project_id: str | None = None,
        repository_id: str | None = None,
    ) -> BlockReason:
        """判定给定上下文是否被 Kill Switch 阻止。

        优先级：GLOBAL > ORGANIZATION > PROJECT > REPOSITORY
        （高优先级 scope 触发时，所有低优先级都视为 blocked）

        设计选择：fail-open。如果 manager 状态正常但无 trigger，视为放行；
        状态异常（极端情况）也放行，但记录告警。
        """
        if self._state == KillSwitchState.IDLE:
            return BlockReason(
                blocked=False, current_state=self._state, current_scope=None
            )

        if self._state in {
            KillSwitchState.TRIGGERED,
            KillSwitchState.RECOVERING,
        }:
            # 触发器是 GLOBAL → 全部阻止
            if (
                self._current_trigger
                and self._current_trigger.scope == KillSwitchScope.GLOBAL
            ):
                return BlockReason(
                    blocked=True,
                    reason=f"global kill switch triggered: {self._current_trigger.reason}",
                    current_state=self._state,
                    current_scope=KillSwitchScope.GLOBAL,
                    trigger_event_id=self._current_trigger.event_id,
                )

            # 其他 scope：按层次匹配
            assert self._current_trigger is not None  # type-narrow
            scope = self._current_trigger.scope
            blocked = False
            reason_extra = ""
            if scope == KillSwitchScope.ORGANIZATION:
                # 注：MVP 不校验 organization_id（上下文没有 organization 概念）
                blocked = True
                reason_extra = (
                    f" (org={self._current_trigger.metadata.get('organization_id', '?')})"
                )
            elif scope == KillSwitchScope.PROJECT:
                blocked = True
                reason_extra = f" (project={self._current_trigger.metadata.get('project_id', '?')})"
            elif scope == KillSwitchScope.REPOSITORY:
                blocked = True
                reason_extra = f" (repo={self._current_trigger.metadata.get('repository_id', '?')})"

            return BlockReason(
                blocked=blocked,
                reason=(
                    f"kill switch {self._state.value} {scope.value}{reason_extra}: "
                    f"{self._current_trigger.reason}"
                    if blocked
                    else ""
                ),
                current_state=self._state,
                current_scope=scope,
                trigger_event_id=self._current_trigger.event_id,
            )

        return BlockReason(
            blocked=False, current_state=self._state, current_scope=None
        )

    # ------------------------------------------------------------------
    # 状态变更
    # ------------------------------------------------------------------

    async def trigger(
        self,
        *,
        scope: KillSwitchScope,
        reason: str,
        actor_id: str,
        trigger_source: str = "manual",
        metadata: dict[str, str] | None = None,
    ) -> TriggerEvent:
        """触发 Kill Switch（IDLE → TRIGGERED）。

        副作用：
        - 拒绝所有新工具调用（is_blocked=True）
        - 写审计日志
        - 增加 total_triggers 计数
        - 不撤销凭据（由调用方触发 SEC-004 撤销，避免循环依赖）
        """
        async with self._lock:
            if not is_valid_transition(self._state, KillSwitchState.TRIGGERED):
                raise RuntimeError(
                    f"cannot trigger from state={self._state.value}"
                )

            event = TriggerEvent(
                event_id=generate_entity_id(),
                scope=scope,
                reason=reason,
                actor_id=actor_id,
                triggered_at=datetime.now(UTC),
                trigger_source=trigger_source,
                metadata=metadata or {},
            )
            self._state = KillSwitchState.TRIGGERED
            self._current_trigger = event
            self._current_recovery = None
            self._history.append(event)
            self._total_triggers += 1
            await self._emit_audit(
                event_type="trigger",
                payload=event.model_dump(mode="json"),
            )
            logger.warning(
                "kill switch TRIGGERED: scope=%s reason=%s actor=%s",
                scope.value,
                reason,
                actor_id,
            )
            return event

    async def request_recovery(
        self, *, actor_id: str, reason: str = ""
    ) -> RecoveryRequestEvent:
        """阶段 1：进入 RECOVERING（TRIGGERED → RECOVERING）；返回 confirm_token。

        阶段 1 仅做"准备解除"，仍处于 blocked 状态。
        调用方必须在 RECOVERY_CONFIRM_WINDOW 内用 confirm_token 走 confirm_recovery。
        """
        async with self._lock:
            if not is_valid_transition(self._state, KillSwitchState.RECOVERING):
                raise RuntimeError(
                    f"cannot request_recovery from state={self._state.value}"
                )

            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            event = RecoveryRequestEvent(
                event_id=generate_entity_id(),
                confirm_token=token_hash,  # 存哈希而非明文
                requested_at=datetime.now(UTC),
                actor_id=actor_id,
                reason=reason,
            )
            self._state = KillSwitchState.RECOVERING
            self._current_recovery = event
            await self._emit_audit(
                event_type="recovery_request",
                payload=event.model_dump(mode="json"),
            )
            logger.warning(
                "kill switch RECOVERY_REQUESTED: actor=%s reason=%s",
                actor_id,
                reason,
            )
            # 返回 event，但用 raw_token 替换 confirm_token（明文 token 仅在
            # 本次响应中给调用方；服务端存哈希）
            return event.model_copy(update={"confirm_token": raw_token})

    async def confirm_recovery(
        self, *, confirm_token: str, actor_id: str
    ) -> RecoveryConfirmEvent:
        """阶段 2：解除冻结（RECOVERING → IDLE）。"""
        async with self._lock:
            if self._state != KillSwitchState.RECOVERING:
                raise RuntimeError(
                    f"cannot confirm_recovery from state={self._state.value}"
                )
            if self._current_recovery is None:
                raise RuntimeError("no pending recovery request")

            # 校验 token + 时窗
            provided_hash = hashlib.sha256(confirm_token.encode()).hexdigest()
            if provided_hash != self._current_recovery.confirm_token:
                raise ValueError("invalid confirm_token")

            now = datetime.now(UTC)
            if (
                now - self._current_recovery.requested_at
            ) > RECOVERY_CONFIRM_WINDOW:
                raise ValueError("confirm_token expired")

            event = RecoveryConfirmEvent(
                event_id=generate_entity_id(),
                confirm_token=provided_hash,
                confirmed_at=now,
                actor_id=actor_id,
            )
            self._state = KillSwitchState.IDLE
            self._recovery_history.append(event)
            previous_trigger = self._current_trigger
            self._current_trigger = None
            self._current_recovery = None
            await self._emit_audit(
                event_type="recovery_confirm",
                payload=event.model_dump(mode="json"),
            )
            logger.warning(
                "kill switch RECOVERED: actor=%s previous_trigger=%s",
                actor_id,
                previous_trigger.event_id if previous_trigger else "?",
            )
            return event

    # ------------------------------------------------------------------
    # 审计
    # ------------------------------------------------------------------

    def add_audit_listener(self, callback: Any) -> None:
        """注册审计回调（如 OTel span writer）。"""
        self._audit_listeners.append(callback)

    async def _emit_audit(self, *, event_type: str, payload: dict) -> None:
        """触发所有审计监听器；监听器失败不影响主流程（fail-open 审计）。"""
        for listener in self._audit_listeners:
            try:
                result = listener(event_type=event_type, payload=payload)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:  # noqa: BLE001
                logger.error("audit listener failed: %s", exc)


__all__ = ["RECOVERY_CONFIRM_WINDOW", "KillSwitchManager"]
