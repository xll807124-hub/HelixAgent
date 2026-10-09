"""测试 Checkpoint Models（REQ-RT-005 §4）"""
from datetime import UTC, datetime

from src.runtime.checkpoint.models import (
    ActionCheckpointRef,
    BudgetSnapshot,
    CheckpointReason,
    CheckpointStatus,
    RecoveryAction,
    ResourceSnapshot,
    SideEffectState,
    StateSnapshot,
    WorkerCheckpointRef,
    WorkflowCheckpoint,
)
from src.runtime.entities.action import ActionStatus, ActionType, RiskLevel
from src.runtime.entities.task import TaskStatus
from src.runtime.entities.worker import WorkerStatus, WorkerType
from src.runtime.entities.workflow import WorkflowStatus


class TestWorkflowCheckpoint:
    """测试 WorkflowCheckpoint 模型"""

    def test_create_minimal_checkpoint(self):
        """测试创建最小检查点"""
        checkpoint = WorkflowCheckpoint(
            checkpoint_id="ckpt_001",
            workflow_id="wf_001",
            task_id="task_001",
            organization_id="org_001",
            project_id="proj_001",
            repository_id="repo_001",
            created_at=datetime.now(UTC),
            created_by="system",
            source_event_sequence=100,
            source_event_id="evt_100",
            source_event_hash="abc123",
            event_stream_partition="default",
            checkpoint_reason=CheckpointReason.RUNNING,
            content_hash="content_hash_123",
            checkpoint_hash="hash123",
            runtime_contract_version="v1.0.0",
            workflow_template_id="tpl_001",
            workflow_template_version="v1.0.0",
            agent_profile_version="v1.0.0",
            toolset_version="v1.0.0",
            state_snapshot_ref="state_ref_001",
            budget_snapshot_ref="budget_ref_001",
            resource_snapshot_ref="resource_ref_001",
        )
        assert checkpoint.checkpoint_id == "ckpt_001"
        assert checkpoint.workflow_id == "wf_001"
        assert checkpoint.source_event_sequence == 100
        assert checkpoint.checkpoint_reason == CheckpointReason.RUNNING
        assert checkpoint.checkpoint_status == CheckpointStatus.CREATED

    def test_checkpoint_with_full_metadata(self):
        """测试完整元数据检查点"""
        checkpoint = WorkflowCheckpoint(
            checkpoint_id="ckpt_002",
            workflow_id="wf_002",
            task_id="task_002",
            organization_id="org_001",
            project_id="proj_001",
            repository_id="repo_001",
            created_at=datetime.now(UTC),
            created_by="user_001",
            source_event_sequence=200,
            source_event_id="evt_200",
            source_event_hash="def456",
            event_stream_partition="default",
            checkpoint_reason=CheckpointReason.APPROVAL,
            content_hash="content_hash_456",
            checkpoint_hash="hash456",
            runtime_contract_version="v1.0.0",
            workflow_template_id="tpl_002",
            workflow_template_version="v2.0.0",
            agent_profile_version="v1.5.0",
            toolset_version="v1.2.0",
            state_snapshot_ref="state_ref_002",
            budget_snapshot_ref="budget_ref_002",
            resource_snapshot_ref="resource_ref_002",
        )
        assert checkpoint.organization_id == "org_001"
        assert checkpoint.project_id == "proj_001"
        assert checkpoint.runtime_contract_version == "v1.0.0"
        assert checkpoint.workflow_template_version == "v2.0.0"
        assert checkpoint.agent_profile_version == "v1.5.0"

    def test_checkpoint_serialization(self):
        """测试检查点序列化"""
        checkpoint = WorkflowCheckpoint(
            checkpoint_id="ckpt_003",
            workflow_id="wf_003",
            task_id="task_003",
            organization_id="org_001",
            project_id="proj_001",
            repository_id="repo_001",
            created_at=datetime.now(UTC),
            created_by="system",
            source_event_sequence=300,
            source_event_id="evt_300",
            source_event_hash="ghi789",
            event_stream_partition="default",
            checkpoint_reason=CheckpointReason.PAUSE,
            content_hash="content_hash_789",
            checkpoint_hash="hash789",
            runtime_contract_version="v1.0.0",
            workflow_template_id="tpl_003",
            workflow_template_version="v1.0.0",
            agent_profile_version="v1.0.0",
            toolset_version="v1.0.0",
            state_snapshot_ref="state_ref_003",
            budget_snapshot_ref="budget_ref_003",
            resource_snapshot_ref="resource_ref_003",
        )
        # 测试序列化
        data = checkpoint.model_dump()
        assert data["checkpoint_id"] == "ckpt_003"
        assert data["checkpoint_reason"] == "PAUSE"

        # 测试反序列化
        restored = WorkflowCheckpoint(**data)
        assert restored.checkpoint_id == checkpoint.checkpoint_id
        assert restored.checkpoint_reason == checkpoint.checkpoint_reason


class TestStateSnapshot:
    """测试 StateSnapshot 模型"""

    def test_create_state_snapshot(self):
        """测试创建状态快照"""
        snapshot = StateSnapshot(
            task_status=TaskStatus.EXECUTING,
            workflow_status=WorkflowStatus.RUNNING,
            base_revision="rev_001",
        )
        assert snapshot.task_status == TaskStatus.EXECUTING
        assert snapshot.workflow_status == WorkflowStatus.RUNNING
        assert snapshot.base_revision == "rev_001"


class TestWorkerCheckpointRef:
    """测试 WorkerCheckpointRef 模型"""

    def test_create_worker_ref(self):
        """测试创建 Worker 引用"""
        worker_ref = WorkerCheckpointRef(
            worker_id="worker_001",
            step_id="step_001",
            worker_type=WorkerType.CODER,
            attempt=1,
            status=WorkerStatus.RUNNING,
            source_revision="rev_001",
            last_applied_event_sequence=100,
        )
        assert worker_ref.worker_id == "worker_001"
        assert worker_ref.worker_type == WorkerType.CODER
        assert worker_ref.status == WorkerStatus.RUNNING
        assert worker_ref.last_applied_event_sequence == 100


class TestActionCheckpointRef:
    """测试 ActionCheckpointRef 模型"""

    def test_create_action_ref_confirmed(self):
        """测试创建已确认成功的 Action 引用"""
        action_ref = ActionCheckpointRef(
            action_id="action_001",
            worker_id="worker_001",
            attempt=1,
            action_type=ActionType.WRITE,
            tool_name="git_commit",
            tool_schema_version="v1",
            target_resource_hash="hash123",
            source_revision="rev_001",
            action_status=ActionStatus.SUCCEEDED,
            risk_level=RiskLevel.MEDIUM,
            side_effect_state=SideEffectState.CONFIRMED,
            recovery_action=RecoveryAction.VERIFY,
            idempotency_key_ref="idem_001",
        )
        assert action_ref.action_type == ActionType.WRITE
        assert action_ref.action_status == ActionStatus.SUCCEEDED
        assert action_ref.side_effect_state == SideEffectState.CONFIRMED
        assert action_ref.recovery_action == RecoveryAction.VERIFY

    def test_create_action_ref_not_started(self):
        """测试创建未开始的 Action 引用"""
        action_ref = ActionCheckpointRef(
            action_id="action_002",
            worker_id="worker_001",
            attempt=1,
            action_type=ActionType.READ,
            tool_name="file_read",
            tool_schema_version="v1",
            target_resource_hash="hash456",
            source_revision="rev_001",
            action_status=ActionStatus.PROPOSED,
            risk_level=RiskLevel.LOW,
            side_effect_state=SideEffectState.NOT_STARTED,
            recovery_action=RecoveryAction.CREATE_NEW_ACTION,
        )
        assert action_ref.action_status == ActionStatus.PROPOSED
        assert action_ref.side_effect_state == SideEffectState.NOT_STARTED
        assert action_ref.recovery_action == RecoveryAction.CREATE_NEW_ACTION

    def test_create_action_ref_unknown(self):
        """测试创建状态未知的 Action 引用"""
        action_ref = ActionCheckpointRef(
            action_id="action_003",
            worker_id="worker_001",
            attempt=1,
            action_type=ActionType.EXECUTE,
            tool_name="shell_exec",
            tool_schema_version="v1",
            target_resource_hash="hash789",
            source_revision="rev_001",
            action_status=ActionStatus.EXECUTING,
            risk_level=RiskLevel.HIGH,
            side_effect_state=SideEffectState.UNKNOWN,
            recovery_action=RecoveryAction.HUMAN_REVIEW,
        )
        assert action_ref.risk_level == RiskLevel.HIGH
        assert action_ref.side_effect_state == SideEffectState.UNKNOWN
        assert action_ref.recovery_action == RecoveryAction.HUMAN_REVIEW


class TestBudgetSnapshot:
    """测试 BudgetSnapshot 模型"""

    def test_create_budget_snapshot(self):
        """测试创建预算快照"""
        budget = BudgetSnapshot(
            max_input_tokens=5000,
            max_output_tokens=5000,
            max_total_tokens=10000,
            max_cost_microusd=100000000,  # 100 USD in microUSD
            max_duration_seconds=3600,
            max_tool_calls=100,
            consumed_input_tokens=2500,
            consumed_output_tokens=2500,
            consumed_total_tokens=5000,
            consumed_cost_microusd=50000000,  # 50 USD in microUSD
            elapsed_duration_seconds=1800,
            completed_tool_calls=50,
        )
        assert budget.max_total_tokens == 10000
        assert budget.consumed_total_tokens == 5000
        assert budget.remaining_tokens == 5000
        assert budget.is_budget_exceeded is False

    def test_budget_exceeded(self):
        """测试预算超限"""
        budget = BudgetSnapshot(
            max_input_tokens=5000,
            max_output_tokens=5000,
            max_total_tokens=10000,
            max_cost_microusd=100000000,
            max_duration_seconds=3600,
            max_tool_calls=100,
            consumed_input_tokens=6000,
            consumed_output_tokens=6000,
            consumed_total_tokens=12000,
            consumed_cost_microusd=50000000,
            elapsed_duration_seconds=1800,
            completed_tool_calls=50,
        )
        assert budget.is_budget_exceeded is True
        assert budget.remaining_tokens == 0


class TestResourceSnapshot:
    """测试 ResourceSnapshot 模型"""

    def test_create_resource_snapshot(self):
        """测试创建资源快照"""
        resource = ResourceSnapshot(
            workspace_id="ws_001",
            workspace_image_version="v1.0.0",
            workspace_state_hash="hash123",
            base_revision="rev_001",
            working_revision="rev_002",
            branch_ref="refs/heads/main",
            network_policy_version="v1.0.0",
        )
        assert resource.workspace_id == "ws_001"
        assert resource.base_revision == "rev_001"
        assert resource.working_revision == "rev_002"
        assert resource.branch_ref == "refs/heads/main"


class TestEnums:
    """测试枚举类型"""

    def test_checkpoint_reason_enum(self):
        """测试 CheckpointReason 枚举"""
        assert CheckpointReason.RUNNING.value == "RUNNING"
        assert CheckpointReason.PAUSE.value == "PAUSE"
        assert CheckpointReason.APPROVAL.value == "APPROVAL"
        assert CheckpointReason.RECOVERY.value == "RECOVERY"

    def test_checkpoint_status_enum(self):
        """测试 CheckpointStatus 枚举"""
        assert CheckpointStatus.CREATED.value == "CREATED"
        assert CheckpointStatus.VERIFIED.value == "VERIFIED"
        assert CheckpointStatus.INVALID.value == "INVALID"

    def test_side_effect_state_enum(self):
        """测试 SideEffectState 枚举"""
        assert SideEffectState.NOT_STARTED.value == "NOT_STARTED"
        assert SideEffectState.IN_PROGRESS.value == "IN_PROGRESS"
        assert SideEffectState.CONFIRMED.value == "CONFIRMED"
        assert SideEffectState.FAILED.value == "FAILED"
        assert SideEffectState.UNKNOWN.value == "UNKNOWN"

    def test_recovery_action_enum(self):
        """测试 RecoveryAction 枚举"""
        assert RecoveryAction.VERIFY.value == "VERIFY"
        assert RecoveryAction.REPLAY_SAFE.value == "REPLAY_SAFE"
        assert RecoveryAction.CREATE_NEW_ACTION.value == "CREATE_NEW_ACTION"
        assert RecoveryAction.HUMAN_REVIEW.value == "HUMAN_REVIEW"
