"""
状态机与迁移约束（REQ-RT-002）。

本包实现 Task、Workflow、Worker、Action 四层状态机的合法迁移规则和父子状态
一致性约束，作为后续事件写入（REQ-RT-003）和状态投影更新（REQ-RT-004）的
前置校验层。

本包职责：
- 定义每个状态机的合法迁移路径（transitions.py）
- 校验父子实体状态一致性（validators.py）
- 判定控制状态（暂停/恢复/取消/失败）的允许条件

本包不负责：
- 事件持久化（REQ-RT-003）
- 状态投影查询（REQ-RT-004）
- 具体审批矩阵和 Policy DSL（REQ-SEC-003）
- Checkpoint 恢复协议（REQ-RT-005）
"""
from __future__ import annotations

from src.runtime.state_machine.transitions import (
    can_transition_action,
    can_transition_task,
    can_transition_worker,
    can_transition_workflow,
    is_terminal_state_action,
    is_terminal_state_task,
    is_terminal_state_worker,
    is_terminal_state_workflow,
)
from src.runtime.state_machine.validators import (
    validate_parent_child_consistency,
)

__all__ = [
    "can_transition_task",
    "can_transition_workflow",
    "can_transition_worker",
    "can_transition_action",
    "is_terminal_state_task",
    "is_terminal_state_workflow",
    "is_terminal_state_worker",
    "is_terminal_state_action",
    "validate_parent_child_consistency",
]
