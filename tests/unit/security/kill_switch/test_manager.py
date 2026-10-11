"""KillSwitchManager 状态机核心测试。"""
from __future__ import annotations

import pytest

from src.security.kill_switch import (
    KillSwitchManager,
    KillSwitchScope,
    KillSwitchState,
)


class TestKillSwitchManager:
    """状态机 IDLE/TRIGGERED/RECOVERING/IDLE 完整迁移。"""

    def _make(self) -> KillSwitchManager:
        return KillSwitchManager()

    @pytest.mark.asyncio
    async def test_initial_state_is_idle(self) -> None:
        m = self._make()
        assert m.get_state() == KillSwitchState.IDLE
        assert m.is_blocked().blocked is False

    @pytest.mark.asyncio
    async def test_trigger_from_idle(self) -> None:
        m = self._make()
        event = await m.trigger(
            scope=KillSwitchScope.GLOBAL,
            reason="test",
            actor_id="user-1",
        )
        assert m.get_state() == KillSwitchState.TRIGGERED
        assert event.scope == KillSwitchScope.GLOBAL
        assert event.reason == "test"
        assert event.trigger_source == "manual"

    @pytest.mark.asyncio
    async def test_trigger_from_triggered_fails(self) -> None:
        m = self._make()
        await m.trigger(
            scope=KillSwitchScope.GLOBAL, reason="first", actor_id="u1"
        )
        with pytest.raises(RuntimeError):
            await m.trigger(
                scope=KillSwitchScope.GLOBAL, reason="second", actor_id="u2"
            )

    @pytest.mark.asyncio
    async def test_request_recovery_returns_token(self) -> None:
        m = self._make()
        await m.trigger(
            scope=KillSwitchScope.GLOBAL, reason="test", actor_id="u1"
        )
        event = await m.request_recovery(actor_id="u1", reason="fixed")
        assert m.get_state() == KillSwitchState.RECOVERING
        assert event.confirm_token
        assert len(event.confirm_token) >= 16

    @pytest.mark.asyncio
    async def test_confirm_recovery_with_valid_token(self) -> None:
        m = self._make()
        await m.trigger(
            scope=KillSwitchScope.GLOBAL, reason="test", actor_id="u1"
        )
        req = await m.request_recovery(actor_id="u1")
        await m.confirm_recovery(
            confirm_token=req.confirm_token, actor_id="u1"
        )
        assert m.get_state() == KillSwitchState.IDLE

    @pytest.mark.asyncio
    async def test_confirm_with_invalid_token_raises(self) -> None:
        m = self._make()
        await m.trigger(
            scope=KillSwitchScope.GLOBAL, reason="test", actor_id="u1"
        )
        await m.request_recovery(actor_id="u1")
        with pytest.raises(ValueError):
            await m.confirm_recovery(
                confirm_token="wrong-token", actor_id="u1"
            )

    @pytest.mark.asyncio
    async def test_request_recovery_from_idle_raises(self) -> None:
        m = self._make()
        with pytest.raises(RuntimeError):
            await m.request_recovery(actor_id="u1")

    @pytest.mark.asyncio
    async def test_is_blocked_during_triggered(self) -> None:
        m = self._make()
        await m.trigger(
            scope=KillSwitchScope.GLOBAL, reason="emergency", actor_id="u1"
        )
        result = m.is_blocked()
        assert result.blocked is True
        assert "emergency" in result.reason
        assert result.current_scope == KillSwitchScope.GLOBAL
        assert result.trigger_event_id

    @pytest.mark.asyncio
    async def test_audit_listener_called(self) -> None:
        m = self._make()
        captured: list[tuple[str, dict]] = []

        def listener(event_type: str, payload: dict) -> None:
            captured.append((event_type, payload))

        m.add_audit_listener(listener)
        await m.trigger(
            scope=KillSwitchScope.GLOBAL, reason="x", actor_id="u1"
        )
        assert any(et == "trigger" for et, _ in captured)

    @pytest.mark.asyncio
    async def test_get_status_increments_counter(self) -> None:
        m = self._make()
        s1 = m.get_status()
        assert s1.total_triggers == 0
        await m.trigger(
            scope=KillSwitchScope.GLOBAL, reason="a", actor_id="u1"
        )
        s2 = m.get_status()
        assert s2.total_triggers == 1
        assert s2.state == KillSwitchState.TRIGGERED
        assert s2.current_trigger is not None

    @pytest.mark.asyncio
    async def test_recover_with_token_then_idle(self) -> None:
        """完整 IDLE→TRIGGERED→RECOVERING→IDLE 循环。"""
        m = self._make()
        await m.trigger(
            scope=KillSwitchScope.GLOBAL, reason="x", actor_id="u1"
        )
        assert m.get_state() == KillSwitchState.TRIGGERED

        req = await m.request_recovery(actor_id="u1")
        assert m.get_state() == KillSwitchState.RECOVERING

        await m.confirm_recovery(
            confirm_token=req.confirm_token, actor_id="u1"
        )
        assert m.get_state() == KillSwitchState.IDLE
        assert m.is_blocked().blocked is False


class TestIsBlockedScopes:
    """is_blocked 各级 scope 行为。"""

    def _make(self) -> KillSwitchManager:
        return KillSwitchManager()

    @pytest.mark.asyncio
    async def test_global_blocks_everything(self) -> None:
        m = self._make()
        await m.trigger(
            scope=KillSwitchScope.GLOBAL, reason="g", actor_id="u"
        )
        # 所有组织/项目/仓库都被阻止
        assert m.is_blocked(organization_id="org-1").blocked
        assert m.is_blocked(project_id="proj-1").blocked
        assert m.is_blocked(repository_id="repo-1").blocked

    @pytest.mark.asyncio
    async def test_organization_scope_blocks(self) -> None:
        m = self._make()
        await m.trigger(
            scope=KillSwitchScope.ORGANIZATION, reason="o", actor_id="u"
        )
        assert m.is_blocked(organization_id="any").blocked
