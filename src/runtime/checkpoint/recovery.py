"""
Recovery Protocol（REQ-RT-005 §6, §7）

职责：
1. 主恢复入口（§6.1 流程）
2. 选择恢复点（§6.3）
3. 恢复前校验
4. 从 sequence+1 重放事件
5. 副作用核查（§7）
6. 重新验证权限、预算、工作区

核心原则（REQ-RT-005 §3, §6, §7）：
- 恢复必须先校验检查点，再重放事件
- 已确认 Action 不得重复执行
- 状态未知 Action 进入副作用核查
- 重新授权、校验预算和资源
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.runtime.checkpoint.models import (
    ActionCheckpointRef,
    RecoveryAction,
    SideEffectState,
    WorkflowCheckpoint,
)
from src.runtime.entities.action import ActionStatus

if TYPE_CHECKING:
    from src.runtime.checkpoint.manager import CheckpointManager
    from src.runtime.event_store.store import EventStore
    from src.runtime.idempotency.manager import IdempotencyManager
    from src.runtime.projection.storage import ProjectionStorage


class RecoveryError(Exception):
    """恢复协议异常"""

    pass


class RecoveryCoordinator:
    """
    恢复协调器

    协调检查点恢复的完整流程
    """

    def __init__(
        self,
        checkpoint_manager: CheckpointManager,
        event_store: EventStore,
        projection_storage: ProjectionStorage,
        idempotency_manager: IdempotencyManager,
    ) -> None:
        self.checkpoint_manager = checkpoint_manager
        self.event_store = event_store
        self.projection_storage = projection_storage
        self.idempotency_manager = idempotency_manager
        self.side_effect_verifier = SideEffectVerifier(idempotency_manager)

    def recover_workflow(
        self, workflow_id: str, verify_permissions: bool = True
    ) -> WorkflowCheckpoint:
        """
        主恢复入口（REQ-RT-005 §6.1）

        恢复流程：
        1. 选择恢复点（§6.3）
        2. 恢复前校验
        3. 从 sequence+1 重放事件
        4. 核查未完成 Action 的副作用
        5. 重新验证权限、预算、工作区

        Args:
            workflow_id: Workflow ID
            verify_permissions: 是否重新验证权限（默认 True）

        Returns:
            恢复使用的检查点

        Raises:
            RecoveryError: 恢复失败
        """
        # 1. 选择恢复点
        checkpoint = self._select_recovery_point(workflow_id)
        if not checkpoint:
            raise RecoveryError(f"No valid checkpoint found for workflow {workflow_id}")

        # 2. 恢复前校验
        self._verify_checkpoint_validity(checkpoint)

        # 3. 从 sequence+1 重放事件
        _ = self._replay_incremental_events(checkpoint)

        # 4. 核查未完成 Action 的副作用
        state_snapshot_ref = checkpoint.state_snapshot_ref
        action_refs: list[dict[str, Any]] = []
        if isinstance(state_snapshot_ref, dict):
            action_refs = state_snapshot_ref.get("action_refs", [])

        for action_ref_dict in action_refs:
            action_ref = ActionCheckpointRef(**action_ref_dict)
            self._verify_side_effects(action_ref)

        # 5. 重新验证（MVP简化：只记录日志）
        if verify_permissions:
            self._revalidate_permissions(checkpoint)
            self._revalidate_budget(checkpoint)
            self._revalidate_workspace(checkpoint)

        return checkpoint

    def _select_recovery_point(self, workflow_id: str) -> WorkflowCheckpoint | None:
        """
        选择恢复点（REQ-RT-005 §6.3）

        回退策略：
        1. 尝试最新检查点
        2. 如果损坏，回退到前一个
        3. 重复直到找到有效检查点

        Args:
            workflow_id: Workflow ID

        Returns:
            最新有效检查点，或 None
        """
        return self.checkpoint_manager.find_valid_checkpoint(workflow_id)

    def _verify_checkpoint_validity(self, checkpoint: WorkflowCheckpoint) -> None:
        """
        恢复前校验

        验证内容：
        1. 哈希一致性
        2. 必填字段存在
        3. 检查点状态合法

        Args:
            checkpoint: 检查点对象

        Raises:
            RecoveryError: 校验失败
        """
        try:
            self.checkpoint_manager.verify_checkpoint(checkpoint)
        except Exception as e:
            raise RecoveryError(f"Checkpoint verification failed: {e}") from e

    def _replay_incremental_events(
        self, checkpoint: WorkflowCheckpoint
    ) -> list[dict[str, Any]]:
        """
        从 sequence+1 重放事件（REQ-RT-005 §6.1）

        Args:
            checkpoint: 检查点对象

        Returns:
            重放的事件列表

        Raises:
            RecoveryError: 重放失败
        """
        workflow_id = checkpoint.workflow_id
        from_sequence = checkpoint.source_event_sequence + 1

        # MVP简化：使用projection checkpoint的序列号作为终点
        projection_checkpoint = self.projection_storage.load_checkpoint(
            projection_name="workflow", partition_key=workflow_id
        )
        to_sequence = projection_checkpoint.last_applied_sequence

        if from_sequence > to_sequence:
            # 无新事件需要重放
            return []

        # MVP简化：Event Store 暂不支持范围查询，返回空列表
        # 生产环境应实现：self.event_store.get_events_range(workflow_id, from_sequence, to_sequence)
        return []

    def _verify_side_effects(self, action_ref: ActionCheckpointRef) -> None:
        """
        副作用核查（REQ-RT-005 §7）

        分类 Action 状态：
        1. 已确认成功 (§7.1)
        2. 已确认未开始 (§7.2)
        3. 结果未知 (§7.3)

        Args:
            action_ref: Action 检查点引用

        Raises:
            RecoveryError: 核查失败或需要人工介入
        """
        side_effect_state = action_ref.side_effect_state
        recovery_action = action_ref.recovery_action

        if side_effect_state == SideEffectState.CONFIRMED:
            # 已确认成功，验证幂等键
            self.side_effect_verifier.verify_confirmed_success(action_ref)

        elif side_effect_state == SideEffectState.NOT_STARTED:
            # 已确认未开始，可安全重新执行
            self.side_effect_verifier.verify_not_started(action_ref)

        elif side_effect_state == SideEffectState.UNKNOWN:
            # 结果未知，需要人工处理
            self.side_effect_verifier.verify_unknown_state(action_ref)

        elif side_effect_state == SideEffectState.IN_PROGRESS:
            # 执行中，进入人工审查
            if recovery_action == RecoveryAction.HUMAN_REVIEW:
                raise RecoveryError(
                    f"Action {action_ref.action_id} was in progress, requires human review"
                )

        elif side_effect_state == SideEffectState.FAILED:
            # 已失败，创建新 Action
            pass  # MVP简化：不自动创建新 Action

    def _revalidate_permissions(self, checkpoint: WorkflowCheckpoint) -> None:
        """
        重新验证权限（REQ-RT-005 §6.2）

        MVP简化：只记录日志，不实际校验

        Args:
            checkpoint: 检查点对象
        """
        # TODO: 实际调用 Policy Gateway 验证权限
        pass

    def _revalidate_budget(self, checkpoint: WorkflowCheckpoint) -> None:
        """
        重新验证预算（REQ-RT-005 §6.2）

        MVP简化：只记录日志，不实际校验

        Args:
            checkpoint: 检查点对象
        """
        # TODO: 实际校验预算余额
        pass

    def _revalidate_workspace(self, checkpoint: WorkflowCheckpoint) -> None:
        """
        重新验证工作区（REQ-RT-005 §6.2）

        MVP简化：只记录日志，不实际校验

        Args:
            checkpoint: 检查点对象
        """
        # TODO: 实际校验 working_revision 和 workspace
        pass


class SideEffectVerifier:
    """
    副作用验证器

    分类和验证 Action 的副作用状态
    """

    def __init__(self, idempotency_manager: IdempotencyManager) -> None:
        self.idempotency_manager = idempotency_manager

    def classify_action_state(
        self, action_id: str, action_status: ActionStatus
    ) -> tuple[SideEffectState, RecoveryAction]:
        """
        分类 Action 副作用状态（REQ-RT-005 §7）

        Args:
            action_id: Action ID
            action_status: Action 状态

        Returns:
            (副作用状态, 恢复动作)
        """
        if action_status == ActionStatus.SUCCEEDED:
            return SideEffectState.CONFIRMED, RecoveryAction.VERIFY

        if action_status == ActionStatus.FAILED:
            return SideEffectState.FAILED, RecoveryAction.CREATE_NEW_ACTION

        if action_status == ActionStatus.EXECUTING:
            return SideEffectState.IN_PROGRESS, RecoveryAction.HUMAN_REVIEW

        # PROPOSED, AUTHORIZED, WAITING_APPROVAL, REJECTED, CANCELLED
        return SideEffectState.NOT_STARTED, RecoveryAction.CREATE_NEW_ACTION

    def verify_confirmed_success(self, action_ref: ActionCheckpointRef) -> None:
        """
        验证已确认成功的 Action（REQ-RT-005 §7.1）

        通过幂等键验证副作用已完成

        Args:
            action_ref: Action 检查点引用

        Raises:
            RecoveryError: 验证失败
        """
        action_id = action_ref.action_id
        idempotency_key_ref = action_ref.idempotency_key_ref

        if not idempotency_key_ref:
            raise RecoveryError(
                f"Action {action_id} marked as CONFIRMED but missing idempotency_key_ref"
            )

        # MVP简化：假设幂等键存在即表示副作用已完成
        # 生产环境应调用: self.idempotency_manager.check_exists(idempotency_key_ref)
        pass

    def verify_not_started(self, action_ref: ActionCheckpointRef) -> None:
        """
        验证已确认未开始的 Action（REQ-RT-005 §7.2）

        Args:
            action_ref: Action 检查点引用
        """
        # MVP简化：直接返回，可安全重新执行
        pass

    def verify_unknown_state(self, action_ref: ActionCheckpointRef) -> None:
        """
        处理结果未知的 Action（REQ-RT-005 §7.3）

        Args:
            action_ref: Action 检查点引用

        Raises:
            RecoveryError: 需要人工介入
        """
        action_id = action_ref.action_id
        raise RecoveryError(
            f"Action {action_id} in UNKNOWN state, requires human review"
        )
