"""
CheckpointBuilder 单元测试

测试检查点构建器的核心功能：
- 从运行时状态构建 WorkflowCheckpoint
- 验证前置条件
- 构建状态快照和引用
- 计算哈希
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.runtime.checkpoint.builder import CheckpointBuilder
from src.runtime.checkpoint.models import (
    ActionCheckpointRef,
    BudgetSnapshot,
    CheckpointReason,
    RecoveryAction,
    ResourceSnapshot,
    SideEffectState,
    StateSnapshot,
    WorkerCheckpointRef,
)
from src.runtime.entities.action import ActionStatus, ActionType
from src.runtime.entities.task import RiskLevel, TaskStatus
from src.runtime.entities.worker import WorkerStatus, WorkerType
from src.runtime.entities.workflow import WorkflowStatus


class TestCheckpointBuilder:
    """测试 CheckpointBuilder"""

    @pytest.fixture
    def mock_event_store(self):
        """模拟事件存储"""
        store = MagicMock()
        store.get_last_event_sequence = AsyncMock(return_value=100)
        store.get_event_hash = AsyncMock(return_value="evt_hash_100")
        return store

    @pytest.fixture
    def mock_projection_storage(self):
        """模拟投影存储"""
        storage = MagicMock()

        # 模拟 load_checkpoint 返回值
        mock_checkpoint = MagicMock()
        mock_checkpoint.pending_gap_from = None
        mock_checkpoint.pending_gap_to = None
        mock_checkpoint.last_applied_sequence = 100
        storage.load_checkpoint = MagicMock(return_value=mock_checkpoint)

        # 模拟 load_task_projection 返回值
        mock_task_projection = MagicMock()
        mock_task_projection.status = "EXECUTING"
        storage.load_task_projection = MagicMock(return_value=mock_task_projection)

        # 模拟 load_workflow_projection 返回值
        mock_workflow_projection = MagicMock()
        mock_workflow_projection.status = "RUNNING"
        storage.load_workflow_projection = MagicMock(return_value=mock_workflow_projection)

        return storage

    @pytest.fixture
    def builder(self, mock_event_store, mock_projection_storage):
        """创建 CheckpointBuilder 实例"""
        return CheckpointBuilder(mock_event_store, mock_projection_storage)

    def test_build_from_workflow(self, builder):
        """测试从 Workflow 构建检查点"""
        checkpoint = builder.build_from_workflow(
            workflow_id="wf_001",
            task_id="task_001",
            organization_id="org_001",
            project_id="proj_001",
            repository_id="repo_001",
            reason=CheckpointReason.RUNNING,
            created_by="system",
        )

        assert checkpoint.workflow_id == "wf_001"
        assert checkpoint.task_id == "task_001"
        assert checkpoint.checkpoint_reason == CheckpointReason.RUNNING
        assert checkpoint.checkpoint_hash is not None
        assert checkpoint.content_hash is not None

    def test_build_worker_checkpoint_ref(self):
        """测试构建 WorkerCheckpointRef"""
        worker_ref = WorkerCheckpointRef(
            worker_id="worker_001",
            step_id="step_001",
            worker_type=WorkerType.CODER,
            attempt=1,
            status=WorkerStatus.RUNNING,
            source_revision="rev_001",
            last_applied_event_sequence=50,
        )

        assert worker_ref.worker_id == "worker_001"
        assert worker_ref.step_id == "step_001"
        assert worker_ref.worker_type == WorkerType.CODER
        assert worker_ref.status == WorkerStatus.RUNNING
        assert worker_ref.last_applied_event_sequence == 50

    def test_build_action_checkpoint_ref_confirmed(self):
        """测试构建已确认的 ActionCheckpointRef"""
        action_ref = ActionCheckpointRef(
            action_id="action_001",
            worker_id="worker_001",
            attempt=1,
            action_type=ActionType.WRITE,
            tool_name="git",
            tool_schema_version="v1.0.0",
            target_resource_hash="resource_hash_001",
            source_revision="rev_001",
            action_status=ActionStatus.SUCCEEDED,
            risk_level=RiskLevel.MEDIUM,
            side_effect_state=SideEffectState.CONFIRMED,
            recovery_action=RecoveryAction.VERIFY,
            policy_decision_id="policy_001",
            idempotency_key_ref="idem_key_001",
        )

        assert action_ref.action_id == "action_001"
        assert action_ref.action_type == ActionType.WRITE
        assert action_ref.side_effect_state == SideEffectState.CONFIRMED
        assert action_ref.policy_decision_id == "policy_001"

    def test_build_action_checkpoint_ref_not_started(self):
        """测试构建未开始的 ActionCheckpointRef"""
        action_ref = ActionCheckpointRef(
            action_id="action_002",
            worker_id="worker_001",
            attempt=1,
            action_type=ActionType.READ,
            tool_name="filesystem",
            tool_schema_version="v1.0.0",
            target_resource_hash="resource_hash_002",
            source_revision="rev_001",
            action_status=ActionStatus.PROPOSED,
            risk_level=RiskLevel.LOW,
            side_effect_state=SideEffectState.NOT_STARTED,
            recovery_action=RecoveryAction.REPLAY_SAFE,
        )

        assert action_ref.action_id == "action_002"
        assert action_ref.side_effect_state == SideEffectState.NOT_STARTED
        assert action_ref.policy_decision_id is None


class TestStateSnapshotBuilder:
    """测试从投影构建 StateSnapshot"""

    def test_build_from_projection(self):
        """测试从投影构建状态快照"""
        # 模拟投影数据
        projection_data = {
            "task_status": "executing",
            "workflow_status": "running",
            "base_revision": "rev_001",
            "current_step_id": "step_001",
            "runnable_step_ids": ["step_002"],
            "completed_step_ids": ["step_000"],
        }

        snapshot = StateSnapshot(
            task_status=TaskStatus.EXECUTING,
            workflow_status=WorkflowStatus.RUNNING,
            base_revision=projection_data["base_revision"],
            current_step_id=projection_data.get("current_step_id"),
            runnable_step_ids=projection_data.get("runnable_step_ids", []),
            completed_step_ids=projection_data.get("completed_step_ids", []),
        )

        assert snapshot.task_status == TaskStatus.EXECUTING
        assert snapshot.workflow_status == WorkflowStatus.RUNNING
        assert snapshot.current_step_id == "step_001"
        assert "step_002" in snapshot.runnable_step_ids
        assert "step_000" in snapshot.completed_step_ids


class TestBudgetSnapshotBuilder:
    """测试预算快照构建"""

    def test_build_budget_snapshot(self):
        """测试构建预算快照"""
        budget = BudgetSnapshot(
            max_input_tokens=5000,
            max_output_tokens=5000,
            max_total_tokens=10000,
            max_cost_microusd=100000000,
            max_duration_seconds=3600,
            max_tool_calls=100,
            consumed_input_tokens=2500,
            consumed_output_tokens=2500,
            consumed_total_tokens=5000,
            consumed_cost_microusd=50000000,
            elapsed_duration_seconds=1800,
            completed_tool_calls=50,
        )

        assert budget.max_total_tokens == 10000
        assert budget.consumed_total_tokens == 5000
        assert budget.remaining_tokens == 5000
        assert not budget.is_budget_exceeded

    def test_budget_remaining_calculation(self):
        """测试预算剩余计算"""
        budget = BudgetSnapshot(
            max_input_tokens=5000,
            max_output_tokens=5000,
            max_total_tokens=10000,
            max_cost_microusd=100000000,
            max_duration_seconds=3600,
            max_tool_calls=100,
            consumed_input_tokens=1000,
            consumed_output_tokens=1000,
            consumed_total_tokens=2000,
            consumed_cost_microusd=20000000,
            elapsed_duration_seconds=600,
            completed_tool_calls=20,
        )

        assert budget.remaining_tokens == 8000
        assert not budget.is_budget_exceeded


class TestResourceSnapshotBuilder:
    """测试资源快照构建"""

    def test_build_resource_snapshot(self):
        """测试构建资源快照"""
        resource = ResourceSnapshot(
            workspace_id="ws_001",
            workspace_state_hash="ws_hash_001",
            base_revision="rev_001",
            workspace_image_version="v1.0.0",
            network_policy_version="v1.0.0",
            working_revision="rev_002",
            generated_artifact_refs=["artifact_001", "artifact_002"],
            credential_refs=["cred_ref_001"],
        )

        assert resource.workspace_id == "ws_001"
        assert resource.base_revision == "rev_001"
        assert resource.working_revision == "rev_002"
        assert len(resource.generated_artifact_refs) == 2
        assert "artifact_001" in resource.generated_artifact_refs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
