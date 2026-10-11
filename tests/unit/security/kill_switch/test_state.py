"""Kill Switch 状态机单元测试。"""
from __future__ import annotations

import pytest

from src.security.kill_switch.state import (
    KillSwitchScope,
    KillSwitchState,
    is_valid_transition,
)


class TestStateMachine:
    """状态机迁移合法性。"""

    def test_idle_to_triggered_valid(self) -> None:
        """IDLE → TRIGGERED 合法。"""
        assert is_valid_transition(KillSwitchState.IDLE, KillSwitchState.TRIGGERED)

    def test_triggered_to_recovering_valid(self) -> None:
        """TRIGGERED → RECOVERING 合法。"""
        assert is_valid_transition(
            KillSwitchState.TRIGGERED, KillSwitchState.RECOVERING
        )

    def test_recovering_to_idle_valid(self) -> None:
        """RECOVERING → IDLE 合法。"""
        assert is_valid_transition(KillSwitchState.RECOVERING, KillSwitchState.IDLE)

    @pytest.mark.parametrize(
        "src,target",
        [
            (KillSwitchState.IDLE, KillSwitchState.RECOVERING),
            (KillSwitchState.RECOVERING, KillSwitchState.TRIGGERED),
            (KillSwitchState.TRIGGERED, KillSwitchState.IDLE),
            (KillSwitchState.IDLE, KillSwitchState.IDLE),
            (KillSwitchState.TRIGGERED, KillSwitchState.TRIGGERED),
        ],
    )
    def test_illegal_transitions(self, src: KillSwitchState, target: KillSwitchState) -> None:
        """非法迁移一律拒绝。"""
        assert not is_valid_transition(src, target)


class TestScope:
    """Scope 枚举值与顺序。"""

    def test_scope_values(self) -> None:
        """Scope 值与 SEC-008 多租户层级一致。"""
        assert KillSwitchScope.GLOBAL.value == "GLOBAL"
        assert KillSwitchScope.ORGANIZATION.value == "ORGANIZATION"
        assert KillSwitchScope.PROJECT.value == "PROJECT"
        assert KillSwitchScope.REPOSITORY.value == "REPOSITORY"
