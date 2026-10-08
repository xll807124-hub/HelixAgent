"""
父子状态一致性校验单元测试（REQ-RT-002 §10）。

测试策略：
- 冒烟：每种父子关系的典型允许场景
- 边界：Task 取消/暂停时对 Workflow 的约束、Workflow 审批等待时对 Worker 的约束
- 异常：违反父子约束的场景（Task CANCELLED 时 Workflow 想进 RUNNING）
"""
from __future__ import annotations

from src.runtime.entities import (
    ActionStatus,
    TaskStatus,
    WorkerStatus,
    WorkflowStatus,
)
from src.runtime.state_machine.validators import (
    can_action_be_proposed_under_worker,
    can_action_execute_under_worker,
    can_worker_continue_under_workflow,
    can_worker_run_under_workflow,
    can_workflow_continue_under_task,
    can_workflow_run_under_task,
    validate_parent_child_consistency,
)

# ==============================================================================
# Task - Workflow 父子约束测试
# ==============================================================================

class TestTaskWorkflowConstraints:
    """Task 与 Workflow 父子状态约束测试"""

    # --------------------------------------------------------------------------
    # 冒烟测试：允许的场景
    # --------------------------------------------------------------------------

    def test_workflow_can_run_when_task_executing(self):
        """Task EXECUTING 时允许 Workflow RUNNING"""
        assert can_workflow_run_under_task(TaskStatus.EXECUTING)

    def test_workflow_can_run_when_task_preparing(self):
        """Task PREPARING_WORKSPACE 时允许 Workflow RUNNING"""
        assert can_workflow_run_under_task(TaskStatus.PREPARING_WORKSPACE)

    def test_workflow_can_run_when_task_validating(self):
        """Task VALIDATING 时允许 Workflow RUNNING"""
        assert can_workflow_run_under_task(TaskStatus.VALIDATING)

    # --------------------------------------------------------------------------
    # 边界测试：Task 不同阶段对 Workflow 的约束
    # --------------------------------------------------------------------------

    def test_workflow_cannot_run_when_task_created(self):
        """Task CREATED 时不允许 Workflow RUNNING（未进入执行阶段）"""
        assert not can_workflow_run_under_task(TaskStatus.CREATED)

    def test_workflow_cannot_run_when_task_authorizing(self):
        """Task AUTHORIZING 时不允许 Workflow RUNNING"""
        assert not can_workflow_run_under_task(TaskStatus.AUTHORIZING)

    def test_workflow_cannot_run_when_task_planning(self):
        """Task PLANNING 时不允许 Workflow RUNNING"""
        assert not can_workflow_run_under_task(TaskStatus.PLANNING)

    # --------------------------------------------------------------------------
    # 边界测试：Task 取消时的约束
    # --------------------------------------------------------------------------

    def test_workflow_can_only_cancel_when_task_cancelled(self):
        """Task CANCELLED 时 Workflow 只能进入 CANCELLED/FAILED/PAUSED"""
        assert can_workflow_continue_under_task(
            TaskStatus.CANCELLED, WorkflowStatus.CANCELLED
        )
        assert can_workflow_continue_under_task(
            TaskStatus.CANCELLED, WorkflowStatus.FAILED
        )
        assert can_workflow_continue_under_task(
            TaskStatus.CANCELLED, WorkflowStatus.PAUSED
        )

    def test_workflow_cannot_run_when_task_cancelled(self):
        """Task CANCELLED 时 Workflow 不允许进入 RUNNING"""
        assert not can_workflow_continue_under_task(
            TaskStatus.CANCELLED, WorkflowStatus.RUNNING
        )

    def test_workflow_cannot_wait_approval_when_task_cancelled(self):
        """Task CANCELLED 时 Workflow 不允许进入 WAITING_APPROVAL"""
        assert not can_workflow_continue_under_task(
            TaskStatus.CANCELLED, WorkflowStatus.WAITING_APPROVAL
        )

    # --------------------------------------------------------------------------
    # 边界测试：Task 暂停时的约束
    # --------------------------------------------------------------------------

    def test_workflow_cannot_run_when_task_paused(self):
        """Task PAUSED 时 Workflow 不允许进入 RUNNING"""
        assert not can_workflow_continue_under_task(
            TaskStatus.PAUSED, WorkflowStatus.RUNNING
        )

    def test_workflow_can_stay_ready_when_task_paused(self):
        """Task PAUSED 时 Workflow 允许保持 READY"""
        assert can_workflow_continue_under_task(
            TaskStatus.PAUSED, WorkflowStatus.READY
        )


# ==============================================================================
# Workflow - Worker 父子约束测试
# ==============================================================================

class TestWorkflowWorkerConstraints:
    """Workflow 与 Worker 父子状态约束测试"""

    # --------------------------------------------------------------------------
    # 冒烟测试：允许的场景
    # --------------------------------------------------------------------------

    def test_worker_can_run_when_workflow_ready(self):
        """Workflow READY 时允许 Worker RUNNING"""
        assert can_worker_run_under_workflow(WorkflowStatus.READY)

    def test_worker_can_run_when_workflow_running(self):
        """Workflow RUNNING 时允许 Worker RUNNING"""
        assert can_worker_run_under_workflow(WorkflowStatus.RUNNING)

    # --------------------------------------------------------------------------
    # 边界测试：Workflow 不同状态对 Worker 的约束
    # --------------------------------------------------------------------------

    def test_worker_cannot_run_when_workflow_created(self):
        """Workflow CREATED 时不允许 Worker RUNNING"""
        assert not can_worker_run_under_workflow(WorkflowStatus.CREATED)

    def test_worker_cannot_run_when_workflow_waiting_approval(self):
        """Workflow WAITING_APPROVAL 时不允许 Worker RUNNING"""
        assert not can_worker_run_under_workflow(WorkflowStatus.WAITING_APPROVAL)

    # --------------------------------------------------------------------------
    # 边界测试：Workflow 审批等待时的约束
    # --------------------------------------------------------------------------

    def test_worker_can_wait_approval_when_workflow_waiting(self):
        """Workflow WAITING_APPROVAL 时 Worker 允许进入 WAITING_APPROVAL"""
        assert can_worker_continue_under_workflow(
            WorkflowStatus.WAITING_APPROVAL, WorkerStatus.WAITING_APPROVAL
        )

    def test_worker_can_stay_ready_when_workflow_waiting(self):
        """Workflow WAITING_APPROVAL 时 Worker 允许保持 READY"""
        assert can_worker_continue_under_workflow(
            WorkflowStatus.WAITING_APPROVAL, WorkerStatus.READY
        )

    def test_worker_cannot_continue_to_running_when_workflow_waiting_approval(self):
        """Workflow WAITING_APPROVAL 时 Worker 不允许进入 RUNNING"""
        assert not can_worker_continue_under_workflow(
            WorkflowStatus.WAITING_APPROVAL, WorkerStatus.RUNNING
        )

    # --------------------------------------------------------------------------
    # 边界测试：Workflow 取消/失败时的约束
    # --------------------------------------------------------------------------

    def test_worker_can_only_stop_when_workflow_cancelled(self):
        """Workflow CANCELLED 时 Worker 只能进入非业务执行状态"""
        assert can_worker_continue_under_workflow(
            WorkflowStatus.CANCELLED, WorkerStatus.CANCELLED
        )
        assert can_worker_continue_under_workflow(
            WorkflowStatus.CANCELLED, WorkerStatus.FAILED
        )
        assert can_worker_continue_under_workflow(
            WorkflowStatus.CANCELLED, WorkerStatus.PAUSED
        )

    def test_worker_cannot_run_when_workflow_cancelled(self):
        """Workflow CANCELLED 时 Worker 不允许进入 RUNNING"""
        assert not can_worker_continue_under_workflow(
            WorkflowStatus.CANCELLED, WorkerStatus.RUNNING
        )


# ==============================================================================
# Worker - Action 父子约束测试
# ==============================================================================

class TestWorkerActionConstraints:
    """Worker 与 Action 父子状态约束测试"""

    # --------------------------------------------------------------------------
    # 冒烟测试：允许的场景
    # --------------------------------------------------------------------------

    def test_action_can_be_proposed_when_worker_running(self):
        """Worker RUNNING 时允许提议新 Action"""
        assert can_action_be_proposed_under_worker(WorkerStatus.RUNNING)

    def test_action_can_execute_when_worker_running(self):
        """Worker RUNNING 时 Action 允许进入 EXECUTING"""
        assert can_action_execute_under_worker(
            WorkerStatus.RUNNING, ActionStatus.EXECUTING
        )

    # --------------------------------------------------------------------------
    # 边界测试：Worker 非 RUNNING 时不能提议新 Action
    # --------------------------------------------------------------------------

    def test_action_cannot_be_proposed_when_worker_created(self):
        """Worker CREATED 时不允许提议新 Action"""
        assert not can_action_be_proposed_under_worker(WorkerStatus.CREATED)

    def test_action_cannot_be_proposed_when_worker_ready(self):
        """Worker READY 时不允许提议新 Action"""
        assert not can_action_be_proposed_under_worker(WorkerStatus.READY)

    def test_action_cannot_be_proposed_when_worker_paused(self):
        """Worker PAUSED 时不允许提议新 Action"""
        assert not can_action_be_proposed_under_worker(WorkerStatus.PAUSED)

    def test_action_cannot_be_proposed_when_worker_cancelled(self):
        """Worker CANCELLED 时不允许提议新 Action"""
        assert not can_action_be_proposed_under_worker(WorkerStatus.CANCELLED)

    def test_action_cannot_be_proposed_when_worker_failed(self):
        """Worker FAILED 时不允许提议新 Action"""
        assert not can_action_be_proposed_under_worker(WorkerStatus.FAILED)

    # --------------------------------------------------------------------------
    # 边界测试：Worker 审批等待时的约束
    # --------------------------------------------------------------------------

    def test_action_can_wait_approval_when_worker_waiting(self):
        """Worker WAITING_APPROVAL 时 Action 允许进入 WAITING_APPROVAL"""
        assert can_action_execute_under_worker(
            WorkerStatus.WAITING_APPROVAL, ActionStatus.WAITING_APPROVAL
        )

    def test_action_can_be_rejected_when_worker_waiting(self):
        """Worker WAITING_APPROVAL 时 Action 允许进入 REJECTED"""
        assert can_action_execute_under_worker(
            WorkerStatus.WAITING_APPROVAL, ActionStatus.REJECTED
        )

    def test_action_cannot_execute_when_worker_waiting_approval(self):
        """Worker WAITING_APPROVAL 时 Action 不允许进入 EXECUTING"""
        assert not can_action_execute_under_worker(
            WorkerStatus.WAITING_APPROVAL, ActionStatus.EXECUTING
        )

    # --------------------------------------------------------------------------
    # 边界测试：Worker 暂停/取消/失败时的约束
    # --------------------------------------------------------------------------

    def test_action_cannot_execute_when_worker_paused(self):
        """Worker PAUSED 时 Action 不允许进入 EXECUTING"""
        assert not can_action_execute_under_worker(
            WorkerStatus.PAUSED, ActionStatus.EXECUTING
        )

    def test_action_cannot_be_authorized_when_worker_cancelled(self):
        """Worker CANCELLED 时 Action 不允许进入 AUTHORIZED"""
        assert not can_action_execute_under_worker(
            WorkerStatus.CANCELLED, ActionStatus.AUTHORIZED
        )

    def test_action_can_be_cancelled_when_worker_failed(self):
        """Worker FAILED 时 Action 允许进入 CANCELLED"""
        assert can_action_execute_under_worker(
            WorkerStatus.FAILED, ActionStatus.CANCELLED
        )


# ==============================================================================
# 综合父子一致性校验测试
# ==============================================================================

class TestParentChildConsistencyValidation:
    """综合父子状态一致性校验测试"""

    # --------------------------------------------------------------------------
    # 冒烟测试：Task-Workflow 典型场景
    # --------------------------------------------------------------------------

    def test_validate_workflow_can_run_under_executing_task(self):
        """Task EXECUTING 时允许 Workflow RUNNING"""
        allowed, reason = validate_parent_child_consistency(
            "task", TaskStatus.EXECUTING,
            "workflow", WorkflowStatus.RUNNING
        )
        assert allowed
        assert reason == ""

    def test_validate_workflow_cannot_run_under_cancelled_task(self):
        """Task CANCELLED 时不允许 Workflow RUNNING"""
        allowed, reason = validate_parent_child_consistency(
            "task", TaskStatus.CANCELLED,
            "workflow", WorkflowStatus.RUNNING
        )
        assert not allowed
        assert "CANCELLED" in reason
        assert "RUNNING" in reason

    # --------------------------------------------------------------------------
    # 冒烟测试：Workflow-Worker 典型场景
    # --------------------------------------------------------------------------

    def test_validate_worker_can_run_under_running_workflow(self):
        """Workflow RUNNING 时允许 Worker RUNNING"""
        allowed, reason = validate_parent_child_consistency(
            "workflow", WorkflowStatus.RUNNING,
            "worker", WorkerStatus.RUNNING
        )
        assert allowed
        assert reason == ""

    def test_validate_worker_cannot_run_under_waiting_workflow(self):
        """Workflow WAITING_APPROVAL 时不允许 Worker RUNNING"""
        allowed, reason = validate_parent_child_consistency(
            "workflow", WorkflowStatus.WAITING_APPROVAL,
            "worker", WorkerStatus.RUNNING
        )
        assert not allowed
        assert "WAITING_APPROVAL" in reason
        assert "RUNNING" in reason

    # --------------------------------------------------------------------------
    # 冒烟测试：Worker-Action 典型场景
    # --------------------------------------------------------------------------

    def test_validate_action_can_be_proposed_under_running_worker(self):
        """Worker RUNNING 时允许 Action PROPOSED"""
        allowed, reason = validate_parent_child_consistency(
            "worker", WorkerStatus.RUNNING,
            "action", ActionStatus.PROPOSED
        )
        assert allowed
        assert reason == ""

    def test_validate_action_cannot_be_proposed_under_paused_worker(self):
        """Worker PAUSED 时不允许 Action PROPOSED"""
        allowed, reason = validate_parent_child_consistency(
            "worker", WorkerStatus.PAUSED,
            "action", ActionStatus.PROPOSED
        )
        assert not allowed
        assert "PAUSED" in reason
        assert "Action" in reason

    # --------------------------------------------------------------------------
    # 边界测试：类型不匹配
    # --------------------------------------------------------------------------

    def test_validate_type_mismatch_parent_status(self):
        """父实体状态类型不匹配"""
        # 传入 WorkflowStatus 给 task 类型
        allowed, reason = validate_parent_child_consistency(
            "task", WorkflowStatus.RUNNING,  # type: ignore
            "workflow", WorkflowStatus.RUNNING
        )
        assert not allowed
        assert "类型不匹配" in reason

    def test_validate_type_mismatch_child_status(self):
        """子实体状态类型不匹配"""
        # 传入 TaskStatus 给 workflow 类型
        allowed, reason = validate_parent_child_consistency(
            "task", TaskStatus.EXECUTING,
            "workflow", TaskStatus.EXECUTING  # type: ignore
        )
        assert not allowed
        assert "类型不匹配" in reason

    def test_validate_unsupported_parent_child_combination(self):
        """不支持的父子实体类型组合"""
        allowed, reason = validate_parent_child_consistency(
            "task", TaskStatus.EXECUTING,
            "action", ActionStatus.PROPOSED  # Task 不直接包含 Action
        )
        assert not allowed
        assert "不支持" in reason

    # --------------------------------------------------------------------------
    # 边界测试：多层级约束传递
    # --------------------------------------------------------------------------

    def test_validate_task_paused_blocks_workflow_running(self):
        """Task PAUSED 阻止 Workflow RUNNING"""
        allowed, reason = validate_parent_child_consistency(
            "task", TaskStatus.PAUSED,
            "workflow", WorkflowStatus.RUNNING
        )
        assert not allowed
        assert "PAUSED" in reason

    def test_validate_workflow_cancelled_blocks_worker_running(self):
        """Workflow CANCELLED 阻止 Worker RUNNING"""
        allowed, reason = validate_parent_child_consistency(
            "workflow", WorkflowStatus.CANCELLED,
            "worker", WorkerStatus.RUNNING
        )
        assert not allowed
        assert "CANCELLED" in reason

    def test_validate_worker_failed_blocks_action_executing(self):
        """Worker FAILED 阻止 Action EXECUTING"""
        allowed, reason = validate_parent_child_consistency(
            "worker", WorkerStatus.FAILED,
            "action", ActionStatus.EXECUTING
        )
        assert not allowed
        assert "FAILED" in reason

    # --------------------------------------------------------------------------
    # 边界测试：允许的恢复路径
    # --------------------------------------------------------------------------

    def test_validate_task_paused_allows_workflow_paused(self):
        """Task PAUSED 允许 Workflow 保持 PAUSED"""
        allowed, reason = validate_parent_child_consistency(
            "task", TaskStatus.PAUSED,
            "workflow", WorkflowStatus.PAUSED
        )
        assert allowed
        assert reason == ""

    def test_validate_workflow_waiting_allows_worker_ready(self):
        """Workflow WAITING_APPROVAL 允许 Worker 保持 READY"""
        allowed, reason = validate_parent_child_consistency(
            "workflow", WorkflowStatus.WAITING_APPROVAL,
            "worker", WorkerStatus.READY
        )
        assert allowed
        assert reason == ""

    # --------------------------------------------------------------------------
    # 边界测试：完整覆盖所有类型不匹配分支
    # --------------------------------------------------------------------------

    def test_validate_workflow_worker_parent_type_mismatch(self):
        """Workflow-Worker：父实体类型不匹配（传入非 WorkflowStatus）"""
        allowed, reason = validate_parent_child_consistency(
            "workflow", TaskStatus.EXECUTING,  # type: ignore
            "worker", WorkerStatus.RUNNING
        )
        assert not allowed
        assert "类型不匹配" in reason

    def test_validate_workflow_worker_child_type_mismatch(self):
        """Workflow-Worker：子实体类型不匹配（传入非 WorkerStatus）"""
        allowed, reason = validate_parent_child_consistency(
            "workflow", WorkflowStatus.RUNNING,
            "worker", TaskStatus.EXECUTING  # type: ignore
        )
        assert not allowed
        assert "类型不匹配" in reason

    def test_validate_worker_action_parent_type_mismatch(self):
        """Worker-Action：父实体类型不匹配（传入非 WorkerStatus）"""
        allowed, reason = validate_parent_child_consistency(
            "worker", TaskStatus.EXECUTING,  # type: ignore
            "action", ActionStatus.PROPOSED
        )
        assert not allowed
        assert "类型不匹配" in reason

    def test_validate_worker_action_child_type_mismatch(self):
        """Worker-Action：子实体类型不匹配（传入非 ActionStatus）"""
        allowed, reason = validate_parent_child_consistency(
            "worker", WorkerStatus.RUNNING,
            "action", TaskStatus.EXECUTING  # type: ignore
        )
        assert not allowed
        assert "类型不匹配" in reason

    # --------------------------------------------------------------------------
    # 边界测试：覆盖 can_workflow_continue_under_task 的所有路径
    # --------------------------------------------------------------------------

    def test_validate_task_created_workflow_running_blocked(self):
        """Task CREATED 阻止 Workflow RUNNING（通过 can_workflow_run_under_task）"""
        allowed, reason = validate_parent_child_consistency(
            "task", TaskStatus.CREATED,
            "workflow", WorkflowStatus.RUNNING
        )
        assert not allowed
        assert "CREATED" in reason
        assert "RUNNING" in reason

    def test_validate_task_cancelled_workflow_completed_blocked(self):
        """Task CANCELLED 阻止 Workflow COMPLETED（通过 can_workflow_continue_under_task 的失败路径）"""
        allowed, reason = validate_parent_child_consistency(
            "task", TaskStatus.CANCELLED,
            "workflow", WorkflowStatus.COMPLETED
        )
        assert not allowed
        assert "CANCELLED" in reason
        assert "COMPLETED" in reason

    # --------------------------------------------------------------------------
    # 边界测试：覆盖 can_worker_continue_under_workflow 的所有路径
    # --------------------------------------------------------------------------

    def test_validate_workflow_created_worker_running_blocked(self):
        """Workflow CREATED 阻止 Worker RUNNING（通过 can_worker_run_under_workflow）"""
        allowed, reason = validate_parent_child_consistency(
            "workflow", WorkflowStatus.CREATED,
            "worker", WorkerStatus.RUNNING
        )
        assert not allowed
        assert "CREATED" in reason
        assert "RUNNING" in reason

    def test_validate_workflow_failed_worker_completed_blocked(self):
        """Workflow FAILED 阻止 Worker COMPLETED（通过 can_worker_continue_under_workflow 的失败路径）"""
        allowed, reason = validate_parent_child_consistency(
            "workflow", WorkflowStatus.FAILED,
            "worker", WorkerStatus.COMPLETED
        )
        assert not allowed
        assert "FAILED" in reason
        assert "COMPLETED" in reason
