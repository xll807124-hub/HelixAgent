"""
状态迁移规则（REQ-RT-002 §5-8）。

本模块定义 Task、Workflow、Worker、Action 四层状态机的合法迁移映射表。
迁移表只表达"哪些状态间的转换在逻辑上是合法的"，不包含前置条件判断（如预算、
权限、Artifact 存在性等），那些由调用方在迁移请求前额外校验。

设计原则：
- 迁移表采用 frozenset 表达允许的目标状态集合，便于 O(1) 查找
- 终态（COMPLETED/CANCELLED/FAILED）到任何其他状态的迁移默认非法
- 暂停(PAUSED)可以恢复到暂停前的来源状态，具体恢复路径由调用方决定
- 本模块只做"是否允许迁移"的判断，不改变实体状态（状态变更由事件驱动）
"""
from __future__ import annotations

from src.runtime.entities import (
    ActionStatus,
    TaskStatus,
    WorkerStatus,
    WorkflowStatus,
)

# ==============================================================================
# 终态定义（REQ-RT-002 §4 终态保护）
# ==============================================================================

# Task 终态：完成、取消、失败后不能再迁移到其他状态
_TASK_TERMINAL_STATES = frozenset([
    TaskStatus.COMPLETED,
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
])

# Workflow 终态
_WORKFLOW_TERMINAL_STATES = frozenset([
    WorkflowStatus.COMPLETED,
    WorkflowStatus.CANCELLED,
    WorkflowStatus.FAILED,
])

# Worker 终态
_WORKER_TERMINAL_STATES = frozenset([
    WorkerStatus.COMPLETED,
    WorkerStatus.CANCELLED,
    WorkerStatus.FAILED,
])

# Action 终态（注意：Action 的 REJECTED 也是终态）
_ACTION_TERMINAL_STATES = frozenset([
    ActionStatus.SUCCEEDED,
    ActionStatus.FAILED,
    ActionStatus.REJECTED,
    ActionStatus.CANCELLED,
])

# ==============================================================================
# Task 状态机迁移表（REQ-RT-002 §5）
# ==============================================================================

# Task 正常推进路径的合法迁移
_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset([TaskStatus.AUTHORIZING]),
    TaskStatus.AUTHORIZING: frozenset([
        TaskStatus.PLANNING,
        TaskStatus.PAUSED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    ]),
    TaskStatus.PLANNING: frozenset([
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.PREPARING_WORKSPACE,
        TaskStatus.PAUSED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    ]),
    TaskStatus.WAITING_APPROVAL: frozenset([
        TaskStatus.PREPARING_WORKSPACE,
        TaskStatus.EXECUTING,
        TaskStatus.PAUSED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    ]),
    TaskStatus.PREPARING_WORKSPACE: frozenset([
        TaskStatus.EXECUTING,
        TaskStatus.PAUSED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    ]),
    TaskStatus.EXECUTING: frozenset([
        TaskStatus.VALIDATING,
        TaskStatus.PAUSED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    ]),
    TaskStatus.VALIDATING: frozenset([
        TaskStatus.EXECUTING,  # 验证失败可回到修复流程
        TaskStatus.CREATING_PR,
        TaskStatus.PAUSED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    ]),
    TaskStatus.CREATING_PR: frozenset([
        TaskStatus.WAITING_REVIEW,
        TaskStatus.PAUSED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    ]),
    TaskStatus.WAITING_REVIEW: frozenset([
        TaskStatus.COMPLETED,
        TaskStatus.PAUSED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    ]),
    # 暂停可恢复到允许继续的状态（由调用方根据暂停前状态决定）
    TaskStatus.PAUSED: frozenset([
        TaskStatus.AUTHORIZING,
        TaskStatus.PLANNING,
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.PREPARING_WORKSPACE,
        TaskStatus.EXECUTING,
        TaskStatus.VALIDATING,
        TaskStatus.CREATING_PR,
        TaskStatus.WAITING_REVIEW,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    ]),
    # 终态不允许迁移到其他状态
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.FAILED: frozenset(),
}


def can_transition_task(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    """
    判断 Task 状态迁移是否合法。

    Args:
        from_status: 当前状态
        to_status: 目标状态

    Returns:
        True 表示该迁移在状态机层面合法，False 表示非法迁移

    注意：
        本函数只判断状态迁移的逻辑合法性，不检查前置条件（如预算、权限、
        Artifact 存在性等），调用方需要在迁移请求前额外校验这些条件。
    
    幂等性：
        相同状态的迁移（from_status == to_status）始终返回 True，支持幂等重试。
    """
    # 幂等迁移：目标状态与当前状态相同，允许（支持幂等重试）
    if from_status == to_status:
        return True
    
    allowed_targets = _TASK_TRANSITIONS.get(from_status, frozenset())
    return to_status in allowed_targets


# ==============================================================================
# Workflow 状态机迁移表（REQ-RT-002 §6）
# ==============================================================================

_WORKFLOW_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.CREATED: frozenset([
        WorkflowStatus.READY,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.FAILED,
    ]),
    WorkflowStatus.READY: frozenset([
        WorkflowStatus.RUNNING,
        WorkflowStatus.PAUSED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.FAILED,
    ]),
    WorkflowStatus.RUNNING: frozenset([
        WorkflowStatus.WAITING_APPROVAL,
        WorkflowStatus.COMPLETED,
        WorkflowStatus.PAUSED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.FAILED,
    ]),
    WorkflowStatus.WAITING_APPROVAL: frozenset([
        WorkflowStatus.RUNNING,
        WorkflowStatus.PAUSED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.FAILED,
    ]),
    WorkflowStatus.PAUSED: frozenset([
        WorkflowStatus.READY,
        WorkflowStatus.RUNNING,
        WorkflowStatus.WAITING_APPROVAL,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.FAILED,
    ]),
    # 终态
    WorkflowStatus.COMPLETED: frozenset(),
    WorkflowStatus.CANCELLED: frozenset(),
    WorkflowStatus.FAILED: frozenset(),
}


def can_transition_workflow(
    from_status: WorkflowStatus, to_status: WorkflowStatus
) -> bool:
    """
    判断 Workflow 状态迁移是否合法。

    Args:
        from_status: 当前状态
        to_status: 目标状态

    Returns:
        True 表示该迁移在状态机层面合法，False 表示非法迁移
    
    幂等性：
        相同状态的迁移（from_status == to_status）始终返回 True，支持幂等重试。
    """
    # 幂等迁移：目标状态与当前状态相同，允许（支持幂等重试）
    if from_status == to_status:
        return True
    
    allowed_targets = _WORKFLOW_TRANSITIONS.get(from_status, frozenset())
    return to_status in allowed_targets


# ==============================================================================
# Worker 状态机迁移表（REQ-RT-002 §7）
# ==============================================================================

_WORKER_TRANSITIONS: dict[WorkerStatus, frozenset[WorkerStatus]] = {
    WorkerStatus.CREATED: frozenset([
        WorkerStatus.READY,
        WorkerStatus.CANCELLED,
        WorkerStatus.FAILED,
    ]),
    WorkerStatus.READY: frozenset([
        WorkerStatus.RUNNING,
        WorkerStatus.PAUSED,
        WorkerStatus.CANCELLED,
        WorkerStatus.FAILED,
    ]),
    WorkerStatus.RUNNING: frozenset([
        WorkerStatus.WAITING_APPROVAL,
        WorkerStatus.COMPLETED,
        WorkerStatus.PAUSED,
        WorkerStatus.CANCELLED,
        WorkerStatus.FAILED,
    ]),
    WorkerStatus.WAITING_APPROVAL: frozenset([
        WorkerStatus.RUNNING,
        WorkerStatus.PAUSED,
        WorkerStatus.CANCELLED,
        WorkerStatus.FAILED,
    ]),
    WorkerStatus.PAUSED: frozenset([
        WorkerStatus.READY,
        WorkerStatus.RUNNING,
        WorkerStatus.WAITING_APPROVAL,
        WorkerStatus.CANCELLED,
        WorkerStatus.FAILED,
    ]),
    # 终态
    WorkerStatus.COMPLETED: frozenset(),
    WorkerStatus.CANCELLED: frozenset(),
    WorkerStatus.FAILED: frozenset(),
}


def can_transition_worker(from_status: WorkerStatus, to_status: WorkerStatus) -> bool:
    """
    判断 Worker 状态迁移是否合法。

    Args:
        from_status: 当前状态
        to_status: 目标状态

    Returns:
        True 表示该迁移在状态机层面合法，False 表示非法迁移
    
    幂等性：
        相同状态的迁移（from_status == to_status）始终返回 True，支持幂等重试。
    """
    # 幂等迁移：目标状态与当前状态相同，允许（支持幂等重试）
    if from_status == to_status:
        return True
    
    allowed_targets = _WORKER_TRANSITIONS.get(from_status, frozenset())
    return to_status in allowed_targets


# ==============================================================================
# Action 状态机迁移表（REQ-RT-002 §8）
# ==============================================================================

_ACTION_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROPOSED: frozenset([
        ActionStatus.AUTHORIZED,
        ActionStatus.WAITING_APPROVAL,
        ActionStatus.REJECTED,
        ActionStatus.CANCELLED,
    ]),
    ActionStatus.AUTHORIZED: frozenset([
        ActionStatus.EXECUTING,
        ActionStatus.CANCELLED,
    ]),
    ActionStatus.WAITING_APPROVAL: frozenset([
        ActionStatus.AUTHORIZED,
        ActionStatus.REJECTED,
        ActionStatus.CANCELLED,
    ]),
    ActionStatus.EXECUTING: frozenset([
        ActionStatus.SUCCEEDED,
        ActionStatus.FAILED,
        ActionStatus.CANCELLED,
    ]),
    # 终态
    ActionStatus.SUCCEEDED: frozenset(),
    ActionStatus.FAILED: frozenset(),
    ActionStatus.REJECTED: frozenset(),
    ActionStatus.CANCELLED: frozenset(),
}


def can_transition_action(from_status: ActionStatus, to_status: ActionStatus) -> bool:
    """
    判断 Action 状态迁移是否合法。

    Args:
        from_status: 当前状态
        to_status: 目标状态

    Returns:
        True 表示该迁移在状态机层面合法，False 表示非法迁移
    
    幂等性：
        相同状态的迁移（from_status == to_status）始终返回 True，支持幂等重试。
    """
    # 幂等迁移：目标状态与当前状态相同，允许（支持幂等重试）
    if from_status == to_status:
        return True
    
    allowed_targets = _ACTION_TRANSITIONS.get(from_status, frozenset())
    return to_status in allowed_targets


# ==============================================================================
# 终态和状态查询辅助函数（REQ-RT-002 §4）
# ==============================================================================

def is_terminal_state_task(status: TaskStatus) -> bool:
    """判断 Task 状态是否为终态（COMPLETED/CANCELLED/FAILED）。"""
    return status in _TASK_TERMINAL_STATES


def is_terminal_state_workflow(status: WorkflowStatus) -> bool:
    """判断 Workflow 状态是否为终态（COMPLETED/CANCELLED/FAILED）。"""
    return status in _WORKFLOW_TERMINAL_STATES


def is_terminal_state_worker(status: WorkerStatus) -> bool:
    """判断 Worker 状态是否为终态（COMPLETED/CANCELLED/FAILED）。"""
    return status in _WORKER_TERMINAL_STATES


def is_terminal_state_action(status: ActionStatus) -> bool:
    """判断 Action 状态是否为终态（SUCCEEDED/FAILED/REJECTED/CANCELLED）。"""
    return status in _ACTION_TERMINAL_STATES
