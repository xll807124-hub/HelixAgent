"""
父子状态一致性校验（REQ-RT-002 §10）。

本模块实现四层状态机之间的父子状态一致性约束校验，确保：
- Task 与 Workflow 的状态约束
- Workflow 与 Worker 的状态约束
- Worker 与 Action 的状态约束

设计原则：
- 校验函数接受父实体和子实体的当前状态，返回是否允许子实体进入目标状态
- 不检查实体 ID 关联的正确性（由调用方保证 workflow_id/worker_id 引用有效）
- 不检查前置条件（预算、权限、Artifact 存在性等），只检查状态约束
"""
from __future__ import annotations

from src.runtime.entities import (
    ActionStatus,
    TaskStatus,
    WorkerStatus,
    WorkflowStatus,
)


def can_workflow_run_under_task(task_status: TaskStatus) -> bool:
    """
    判断给定 Task 状态下，其子 Workflow 是否允许进入 RUNNING 状态。

    REQ-RT-002 §10.1 约束1：Task 未进入允许执行的阶段时，Workflow 不得进入 RUNNING。

    Args:
        task_status: Task 当前状态

    Returns:
        True 表示允许 Workflow 进入 RUNNING，False 表示不允许
    """
    # Task 允许执行的阶段包括：PREPARING_WORKSPACE, EXECUTING, VALIDATING, CREATING_PR
    allowed_task_statuses = {
        TaskStatus.PREPARING_WORKSPACE,
        TaskStatus.EXECUTING,
        TaskStatus.VALIDATING,
        TaskStatus.CREATING_PR,
    }
    return task_status in allowed_task_statuses


def can_workflow_continue_under_task(
    task_status: TaskStatus, workflow_target_status: WorkflowStatus
) -> bool:
    """
    判断给定 Task 状态下，其子 Workflow 是否允许继续推进业务 Action。

    REQ-RT-002 §10.1 约束2/3：
    - Task 进入 PAUSED 时，当前 Workflow 不得继续推进新的业务 Action
    - Task 进入 CANCELLED 后，当前 Workflow 必须进入取消或清理路径

    Args:
        task_status: Task 当前状态
        workflow_target_status: Workflow 目标状态

    Returns:
        True 表示允许 Workflow 进入目标状态，False 表示不允许
    """
    # Task 被取消后，Workflow 只能进入 CANCELLED/FAILED，不能进入 RUNNING/WAITING_APPROVAL
    if task_status == TaskStatus.CANCELLED:
        return workflow_target_status in {
            WorkflowStatus.CANCELLED,
            WorkflowStatus.FAILED,
            WorkflowStatus.PAUSED,  # 允许已暂停的保持暂停
        }

    # Task 暂停时，Workflow 不能进入 RUNNING
    if task_status == TaskStatus.PAUSED:
        return workflow_target_status != WorkflowStatus.RUNNING

    return True


def can_worker_run_under_workflow(workflow_status: WorkflowStatus) -> bool:
    """
    判断给定 Workflow 状态下，其子 Worker 是否允许进入 RUNNING 状态。

    REQ-RT-002 §10.2 约束1：Workflow 未处于 READY 或 RUNNING 等允许调度的状态时，
    Worker 不得进入 RUNNING。

    Args:
        workflow_status: Workflow 当前状态

    Returns:
        True 表示允许 Worker 进入 RUNNING，False 表示不允许
    """
    allowed_workflow_statuses = {
        WorkflowStatus.READY,
        WorkflowStatus.RUNNING,
    }
    return workflow_status in allowed_workflow_statuses


def can_worker_continue_under_workflow(
    workflow_status: WorkflowStatus, worker_target_status: WorkerStatus
) -> bool:
    """
    判断给定 Workflow 状态下，其子 Worker 是否允许继续推进。

    REQ-RT-002 §10.2 约束2：Workflow 进入 WAITING_APPROVAL 时，依赖该审批的 Worker
    必须停止推进。

    Args:
        workflow_status: Workflow 当前状态
        worker_target_status: Worker 目标状态

    Returns:
        True 表示允许 Worker 进入目标状态，False 表示不允许
    """
    # Workflow 等待审批时，Worker 不能进入 RUNNING（但可以保持现有状态或进入等待）
    if workflow_status == WorkflowStatus.WAITING_APPROVAL:
        return worker_target_status in {
            WorkerStatus.WAITING_APPROVAL,
            WorkerStatus.PAUSED,
            WorkerStatus.CANCELLED,
            WorkerStatus.FAILED,
            WorkerStatus.READY,  # 允许还未启动的 Worker 保持 READY
            WorkerStatus.CREATED,  # 允许新创建的 Worker 保持 CREATED
        }

    # Workflow 被取消或失败时，Worker 只能进入非业务执行状态
    if workflow_status in {WorkflowStatus.CANCELLED, WorkflowStatus.FAILED}:
        return worker_target_status in {
            WorkflowStatus.CANCELLED,
            WorkflowStatus.FAILED,
            WorkflowStatus.PAUSED,
        }

    return True


def can_action_be_proposed_under_worker(worker_status: WorkerStatus) -> bool:
    """
    判断给定 Worker 状态下，是否允许提议新的 Action（进入 PROPOSED 状态）。

    REQ-RT-002 §10.3 约束1/7：
    - Worker 非 RUNNING 时不得提出需要执行的 Action
    - Worker 进入 CANCELLED 或 FAILED 后不得产生新的业务 Action

    Args:
        worker_status: Worker 当前状态

    Returns:
        True 表示允许提议新 Action，False 表示不允许
    """
    # 只有 RUNNING 状态的 Worker 可以提议新的业务 Action
    return worker_status == WorkerStatus.RUNNING


def can_action_execute_under_worker(
    worker_status: WorkerStatus, action_target_status: ActionStatus
) -> bool:
    """
    判断给定 Worker 状态下，其子 Action 是否允许进入执行相关状态。

    REQ-RT-002 §10.3 约束6：Worker 进入 WAITING_APPROVAL 时，依赖审批的 Action
    必须处于 WAITING_APPROVAL 或尚未提交状态。

    Args:
        worker_status: Worker 当前状态
        action_target_status: Action 目标状态

    Returns:
        True 表示允许 Action 进入目标状态，False 表示不允许
    """
    # Worker 等待审批时，Action 不能进入 EXECUTING（但可以保持 WAITING_APPROVAL）
    if worker_status == WorkerStatus.WAITING_APPROVAL:
        return action_target_status in {
            ActionStatus.PROPOSED,
            ActionStatus.WAITING_APPROVAL,
            ActionStatus.REJECTED,
            ActionStatus.CANCELLED,
        }

    # Worker 暂停、取消或失败时，Action 不能进入执行状态
    if worker_status in {WorkerStatus.PAUSED, WorkerStatus.CANCELLED, WorkerStatus.FAILED}:
        return action_target_status not in {
            ActionStatus.EXECUTING,
            ActionStatus.AUTHORIZED,
        }

    return True


def validate_parent_child_consistency(
    parent_type: str,
    parent_status: TaskStatus | WorkflowStatus | WorkerStatus,
    child_type: str,
    child_target_status: TaskStatus | WorkflowStatus | WorkerStatus | ActionStatus,
) -> tuple[bool, str]:
    """
    校验父子实体状态一致性约束。

    Args:
        parent_type: 父实体类型，取值 "task" | "workflow" | "worker"
        parent_status: 父实体当前状态
        child_type: 子实体类型，取值 "workflow" | "worker" | "action"
        child_target_status: 子实体目标状态

    Returns:
        (是否允许, 错误原因)，允许时返回 (True, "")，不允许时返回 (False, 原因)

    示例：
        >>> validate_parent_child_consistency(
        ...     "task", TaskStatus.CANCELLED,
        ...     "workflow", WorkflowStatus.RUNNING
        ... )
        (False, "Task 处于 CANCELLED 状态时，Workflow 不允许进入 RUNNING")
    """
    if parent_type == "task" and child_type == "workflow":
        if not isinstance(parent_status, TaskStatus):
            return False, f"父实体类型 {parent_type} 的状态类型不匹配"
        if not isinstance(child_target_status, WorkflowStatus):
            return False, f"子实体类型 {child_type} 的状态类型不匹配"

        # 检查 Workflow 是否允许进入 RUNNING
        if child_target_status == WorkflowStatus.RUNNING:
            if not can_workflow_run_under_task(parent_status):
                return (
                    False,
                    f"Task 处于 {parent_status.value} 状态时，"
                    "Workflow 不允许进入 RUNNING（需 Task 处于执行阶段）",
                )

        # 检查 Workflow 是否允许继续推进
        if not can_workflow_continue_under_task(parent_status, child_target_status):
            return (
                False,
                f"Task 处于 {parent_status.value} 状态时，"
                f"Workflow 不允许进入 {child_target_status.value}",
            )

    elif parent_type == "workflow" and child_type == "worker":
        if not isinstance(parent_status, WorkflowStatus):
            return False, f"父实体类型 {parent_type} 的状态类型不匹配"
        if not isinstance(child_target_status, WorkerStatus):
            return False, f"子实体类型 {child_type} 的状态类型不匹配"

        # 检查 Worker 是否允许进入 RUNNING
        if child_target_status == WorkerStatus.RUNNING:
            if not can_worker_run_under_workflow(parent_status):
                return (
                    False,
                    f"Workflow 处于 {parent_status.value} 状态时，"
                    "Worker 不允许进入 RUNNING（需 Workflow 处于 READY 或 RUNNING）",
                )

        # 检查 Worker 是否允许继续推进
        if not can_worker_continue_under_workflow(parent_status, child_target_status):
            return (
                False,
                f"Workflow 处于 {parent_status.value} 状态时，"
                f"Worker 不允许进入 {child_target_status.value}",
            )

    elif parent_type == "worker" and child_type == "action":
        if not isinstance(parent_status, WorkerStatus):
            return False, f"父实体类型 {parent_type} 的状态类型不匹配"
        if not isinstance(child_target_status, ActionStatus):
            return False, f"子实体类型 {child_type} 的状态类型不匹配"

        # 检查是否允许提议新 Action
        if child_target_status == ActionStatus.PROPOSED:
            if not can_action_be_proposed_under_worker(parent_status):
                return (
                    False,
                    f"Worker 处于 {parent_status.value} 状态时，"
                    "不允许提议新的业务 Action（需 Worker 处于 RUNNING）",
                )

        # 检查 Action 是否允许执行
        if not can_action_execute_under_worker(parent_status, child_target_status):
            return (
                False,
                f"Worker 处于 {parent_status.value} 状态时，"
                f"Action 不允许进入 {child_target_status.value}",
            )

    else:
        return False, f"不支持的父子实体类型组合: {parent_type} -> {child_type}"

    return True, ""
