"""
Kill Switch 自动触发器（src/security/kill_switch/triggers/）。

提供：
- Trigger ABC：所有触发器实现
- CredentialLeakTrigger：监听凭据撤销（接入 SEC-004）
- PolicyViolationTrigger：监听 Policy 多次违规
- AnomalyTrigger：异常率突增（MVP 占位：手动 fire）

设计原则：
- 每个触发器是独立组件，可单独 enable/disable
- 默认 enable=False（避免误触发业务）
- 触发时调用 manager.trigger(scope=..., reason=..., trigger_source=trigger_name)
- 不持锁（manager 内部 lock）
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import deque
from datetime import UTC, datetime, timedelta

from src.security.kill_switch.manager import KillSwitchManager
from src.security.kill_switch.state import KillSwitchScope

logger = logging.getLogger(__name__)


class Trigger(ABC):
    """自动触发器基类。"""

    name: str = "abstract"

    def __init__(self, manager: KillSwitchManager) -> None:
        self._manager = manager
        self._enabled: bool = False

    def enable(self) -> None:
        self._enabled = True
        logger.info("trigger %s ENABLED", self.name)

    def disable(self) -> None:
        self._enabled = False
        logger.info("trigger %s DISABLED", self.name)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @abstractmethod
    async def fire(
        self,
        *,
        reason: str = "",
        metadata: dict[str, str] | None = None,
    ) -> bool:
        """触发 Kill Switch；返回 True 表示成功触发。"""


class CredentialLeakTrigger(Trigger):
    """凭据泄露触发器：单次 ≥N 凭据被撤销 → trigger(scope=organization)。

    用法：
        trigger = CredentialLeakTrigger(manager, threshold=10)
        trigger.enable()
        # 当 credential 被 revoke 时：
        await trigger.on_credential_revoked(revocation_event)
    """

    name = "credential_leak"

    def __init__(
        self,
        manager: KillSwitchManager,
        threshold: int = 10,
        window_minutes: int = 5,
    ) -> None:
        super().__init__(manager)
        self._threshold = threshold
        self._window = timedelta(minutes=window_minutes)
        self._recent_revocations: deque[datetime] = deque()

    async def on_credential_revoked(self, _revocation_event: object) -> bool:
        """供外部调用的回调：每次凭据撤销时调用。"""
        if not self._enabled:
            return False
        now = datetime.now(UTC)
        self._recent_revocations.append(now)
        # 清理窗口外的
        while self._recent_revocations and (
            now - self._recent_revocations[0] > self._window
        ):
            self._recent_revocations.popleft()
        if len(self._recent_revocations) >= self._threshold:
            return await self.fire(
                reason=(
                    f"{len(self._recent_revocations)} credentials revoked in "
                    f"{int(self._window.total_seconds() // 60)}min"
                ),
                metadata={"threshold": str(self._threshold)},
            )
        return False

    async def fire(
        self,
        *,
        reason: str = "credential leak threshold exceeded",
        metadata: dict[str, str] | None = None,
    ) -> bool:
        if not self._enabled:
            return False
        await self._manager.trigger(
            scope=KillSwitchScope.ORGANIZATION,
            reason=reason,
            actor_id=f"trigger:{self.name}",
            trigger_source=self.name,
            metadata=metadata or {},
        )
        return True


class PolicyViolationTrigger(Trigger):
    """Policy 违规触发器：1 分钟内 DENY ≥N → trigger(scope=organization)。"""

    name = "policy_violation"

    def __init__(
        self,
        manager: KillSwitchManager,
        threshold: int = 50,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(manager)
        self._threshold = threshold
        self._window = timedelta(seconds=window_seconds)
        self._violations: deque[datetime] = deque()

    async def on_policy_violation(self) -> bool:
        if not self._enabled:
            return False
        now = datetime.now(UTC)
        self._violations.append(now)
        while self._violations and (now - self._violations[0] > self._window):
            self._violations.popleft()
        if len(self._violations) >= self._threshold:
            return await self.fire(
                reason=(
                    f"{len(self._violations)} policy DENY in "
                    f"{self._window.total_seconds()}s"
                ),
                metadata={"threshold": str(self._threshold)},
            )
        return False

    async def fire(
        self,
        *,
        reason: str = "policy violation threshold exceeded",
        metadata: dict[str, str] | None = None,
    ) -> bool:
        if not self._enabled:
            return False
        await self._manager.trigger(
            scope=KillSwitchScope.ORGANIZATION,
            reason=reason,
            actor_id=f"trigger:{self.name}",
            trigger_source=self.name,
            metadata=metadata or {},
        )
        return True


class AnomalyTrigger(Trigger):
    """异常率触发器（占位 MVP：手动 fire）。

    未来：基于 Prometheus / OTel Metrics 的指标突增检测。
    """

    name = "anomaly"

    async def fire(
        self,
        *,
        reason: str = "anomaly detected",
        metadata: dict[str, str] | None = None,
    ) -> bool:
        if not self._enabled:
            return False
        await self._manager.trigger(
            scope=KillSwitchScope.GLOBAL,
            reason=reason,
            actor_id=f"trigger:{self.name}",
            trigger_source=self.name,
            metadata=metadata or {},
        )
        return True


class TriggerRegistry:
    """触发器注册表；管理所有 trigger 的 enable/disable。"""

    def __init__(self, manager: KillSwitchManager) -> None:
        self._manager = manager
        self._triggers: dict[str, Trigger] = {}
        # 默认注册所有 trigger（默认 disable）
        for cls in (CredentialLeakTrigger, PolicyViolationTrigger, AnomalyTrigger):
            t = cls(manager)
            self._triggers[t.name] = t

    def get(self, name: str) -> Trigger | None:
        return self._triggers.get(name)

    def list(self) -> list[Trigger]:
        return list(self._triggers.values())

    def enable(self, name: str) -> None:
        t = self.get(name)
        if t is None:
            raise KeyError(f"unknown trigger: {name}")
        t.enable()

    def disable(self, name: str) -> None:
        t = self.get(name)
        if t is None:
            raise KeyError(f"unknown trigger: {name}")
        t.disable()


__all__ = [
    "AnomalyTrigger",
    "CredentialLeakTrigger",
    "PolicyViolationTrigger",
    "Trigger",
    "TriggerRegistry",
]


# 防止 linter 报 unused import
_ = asyncio