"""
状态迁移规则单元测试（REQ-RT-002 §5-8）。

测试策略：
- 冒烟：每个状态机的典型正常迁移路径
- 边界：终态不允许迁移、暂停可恢复、审批等待路径、幂等迁移
- 异常：非法迁移（跳跃、逆向、从终态出发）
"""
from __future__ import annotations

from src.runtime.entities import (
    ActionStatus,
    TaskStatus,
    WorkerStatus,
    WorkflowStatus,
)
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

# ==============================================================================
# Task 状态机测试
# ==============================================================================

class TestTaskTransitions:
    """Task 状态机迁移规则测试"""

    # --------------------------------------------------------------------------
    # 冒烟测试：典型正常路径
    # --------------------------------------------------------------------------

    def test_task_normal_flow_created_to_authorizing(self):
        """Task 正常流程：CREATED -> AUTHORIZING"""
        assert can_transition_task(TaskStatus.CREATED, TaskStatus.AUTHORIZING)

    def test_task_normal_flow_authorizing_to_planning(self):
        """Task 正常流程：AUTHORIZING -> PLANNING"""
        assert can_transition_task(TaskStatus.AUTHORIZING, TaskStatus.PLANNING)

    def test_task_normal_flow_planning_to_preparing(self):
        """Task 正常流程：PLANNING -> PREPARING_WORKSPACE（无需审批）"""
        assert can_transition_task(
            TaskStatus.PLANNING, TaskStatus.PREPARING_WORKSPACE
        )

    def test_task_normal_flow_preparing_to_executing(self):
        """Task 正常流程：PREPARING_WORKSPACE -> EXECUTING"""
        assert can_transition_task(
            TaskStatus.PREPARING_WORKSPACE, TaskStatus.EXECUTING
        )

    def test_task_normal_flow_executing_to_validating(self):
        """Task 正常流程：EXECUTING -> VALIDATING"""
        assert can_transition_task(TaskStatus.EXECUTING, TaskStatus.VALIDATING)

    def test_task_normal_flow_validating_to_creating_pr(self):
        """Task 正常流程：VALIDATING -> CREATING_PR"""
        assert can_transition_task(TaskStatus.VALIDATING, TaskStatus.CREATING_PR)

    def test_task_normal_flow_creating_pr_to_waiting_review(self):
        """Task 正常流程：CREATING_PR -> WAITING_REVIEW"""
        assert can_transition_task(TaskStatus.CREATING_PR, TaskStatus.WAITING_REVIEW)

    def test_task_normal_flow_waiting_review_to_completed(self):
        """Task 正常流程：WAITING_REVIEW -> COMPLETED"""
        assert can_transition_task(TaskStatus.WAITING_REVIEW, TaskStatus.COMPLETED)

    # --------------------------------------------------------------------------
    # 边界测试：审批路径
    # --------------------------------------------------------------------------

    def test_task_approval_path_planning_to_waiting_approval(self):
        """Task 审批路径：PLANNING -> WAITING_APPROVAL（需人工审批）"""
        assert can_transition_task(TaskStatus.PLANNING, TaskStatus.WAITING_APPROVAL)

    def test_task_approval_path_waiting_to_preparing(self):
        """Task 审批路径：WAITING_APPROVAL -> PREPARING_WORKSPACE（审批通过）"""
        assert can_transition_task(
            TaskStatus.WAITING_APPROVAL, TaskStatus.PREPARING_WORKSPACE
        )

    def test_task_approval_path_waiting_to_executing(self):
        """Task 审批路径：WAITING_APPROVAL -> EXECUTING（执行阶段审批通过）"""
        assert can_transition_task(TaskStatus.WAITING_APPROVAL, TaskStatus.EXECUTING)

    # --------------------------------------------------------------------------
    # 边界测试：验证失败可回到修复流程
    # --------------------------------------------------------------------------

    def test_task_validation_retry_validating_to_executing(self):
        """Task 验证重试：VALIDATING -> EXECUTING（验证失败进入修复）"""
        assert can_transition_task(TaskStatus.VALIDATING, TaskStatus.EXECUTING)

    # --------------------------------------------------------------------------
    # 边界测试：暂停与恢复
    # --------------------------------------------------------------------------

    def test_task_pause_from_executing(self):
        """Task 暂停：EXECUTING -> PAUSED"""
        assert can_transition_task(TaskStatus.EXECUTING, TaskStatus.PAUSED)

    def test_task_pause_from_planning(self):
        """Task 暂停：PLANNING -> PAUSED"""
        assert can_transition_task(TaskStatus.PLANNING, TaskStatus.PAUSED)

    def test_task_resume_paused_to_executing(self):
        """Task 恢复：PAUSED -> EXECUTING"""
        assert can_transition_task(TaskStatus.PAUSED, TaskStatus.EXECUTING)

    def test_task_resume_paused_to_validating(self):
        """Task 恢复：PAUSED -> VALIDATING"""
        assert can_transition_task(TaskStatus.PAUSED, TaskStatus.VALIDATING)

    # --------------------------------------------------------------------------
    # 边界测试：取消与失败
    # --------------------------------------------------------------------------

    def test_task_cancel_from_executing(self):
        """Task 取消：EXECUTING -> CANCELLED"""
        assert can_transition_task(TaskStatus.EXECUTING, TaskStatus.CANCELLED)

    def test_task_cancel_from_paused(self):
        """Task 取消：PAUSED -> CANCELLED（暂停后可取消）"""
        assert can_transition_task(TaskStatus.PAUSED, TaskStatus.CANCELLED)

    def test_task_fail_from_validating(self):
        """Task 失败：VALIDATING -> FAILED"""
        assert can_transition_task(TaskStatus.VALIDATING, TaskStatus.FAILED)

    # --------------------------------------------------------------------------
    # 异常测试：非法迁移
    # --------------------------------------------------------------------------

    def test_task_illegal_created_to_executing(self):
        """Task 非法迁移：CREATED -> EXECUTING（跳过中间阶段）"""
        assert not can_transition_task(TaskStatus.CREATED, TaskStatus.EXECUTING)

    def test_task_illegal_executing_to_planning(self):
        """Task 非法迁移：EXECUTING -> PLANNING（不允许倒退到规划）"""
        assert not can_transition_task(TaskStatus.EXECUTING, TaskStatus.PLANNING)

    def test_task_illegal_completed_to_executing(self):
        """Task 非法迁移：COMPLETED -> EXECUTING（终态不可恢复）"""
        assert not can_transition_task(TaskStatus.COMPLETED, TaskStatus.EXECUTING)

    def test_task_illegal_cancelled_to_planning(self):
        """Task 非法迁移：CANCELLED -> PLANNING（取消后不可重新规划）"""
        assert not can_transition_task(TaskStatus.CANCELLED, TaskStatus.PLANNING)

    def test_task_illegal_failed_to_validating(self):
        """Task 非法迁移：FAILED -> VALIDATING（失败后不可直接恢复）"""
        assert not can_transition_task(TaskStatus.FAILED, TaskStatus.VALIDATING)

    def test_task_illegal_completed_to_any_state(self):
        """Task 非法迁移：COMPLETED 不允许迁移到任何状态"""
        for status in TaskStatus:
            if status != TaskStatus.COMPLETED:
                assert not can_transition_task(TaskStatus.COMPLETED, status)


# ==============================================================================
# Workflow 状态机测试
# ==============================================================================

class TestWorkflowTransitions:
    """Workflow 状态机迁移规则测试"""

    # --------------------------------------------------------------------------
    # 冒烟测试：典型正常路径
    # --------------------------------------------------------------------------

    def test_workflow_normal_flow_created_to_ready(self):
        """Workflow 正常流程：CREATED -> READY"""
        assert can_transition_workflow(WorkflowStatus.CREATED, WorkflowStatus.READY)

    def test_workflow_normal_flow_ready_to_running(self):
        """Workflow 正常流程：READY -> RUNNING"""
        assert can_transition_workflow(WorkflowStatus.READY, WorkflowStatus.RUNNING)

    def test_workflow_normal_flow_running_to_completed(self):
        """Workflow 正常流程：RUNNING -> COMPLETED"""
        assert can_transition_workflow(
            WorkflowStatus.RUNNING, WorkflowStatus.COMPLETED
        )

    # --------------------------------------------------------------------------
    # 边界测试：审批路径
    # --------------------------------------------------------------------------

    def test_workflow_approval_path_running_to_waiting(self):
        """Workflow 审批路径：RUNNING -> WAITING_APPROVAL"""
        assert can_transition_workflow(
            WorkflowStatus.RUNNING, WorkflowStatus.WAITING_APPROVAL
        )

    def test_workflow_approval_path_waiting_to_running(self):
        """Workflow 审批路径：WAITING_APPROVAL -> RUNNING（审批通过）"""
        assert can_transition_workflow(
            WorkflowStatus.WAITING_APPROVAL, WorkflowStatus.RUNNING
        )

    # --------------------------------------------------------------------------
    # 边界测试：暂停与恢复
    # --------------------------------------------------------------------------

    def test_workflow_pause_from_running(self):
        """Workflow 暂停：RUNNING -> PAUSED"""
        assert can_transition_workflow(WorkflowStatus.RUNNING, WorkflowStatus.PAUSED)

    def test_workflow_resume_paused_to_running(self):
        """Workflow 恢复：PAUSED -> RUNNING"""
        assert can_transition_workflow(WorkflowStatus.PAUSED, WorkflowStatus.RUNNING)

    def test_workflow_resume_paused_to_ready(self):
        """Workflow 恢复：PAUSED -> READY（恢复到调度准备）"""
        assert can_transition_workflow(WorkflowStatus.PAUSED, WorkflowStatus.READY)

    # --------------------------------------------------------------------------
    # 边界测试：取消与失败
    # --------------------------------------------------------------------------

    def test_workflow_cancel_from_running(self):
        """Workflow 取消：RUNNING -> CANCELLED"""
        assert can_transition_workflow(
            WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED
        )

    def test_workflow_fail_from_waiting_approval(self):
        """Workflow 失败：WAITING_APPROVAL -> FAILED（审批拒绝）"""
        assert can_transition_workflow(
            WorkflowStatus.WAITING_APPROVAL, WorkflowStatus.FAILED
        )

    # --------------------------------------------------------------------------
    # 异常测试：非法迁移
    # --------------------------------------------------------------------------

    def test_workflow_illegal_created_to_running(self):
        """Workflow 非法迁移：CREATED -> RUNNING（必须先进入 READY）"""
        assert not can_transition_workflow(
            WorkflowStatus.CREATED, WorkflowStatus.RUNNING
        )

    def test_workflow_illegal_running_to_ready(self):
        """Workflow 非法迁移：RUNNING -> READY（不允许回退到准备状态）"""
        assert not can_transition_workflow(
            WorkflowStatus.RUNNING, WorkflowStatus.READY
        )

    def test_workflow_illegal_completed_to_running(self):
        """Workflow 非法迁移：COMPLETED -> RUNNING（终态不可恢复）"""
        assert not can_transition_workflow(
            WorkflowStatus.COMPLETED, WorkflowStatus.RUNNING
        )

    def test_workflow_illegal_cancelled_to_any_state(self):
        """Workflow 非法迁移：CANCELLED 不允许迁移到任何状态"""
        for status in WorkflowStatus:
            if status != WorkflowStatus.CANCELLED:
                assert not can_transition_workflow(WorkflowStatus.CANCELLED, status)


# ==============================================================================
# Worker 状态机测试
# ==============================================================================

class TestWorkerTransitions:
    """Worker 状态机迁移规则测试"""

    # --------------------------------------------------------------------------
    # 冒烟测试：典型正常路径
    # --------------------------------------------------------------------------

    def test_worker_normal_flow_created_to_ready(self):
        """Worker 正常流程：CREATED -> READY"""
        assert can_transition_worker(WorkerStatus.CREATED, WorkerStatus.READY)

    def test_worker_normal_flow_ready_to_running(self):
        """Worker 正常流程：READY -> RUNNING"""
        assert can_transition_worker(WorkerStatus.READY, WorkerStatus.RUNNING)

    def test_worker_normal_flow_running_to_completed(self):
        """Worker 正常流程：RUNNING -> COMPLETED"""
        assert can_transition_worker(WorkerStatus.RUNNING, WorkerStatus.COMPLETED)

    # --------------------------------------------------------------------------
    # 边界测试：审批路径
    # --------------------------------------------------------------------------

    def test_worker_approval_path_running_to_waiting(self):
        """Worker 审批路径：RUNNING -> WAITING_APPROVAL"""
        assert can_transition_worker(
            WorkerStatus.RUNNING, WorkerStatus.WAITING_APPROVAL
        )

    def test_worker_approval_path_waiting_to_running(self):
        """Worker 审批路径：WAITING_APPROVAL -> RUNNING（审批通过）"""
        assert can_transition_worker(
            WorkerStatus.WAITING_APPROVAL, WorkerStatus.RUNNING
        )

    # --------------------------------------------------------------------------
    # 边界测试：暂停与恢复
    # --------------------------------------------------------------------------

    def test_worker_pause_from_running(self):
        """Worker 暂停：RUNNING -> PAUSED"""
        assert can_transition_worker(WorkerStatus.RUNNING, WorkerStatus.PAUSED)

    def test_worker_resume_paused_to_running(self):
        """Worker 恢复：PAUSED -> RUNNING"""
        assert can_transition_worker(WorkerStatus.PAUSED, WorkerStatus.RUNNING)

    # --------------------------------------------------------------------------
    # 边界测试：取消与失败
    # --------------------------------------------------------------------------

    def test_worker_cancel_from_ready(self):
        """Worker 取消：READY -> CANCELLED"""
        assert can_transition_worker(WorkerStatus.READY, WorkerStatus.CANCELLED)

    def test_worker_fail_from_running(self):
        """Worker 失败：RUNNING -> FAILED"""
        assert can_transition_worker(WorkerStatus.RUNNING, WorkerStatus.FAILED)

    # --------------------------------------------------------------------------
    # 异常测试：非法迁移
    # --------------------------------------------------------------------------

    def test_worker_illegal_created_to_running(self):
        """Worker 非法迁移：CREATED -> RUNNING（必须先进入 READY）"""
        assert not can_transition_worker(WorkerStatus.CREATED, WorkerStatus.RUNNING)

    def test_worker_illegal_running_to_ready(self):
        """Worker 非法迁移：RUNNING -> READY（不允许回退）"""
        assert not can_transition_worker(WorkerStatus.RUNNING, WorkerStatus.READY)

    def test_worker_illegal_completed_to_running(self):
        """Worker 非法迁移：COMPLETED -> RUNNING（终态不可恢复）"""
        assert not can_transition_worker(WorkerStatus.COMPLETED, WorkerStatus.RUNNING)

    def test_worker_illegal_failed_to_any_state(self):
        """Worker 非法迁移：FAILED 不允许迁移到任何状态"""
        for status in WorkerStatus:
            if status != WorkerStatus.FAILED:
                assert not can_transition_worker(WorkerStatus.FAILED, status)


# ==============================================================================
# Action 状态机测试
# ==============================================================================

class TestActionTransitions:
    """Action 状态机迁移规则测试"""

    # --------------------------------------------------------------------------
    # 冒烟测试：典型正常路径
    # --------------------------------------------------------------------------

    def test_action_normal_flow_proposed_to_authorized(self):
        """Action 正常流程：PROPOSED -> AUTHORIZED"""
        assert can_transition_action(ActionStatus.PROPOSED, ActionStatus.AUTHORIZED)

    def test_action_normal_flow_authorized_to_executing(self):
        """Action 正常流程：AUTHORIZED -> EXECUTING"""
        assert can_transition_action(ActionStatus.AUTHORIZED, ActionStatus.EXECUTING)

    def test_action_normal_flow_executing_to_succeeded(self):
        """Action 正常流程：EXECUTING -> SUCCEEDED"""
        assert can_transition_action(ActionStatus.EXECUTING, ActionStatus.SUCCEEDED)

    # --------------------------------------------------------------------------
    # 边界测试：审批路径
    # --------------------------------------------------------------------------

    def test_action_approval_path_proposed_to_waiting(self):
        """Action 审批路径：PROPOSED -> WAITING_APPROVAL"""
        assert can_transition_action(
            ActionStatus.PROPOSED, ActionStatus.WAITING_APPROVAL
        )

    def test_action_approval_path_waiting_to_authorized(self):
        """Action 审批路径：WAITING_APPROVAL -> AUTHORIZED（审批通过）"""
        assert can_transition_action(
            ActionStatus.WAITING_APPROVAL, ActionStatus.AUTHORIZED
        )

    # --------------------------------------------------------------------------
    # 边界测试：拒绝路径
    # --------------------------------------------------------------------------

    def test_action_reject_proposed_to_rejected(self):
        """Action 拒绝路径：PROPOSED -> REJECTED"""
        assert can_transition_action(ActionStatus.PROPOSED, ActionStatus.REJECTED)

    def test_action_reject_waiting_to_rejected(self):
        """Action 拒绝路径：WAITING_APPROVAL -> REJECTED（审批拒绝）"""
        assert can_transition_action(
            ActionStatus.WAITING_APPROVAL, ActionStatus.REJECTED
        )

    # --------------------------------------------------------------------------
    # 边界测试：失败与取消
    # --------------------------------------------------------------------------

    def test_action_fail_executing_to_failed(self):
        """Action 失败：EXECUTING -> FAILED"""
        assert can_transition_action(ActionStatus.EXECUTING, ActionStatus.FAILED)

    def test_action_cancel_proposed(self):
        """Action 取消：PROPOSED -> CANCELLED"""
        assert can_transition_action(ActionStatus.PROPOSED, ActionStatus.CANCELLED)

    def test_action_cancel_authorized(self):
        """Action 取消：AUTHORIZED -> CANCELLED"""
        assert can_transition_action(ActionStatus.AUTHORIZED, ActionStatus.CANCELLED)

    # --------------------------------------------------------------------------
    # 异常测试：非法迁移
    # --------------------------------------------------------------------------

    def test_action_illegal_proposed_to_executing(self):
        """Action 非法迁移：PROPOSED -> EXECUTING（必须先授权）"""
        assert not can_transition_action(ActionStatus.PROPOSED, ActionStatus.EXECUTING)

    def test_action_illegal_authorized_to_succeeded(self):
        """Action 非法迁移：AUTHORIZED -> SUCCEEDED（必须先执行）"""
        assert not can_transition_action(
            ActionStatus.AUTHORIZED, ActionStatus.SUCCEEDED
        )

    def test_action_illegal_succeeded_to_executing(self):
        """Action 非法迁移：SUCCEEDED -> EXECUTING（终态不可重新执行）"""
        assert not can_transition_action(ActionStatus.SUCCEEDED, ActionStatus.EXECUTING)

    def test_action_illegal_rejected_to_authorized(self):
        """Action 非法迁移：REJECTED -> AUTHORIZED（拒绝后不可自动授权）"""
        assert not can_transition_action(ActionStatus.REJECTED, ActionStatus.AUTHORIZED)

    def test_action_illegal_failed_to_any_state(self):
        """Action 非法迁移：FAILED 不允许迁移到任何状态"""
        for status in ActionStatus:
            if status != ActionStatus.FAILED:
                assert not can_transition_action(ActionStatus.FAILED, status)


# ==============================================================================
# 幂等迁移测试（所有状态机通用）
# ==============================================================================

class TestIdempotentTransitions:
    """幂等迁移测试：相同状态的迁移应始终允许"""

    def test_task_idempotent_transitions(self):
        """Task 幂等迁移：任意状态到自身的迁移都应允许"""
        for status in TaskStatus:
            assert can_transition_task(status, status), \
                f"Task 幂等迁移失败：{status.value} -> {status.value}"

    def test_workflow_idempotent_transitions(self):
        """Workflow 幂等迁移：任意状态到自身的迁移都应允许"""
        for status in WorkflowStatus:
            assert can_transition_workflow(status, status), \
                f"Workflow 幂等迁移失败：{status.value} -> {status.value}"

    def test_worker_idempotent_transitions(self):
        """Worker 幂等迁移：任意状态到自身的迁移都应允许"""
        for status in WorkerStatus:
            assert can_transition_worker(status, status), \
                f"Worker 幂等迁移失败：{status.value} -> {status.value}"

    def test_action_idempotent_transitions(self):
        """Action 幂等迁移：任意状态到自身的迁移都应允许"""
        for status in ActionStatus:
            assert can_transition_action(status, status), \
                f"Action 幂等迁移失败：{status.value} -> {status.value}"

    def test_task_idempotent_transition_from_terminal_state(self):
        """Task 终态幂等迁移：COMPLETED -> COMPLETED 应允许"""
        assert can_transition_task(TaskStatus.COMPLETED, TaskStatus.COMPLETED)
        assert can_transition_task(TaskStatus.CANCELLED, TaskStatus.CANCELLED)
        assert can_transition_task(TaskStatus.FAILED, TaskStatus.FAILED)

    def test_workflow_idempotent_transition_from_terminal_state(self):
        """Workflow 终态幂等迁移：COMPLETED -> COMPLETED 应允许"""
        assert can_transition_workflow(WorkflowStatus.COMPLETED, WorkflowStatus.COMPLETED)
        assert can_transition_workflow(WorkflowStatus.CANCELLED, WorkflowStatus.CANCELLED)
        assert can_transition_workflow(WorkflowStatus.FAILED, WorkflowStatus.FAILED)

    def test_worker_idempotent_transition_from_terminal_state(self):
        """Worker 终态幂等迁移：COMPLETED -> COMPLETED 应允许"""
        assert can_transition_worker(WorkerStatus.COMPLETED, WorkerStatus.COMPLETED)
        assert can_transition_worker(WorkerStatus.CANCELLED, WorkerStatus.CANCELLED)
        assert can_transition_worker(WorkerStatus.FAILED, WorkerStatus.FAILED)

    def test_action_idempotent_transition_from_terminal_state(self):
        """Action 终态幂等迁移：SUCCEEDED -> SUCCEEDED 应允许"""
        assert can_transition_action(ActionStatus.SUCCEEDED, ActionStatus.SUCCEEDED)
        assert can_transition_action(ActionStatus.FAILED, ActionStatus.FAILED)
        assert can_transition_action(ActionStatus.REJECTED, ActionStatus.REJECTED)
        assert can_transition_action(ActionStatus.CANCELLED, ActionStatus.CANCELLED)


# ==============================================================================
# 终态判断测试
# ==============================================================================

class TestTerminalStateDetection:
    """终态判断测试：验证终态识别函数的正确性"""

    # --------------------------------------------------------------------------
    # Task 终态判断
    # --------------------------------------------------------------------------

    def test_task_terminal_states(self):
        """Task 终态：COMPLETED, CANCELLED, FAILED"""
        assert is_terminal_state_task(TaskStatus.COMPLETED)
        assert is_terminal_state_task(TaskStatus.CANCELLED)
        assert is_terminal_state_task(TaskStatus.FAILED)

    def test_task_non_terminal_states(self):
        """Task 非终态：其他所有状态"""
        non_terminal_states = [
            TaskStatus.CREATED,
            TaskStatus.AUTHORIZING,
            TaskStatus.PLANNING,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.PREPARING_WORKSPACE,
            TaskStatus.EXECUTING,
            TaskStatus.VALIDATING,
            TaskStatus.CREATING_PR,
            TaskStatus.WAITING_REVIEW,
            TaskStatus.PAUSED,
        ]
        for status in non_terminal_states:
            assert not is_terminal_state_task(status), \
                f"{status.value} 不应被识别为终态"

    # --------------------------------------------------------------------------
    # Workflow 终态判断
    # --------------------------------------------------------------------------

    def test_workflow_terminal_states(self):
        """Workflow 终态：COMPLETED, CANCELLED, FAILED"""
        assert is_terminal_state_workflow(WorkflowStatus.COMPLETED)
        assert is_terminal_state_workflow(WorkflowStatus.CANCELLED)
        assert is_terminal_state_workflow(WorkflowStatus.FAILED)

    def test_workflow_non_terminal_states(self):
        """Workflow 非终态：其他所有状态"""
        non_terminal_states = [
            WorkflowStatus.CREATED,
            WorkflowStatus.READY,
            WorkflowStatus.RUNNING,
            WorkflowStatus.WAITING_APPROVAL,
            WorkflowStatus.PAUSED,
        ]
        for status in non_terminal_states:
            assert not is_terminal_state_workflow(status), \
                f"{status.value} 不应被识别为终态"

    # --------------------------------------------------------------------------
    # Worker 终态判断
    # --------------------------------------------------------------------------

    def test_worker_terminal_states(self):
        """Worker 终态：COMPLETED, CANCELLED, FAILED"""
        assert is_terminal_state_worker(WorkerStatus.COMPLETED)
        assert is_terminal_state_worker(WorkerStatus.CANCELLED)
        assert is_terminal_state_worker(WorkerStatus.FAILED)

    def test_worker_non_terminal_states(self):
        """Worker 非终态：其他所有状态"""
        non_terminal_states = [
            WorkerStatus.CREATED,
            WorkerStatus.READY,
            WorkerStatus.RUNNING,
            WorkerStatus.WAITING_APPROVAL,
            WorkerStatus.PAUSED,
        ]
        for status in non_terminal_states:
            assert not is_terminal_state_worker(status), \
                f"{status.value} 不应被识别为终态"

    # --------------------------------------------------------------------------
    # Action 终态判断
    # --------------------------------------------------------------------------

    def test_action_terminal_states(self):
        """Action 终态：SUCCEEDED, FAILED, REJECTED, CANCELLED"""
        assert is_terminal_state_action(ActionStatus.SUCCEEDED)
        assert is_terminal_state_action(ActionStatus.FAILED)
        assert is_terminal_state_action(ActionStatus.REJECTED)
        assert is_terminal_state_action(ActionStatus.CANCELLED)

    def test_action_non_terminal_states(self):
        """Action 非终态：其他所有状态"""
        non_terminal_states = [
            ActionStatus.PROPOSED,
            ActionStatus.AUTHORIZED,
            ActionStatus.WAITING_APPROVAL,
            ActionStatus.EXECUTING,
        ]
        for status in non_terminal_states:
            assert not is_terminal_state_action(status), \
                f"{status.value} 不应被识别为终态"

    # --------------------------------------------------------------------------
    # 终态保护：终态不能迁移到其他非终态状态
    # --------------------------------------------------------------------------

    def test_task_terminal_state_blocks_transition_to_non_terminal(self):
        """Task 终态保护：终态不能迁移到非终态"""
        terminal_states = [TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED]
        non_terminal_states = [
            TaskStatus.CREATED,
            TaskStatus.AUTHORIZING,
            TaskStatus.EXECUTING,
            TaskStatus.VALIDATING,
        ]
        for terminal in terminal_states:
            for non_terminal in non_terminal_states:
                assert not can_transition_task(terminal, non_terminal), \
                    f"终态 {terminal.value} 不应允许迁移到非终态 {non_terminal.value}"

    def test_workflow_terminal_state_blocks_transition_to_non_terminal(self):
        """Workflow 终态保护：终态不能迁移到非终态"""
        terminal_states = [WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED, WorkflowStatus.FAILED]
        non_terminal_states = [
            WorkflowStatus.CREATED,
            WorkflowStatus.READY,
            WorkflowStatus.RUNNING,
        ]
        for terminal in terminal_states:
            for non_terminal in non_terminal_states:
                assert not can_transition_workflow(terminal, non_terminal), \
                    f"终态 {terminal.value} 不应允许迁移到非终态 {non_terminal.value}"

    def test_worker_terminal_state_blocks_transition_to_non_terminal(self):
        """Worker 终态保护：终态不能迁移到非终态"""
        terminal_states = [WorkerStatus.COMPLETED, WorkerStatus.CANCELLED, WorkerStatus.FAILED]
        non_terminal_states = [
            WorkerStatus.CREATED,
            WorkerStatus.READY,
            WorkerStatus.RUNNING,
        ]
        for terminal in terminal_states:
            for non_terminal in non_terminal_states:
                assert not can_transition_worker(terminal, non_terminal), \
                    f"终态 {terminal.value} 不应允许迁移到非终态 {non_terminal.value}"

    def test_action_terminal_state_blocks_transition_to_non_terminal(self):
        """Action 终态保护：终态不能迁移到非终态"""
        terminal_states = [
            ActionStatus.SUCCEEDED,
            ActionStatus.FAILED,
            ActionStatus.REJECTED,
            ActionStatus.CANCELLED,
        ]
        non_terminal_states = [
            ActionStatus.PROPOSED,
            ActionStatus.AUTHORIZED,
            ActionStatus.EXECUTING,
        ]
        for terminal in terminal_states:
            for non_terminal in non_terminal_states:
                assert not can_transition_action(terminal, non_terminal), \
                    f"终态 {terminal.value} 不应允许迁移到非终态 {non_terminal.value}"
