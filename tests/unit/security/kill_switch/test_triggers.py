"""Kill Switch 自动触发器测试。"""
from __future__ import annotations

import pytest

from src.security.kill_switch import (
    CredentialLeakTrigger,
    KillSwitchManager,
    KillSwitchScope,
    KillSwitchState,
    PolicyViolationTrigger,
    TriggerRegistry,
)


class TestCredentialLeakTrigger:
    def _make(self) -> tuple[CredentialLeakTrigger, KillSwitchManager]:
        m = KillSwitchManager()
        t = CredentialLeakTrigger(m, threshold=3, window_minutes=5)
        return t, m

    @pytest.mark.asyncio
    async def test_disabled_by_default(self) -> None:
        t, m = self._make()
        assert not t.enabled
        # 禁用时不触发
        result = await t.on_credential_revoked(object())
        assert result is False
        assert m.get_state() == KillSwitchState.IDLE

    @pytest.mark.asyncio
    async def test_threshold_triggers_kill_switch(self) -> None:
        t, m = self._make()
        t.enable()
        for _ in range(3):
            fired = await t.on_credential_revoked(object())
        # 第三次达到阈值
        assert fired is True
        assert m.get_state() == KillSwitchState.TRIGGERED
        assert m.get_status().current_trigger is not None
        assert m.get_status().current_trigger.scope == KillSwitchScope.ORGANIZATION


class TestPolicyViolationTrigger:
    def _make(self) -> tuple[PolicyViolationTrigger, KillSwitchManager]:
        m = KillSwitchManager()
        t = PolicyViolationTrigger(m, threshold=5, window_seconds=60)
        return t, m

    @pytest.mark.asyncio
    async def test_disabled_does_nothing(self) -> None:
        t, m = self._make()
        for _ in range(10):
            await t.on_policy_violation()
        assert m.get_state() == KillSwitchState.IDLE

    @pytest.mark.asyncio
    async def test_threshold_triggers(self) -> None:
        t, m = self._make()
        t.enable()
        for _ in range(5):
            await t.on_policy_violation()
        assert m.get_state() == KillSwitchState.TRIGGERED


class TestTriggerRegistry:
    def test_registers_all_default_triggers(self) -> None:
        m = KillSwitchManager()
        reg = TriggerRegistry(m)
        assert reg.get("credential_leak") is not None
        assert reg.get("policy_violation") is not None
        assert reg.get("anomaly") is not None
        assert reg.get("nonexistent") is None

    def test_enable_disable(self) -> None:
        m = KillSwitchManager()
        reg = TriggerRegistry(m)
        reg.enable("credential_leak")
        assert reg.get("credential_leak").enabled  # type: ignore[union-attr]
        reg.disable("credential_leak")
        assert not reg.get("credential_leak").enabled  # type: ignore[union-attr]

    def test_unknown_trigger_raises(self) -> None:
        m = KillSwitchManager()
        reg = TriggerRegistry(m)
        with pytest.raises(KeyError):
            reg.enable("nonexistent")
