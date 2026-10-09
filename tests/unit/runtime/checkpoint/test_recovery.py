"""
Recovery Coordinator 单元测试（REQ-RT-005 §6, §7）
"""
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.runtime.checkpoint.manager import (
    CheckpointManager,
    InMemoryCheckpointStorage,
)
from src.runtime.checkpoint.models import (
    ActionCheckpointRef,
    BudgetSnapshot,
    CheckpointReason,
    CheckpointStatus,
    RecoveryAction,
    ResourceSnapshot,
    SideEffectState,
    StateSnapshot,
    WorkflowCheckpoint,
)
from src.runtime.checkpoint.recovery import (
    RecoveryCoordinator,
    RecoveryError,
    SideEffectVerifier,
)
from src.runtime.entities.action import ActionStatus, ActionType


class TestRecoveryCoordinator:
    """测试恢复协调器"""

    @pytest.fixture
    def checkpoint_manager(self) -> CheckpointManager:
        """创建检查点管理器"""
        storage = InMemoryCheckpointStorage()
        return CheckpointManager(storage=storage)

    @pytest.fixture
    def event_store(self) -> MagicMock:
        """Mock事件存储"""
        store = MagicMock()
        store.get_events_since.return_value = []
        return store

    @pytest.fixture
    def valid_checkpoint(self, checkpoint_manager: CheckpointManager) -> WorkflowCheckpoint:
        """创建有效的检查点"""
        from src.runtime.entities.task import TaskStatus
        from src.runtime.entities.workflow import WorkflowStatus

        state_snapshot = StateSnapshot(
            task_status=TaskStatus.EXECUTING,
            workflow_status=WorkflowStatus.RUNNING,
            current_step_id="step-001",
            runnable_step_ids=["step-002"],
            completed_step_ids=["step-001"],
            base_revision="rev-001",
        )

        budget_snapshot = BudgetSnapshot(
            max_input_tokens=10000,
            max_output_tokens=5000,
            max_total_tokens=15000,
            max_cost_microusd=1000000,
            max_duration_seconds=3600,
            max_tool_calls=100,
            consumed_input_tokens=1000,
            consumed_output_tokens=500,
            consumed_total_tokens=1500,
            consumed_cost_microusd=15000,
            elapsed_duration_seconds=120,
            completed_tool_calls=5,
        )

        resource_snapshot = ResourceSnapshot(
            workspace_id="workspace-001",
            workspace_image_version="1.0.0",
            workspace_state_hash="state-hash-123",
            base_revision="rev-001",
            network_policy_version="1.0.0",
        )

        # 先创建不带正确hash的checkpoint
        checkpoint = WorkflowCheckpoint(
            schema_version="runtime.workflow-checkpoint.v1",
            checkpoint_id="wf-001-seq5-20241009",
            workflow_id="wf-001",
            task_id="task-001",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            created_by="user-001",
            source_event_id="event-005",
            source_event_sequence=5,
            source_event_hash="abc123",
            event_stream_partition="partition-001",
            checkpoint_reason=CheckpointReason.RUNNING,
            checkpoint_status=CheckpointStatus.VERIFIED,
            content_hash="content123",
            created_at=datetime.now(UTC),
            runtime_contract_version="1.0.0",
            workflow_template_id="template-001",
            workflow_template_version="1.0.0",
            agent_profile_version="1.0.0",
            toolset_version="1.0.0",
            state_snapshot_ref=str(state_snapshot.model_dump(mode="json")),
            budget_snapshot_ref=str(budget_snapshot.model_dump(mode="json")),
            resource_snapshot_ref=str(resource_snapshot.model_dump(mode="json")),
            checkpoint_hash="temp",
            worker_refs=[],
            action_refs=[],
        )

        # 使用CheckpointManager计算正确的hash
        checkpoint_dict = checkpoint.model_dump(mode="json")
        checkpoint_dict.pop("checkpoint_hash")
        computed_hash = checkpoint_manager._compute_hash(checkpoint_dict)

        # 使用正确hash创建新checkpoint
        checkpoint = checkpoint.model_copy(update={"checkpoint_hash": computed_hash})
        return checkpoint

    @pytest.fixture
    def projection_storage(self) -> MagicMock:
        """Mock投影存储"""
        return MagicMock()

    @pytest.fixture
    def idempotency_manager(self) -> MagicMock:
        """Mock幂等性管理器"""
        return MagicMock()

    @pytest.fixture
    def recovery_coordinator(
        self,
        checkpoint_manager: CheckpointManager,
        event_store: MagicMock,
        projection_storage: MagicMock,
        idempotency_manager: MagicMock,
    ) -> RecoveryCoordinator:
        """创建恢复协调器"""
        return RecoveryCoordinator(
            checkpoint_manager=checkpoint_manager,
            event_store=event_store,
            projection_storage=projection_storage,
            idempotency_manager=idempotency_manager,
        )

    def test_recover_from_checkpoint_success(
        self,
        recovery_coordinator: RecoveryCoordinator,
        valid_checkpoint: WorkflowCheckpoint,
    ) -> None:
        """测试成功从检查点恢复"""
        # Mock _select_recovery_point返回valid_checkpoint
        recovery_coordinator._select_recovery_point = MagicMock(
            return_value=valid_checkpoint
        )

        # Mock projection_storage.load_checkpoint返回projection checkpoint
        projection_checkpoint_mock = MagicMock()
        projection_checkpoint_mock.last_applied_sequence = 10
        recovery_coordinator.projection_storage.load_checkpoint = MagicMock(
            return_value=projection_checkpoint_mock
        )

        # 执行恢复
        result = recovery_coordinator.recover_workflow(
            workflow_id="wf-001",
            verify_permissions=False,
        )

        # 验证返回的checkpoint
        assert result == valid_checkpoint

        # 验证_select_recovery_point被调用
        recovery_coordinator._select_recovery_point.assert_called_once_with("wf-001")

        # 验证projection_storage.load_checkpoint被调用
        recovery_coordinator.projection_storage.load_checkpoint.assert_called_once_with(
            projection_name="workflow",
            partition_key="wf-001",
        )

    def test_recover_from_checkpoint_invalid_checkpoint(
        self,
        recovery_coordinator: RecoveryCoordinator,
    ) -> None:
        """测试从无效检查点恢复"""
        from src.runtime.entities.task import TaskStatus
        from src.runtime.entities.workflow import WorkflowStatus

        # 创建有效的state_snapshot
        state_snapshot = StateSnapshot(
            task_status=TaskStatus.EXECUTING,
            workflow_status=WorkflowStatus.RUNNING,
            current_step_id="step-001",
            runnable_step_ids=["step-002"],
            completed_step_ids=["step-001"],
            base_revision="rev-001",
        )

        budget_snapshot = BudgetSnapshot(
            max_input_tokens=1000,
            max_output_tokens=1000,
            max_total_tokens=2000,
            max_cost_microusd=10000,
            max_duration_seconds=300,
            max_tool_calls=10,
            consumed_input_tokens=100,
            consumed_output_tokens=50,
            consumed_total_tokens=150,
            consumed_cost_microusd=500,
            elapsed_duration_seconds=30,
            completed_tool_calls=2,
        )

        resource_snapshot = ResourceSnapshot(
            workspace_id="workspace-001",
            workspace_image_version="1.0.0",
            workspace_state_hash="state-hash-123",
            base_revision="rev-001",
            network_policy_version="1.0.0",
        )

        # 创建无效检查点（错误的哈希）
        invalid_checkpoint = WorkflowCheckpoint(
            checkpoint_id="wf-001-seq5-20241009",
            workflow_id="wf-001",
            task_id="task-001",
            organization_id="org-001",
            project_id="proj-001",
            repository_id="repo-001",
            created_by="user-001",
            source_event_id="event-005",
            source_event_sequence=5,
            source_event_hash="abc123",
            event_stream_partition="partition-001",
            checkpoint_reason=CheckpointReason.RUNNING,
            checkpoint_status=CheckpointStatus.VERIFIED,
            checkpoint_hash="wrong_hash",
            content_hash="content123",
            created_at=datetime.now(UTC),
            runtime_contract_version="1.0.0",
            workflow_template_id="template-001",
            workflow_template_version="1.0.0",
            agent_profile_version="1.0.0",
            toolset_version="1.0.0",
            state_snapshot_ref=str(state_snapshot.model_dump(mode="json")),
            budget_snapshot_ref=str(budget_snapshot.model_dump(mode="json")),
            resource_snapshot_ref=str(resource_snapshot.model_dump(mode="json")),
        )

        # 验证抛出异常
        from src.runtime.checkpoint.manager import CheckpointVerificationError

        with pytest.raises(CheckpointVerificationError, match="Hash mismatch"):
            # 直接调用内部的verify_checkpoint方法来测试校验失败
            recovery_coordinator.checkpoint_manager.verify_checkpoint(invalid_checkpoint)

    def test_verify_side_effects_confirmed(
        self, recovery_coordinator: RecoveryCoordinator
    ) -> None:
        """测试已确认Action的副作用验证"""
        from src.runtime.entities.action import RiskLevel

        action_ref = ActionCheckpointRef(
            action_id="action-001",
            worker_id="worker-001",
            attempt=1,
            action_type=ActionType.READ,
            tool_name="file_read",
            tool_schema_version="1.0.0",
            target_resource_hash="hash123",
            source_revision="rev-001",
            action_status=ActionStatus.SUCCEEDED,
            risk_level=RiskLevel.LOW,
            idempotency_key_ref="idem-key-001",  # 已确认的Action必须有幂等键
            side_effect_state=SideEffectState.CONFIRMED,
            recovery_action=RecoveryAction.VERIFY,
        )

        # 验证副作用（不应抛出异常）
        recovery_coordinator._verify_side_effects(action_ref)

    def test_verify_side_effects_not_started(
        self, recovery_coordinator: RecoveryCoordinator
    ) -> None:
        """测试未开始Action的副作用验证"""
        from src.runtime.entities.action import RiskLevel

        action_ref = ActionCheckpointRef(
            action_id="action-002",
            worker_id="worker-001",
            attempt=1,
            action_type=ActionType.WRITE,
            tool_name="file_write",
            tool_schema_version="1.0.0",
            target_resource_hash="hash456",
            source_revision="rev-001",
            action_status=ActionStatus.PROPOSED,
            risk_level=RiskLevel.MEDIUM,
            side_effect_state=SideEffectState.NOT_STARTED,
            recovery_action=RecoveryAction.REPLAY_SAFE,
        )

        # 验证副作用（不应抛出异常）
        recovery_coordinator._verify_side_effects(action_ref)

    def test_verify_side_effects_unknown(
        self, recovery_coordinator: RecoveryCoordinator
    ) -> None:
        """测试未知状态Action的副作用验证"""
        from src.runtime.entities.action import RiskLevel

        action_ref = ActionCheckpointRef(
            action_id="action-003",
            worker_id="worker-001",
            attempt=1,
            action_type=ActionType.EXECUTE,
            tool_name="shell_exec",
            tool_schema_version="1.0.0",
            target_resource_hash="hash789",
            source_revision="rev-001",
            action_status=ActionStatus.EXECUTING,
            risk_level=RiskLevel.HIGH,
            side_effect_state=SideEffectState.UNKNOWN,
            recovery_action=RecoveryAction.HUMAN_REVIEW,
        )

        # 验证副作用（UNKNOWN状态会抛出RecoveryError）
        with pytest.raises(RecoveryError, match="UNKNOWN state, requires human review"):
            recovery_coordinator._verify_side_effects(action_ref)


class TestSideEffectVerifier:
    """测试副作用验证器"""

    @pytest.fixture
    def verifier(self) -> SideEffectVerifier:
        """创建副作用验证器"""
        from src.runtime.checkpoint.recovery import SideEffectVerifier

        idempotency_manager = MagicMock()
        return SideEffectVerifier(idempotency_manager)

    def test_classify_action_confirmed(
        self, verifier: SideEffectVerifier
    ) -> None:
        """测试已确认Action分类"""
        result = verifier.classify_action_state(
            action_id="action-001",
            action_status=ActionStatus.SUCCEEDED,
        )

        assert result == (SideEffectState.CONFIRMED, RecoveryAction.VERIFY)

    def test_classify_action_not_started(
        self, verifier: SideEffectVerifier
    ) -> None:
        """测试未开始Action分类"""
        result = verifier.classify_action_state(
            action_id="action-002",
            action_status=ActionStatus.PROPOSED,
        )

        assert result == (SideEffectState.NOT_STARTED, RecoveryAction.CREATE_NEW_ACTION)

    def test_classify_action_in_progress(
        self, verifier: SideEffectVerifier
    ) -> None:
        """测试进行中Action分类"""
        result = verifier.classify_action_state(
            action_id="action-003",
            action_status=ActionStatus.EXECUTING,
        )

        assert result == (SideEffectState.IN_PROGRESS, RecoveryAction.HUMAN_REVIEW)

    def test_classify_action_failed(self, verifier: SideEffectVerifier) -> None:
        """测试失败Action分类"""
        result = verifier.classify_action_state(
            action_id="action-004",
            action_status=ActionStatus.FAILED,
        )

        assert result == (SideEffectState.FAILED, RecoveryAction.CREATE_NEW_ACTION)
