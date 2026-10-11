"""
Kill Switch 状态与作用域枚举（src/security/kill_switch/state.py）。

对齐设计：SEC-009 §3（Kill Switch 状态机）

设计原则：
- 状态机 IDLE → TRIGGERED → RECOVERING → IDLE（二阶段恢复防误操作）
- Scope 分级：global / organization / project / repository（与 SEC-008 对齐）
- 不可变性：所有 enum 值与既有项目状态字符串保持一致
"""
from __future__ import annotations

from enum import Enum


class KillSwitchState(str, Enum):
    """Kill Switch 状态机（SEC-009 §3.1）。"""

    IDLE = "IDLE"
    TRIGGERED = "TRIGGERED"
    RECOVERING = "RECOVERING"


class KillSwitchScope(str, Enum):
    """Kill Switch 触发作用域（SEC-009 §3.2）。

    优先级（从大到小）：GLOBAL > ORGANIZATION > PROJECT > REPOSITORY。
    高优先级 Scope 触发时，所有低优先级都视为 blocked。
    """

    GLOBAL = "GLOBAL"
    ORGANIZATION = "ORGANIZATION"
    PROJECT = "PROJECT"
    REPOSITORY = "REPOSITORY"


# 状态机合法迁移（SEC-009 §3.1）
VALID_TRANSITIONS: dict[KillSwitchState, set[KillSwitchState]] = {
    KillSwitchState.IDLE: {KillSwitchState.TRIGGERED},
    KillSwitchState.TRIGGERED: {KillSwitchState.RECOVERING},
    KillSwitchState.RECOVERING: {KillSwitchState.IDLE},
}


def is_valid_transition(
    current: KillSwitchState, target: KillSwitchState
) -> bool:
    """检查状态迁移是否合法。"""
    return target in VALID_TRANSITIONS.get(current, set())


__all__ = [
    "KillSwitchScope",
    "KillSwitchState",
    "VALID_TRANSITIONS",
    "is_valid_transition",
]