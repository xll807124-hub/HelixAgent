"""
TaskProjector 增量测试（RT-004-P3）

补齐覆盖率：TaskProjector 原 73%，目标 ≥ 90%。
覆盖未被现有测试覆盖的事件：
- TaskStarted
- TaskStatusChanged
- TaskCompleted
- TaskFailed
- WorkflowAttached
- EvidenceRecorded / ApprovalRequired / ApprovalGranted
- _validate_state_invariants 完整路径
"""

from datetime import datetime

from src.runtime.projection.in_memory_storage import InMemoryProjectionStorage
from src.runtime.projection.projector import EventApplicationResult
from src.runtime.projection.task_projector import TaskProjector


def _mk_event(event_id, event_type, sequence, payload, partition_key="workflow:wf_task_test"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "event_type_version": "v1",
        "sequence": sequence,
        "partition_key": partition_key,
        "occurred_at": datetime.now().isoformat(),
        "payload": payload,
    }


class TestTaskProjectorExtendedEvents:
    """TaskProjector 全事件类型覆盖"""

    def setup_method(self):
        self.storage = InMemoryProjectionStorage()
        self.projector = TaskProjector(self.storage)

    def test_task_started(self):
        """TaskStarted：状态=PLANNING，记录 started_at 与 current_step_id"""
        self._seed_task()
        result = self.projector.apply_event(_mk_event(
            "evt_002", "TaskStarted", 2,
            {"task_id": "task_t_001", "started_at": datetime.now().isoformat(),
             "initial_step_id": "step_001"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_task_projection("task_t_001")
        assert proj.status == "PLANNING"
        assert proj.started_at is not None
        assert proj.current_step_id == "step_001"

    def test_task_status_changed(self):
        """TaskStatusChanged：更新 status 与 status_reason"""
        self._seed_task_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "TaskStatusChanged", 3,
            {"task_id": "task_t_001", "new_status": "EXECUTING",
             "reason": "Worker created", "step_id": "step_002"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_task_projection("task_t_001")
        assert proj.status == "EXECUTING"
        assert proj.status_reason == "Worker created"
        assert proj.current_step_id == "step_002"

    def test_task_status_changed_without_step_id(self):
        """TaskStatusChanged 不带 step_id：current_step_id 保持不变"""
        self._seed_task_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "TaskStatusChanged", 3,
            {"task_id": "task_t_001", "new_status": "WAITING_APPROVAL",
             "reason": "Approval needed"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_task_projection("task_t_001")
        assert proj.status == "WAITING_APPROVAL"
        # step_id 不变（保持初始 step_001）

    def test_task_completed(self):
        """TaskCompleted：状态=COMPLETED，记录 completed_at、summary、final_revision"""
        self._seed_task_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "TaskCompleted", 3,
            {"task_id": "task_t_001", "completed_at": datetime.now().isoformat(),
             "summary": {"total_steps": 5}, "final_revision": "rev_final"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_task_projection("task_t_001")
        assert proj.status == "COMPLETED"
        assert proj.completed_at is not None
        assert proj.completion_summary == {"total_steps": 5}
        assert proj.working_revision == "rev_final"

    def test_task_failed(self):
        """TaskFailed：状态=FAILED，记录 failure_reason，unresolved_failure_count +1"""
        self._seed_task_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "TaskFailed", 3,
            {"task_id": "task_t_001", "failure_reason": "Worker timeout"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_task_projection("task_t_001")
        assert proj.status == "FAILED"
        assert proj.status_reason == "Worker timeout"
        assert proj.unresolved_failure_count == 1

    def test_workflow_attached(self):
        """WorkflowAttached：设置 current_workflow_id"""
        self._seed_task_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "WorkflowAttached", 3,
            {"task_id": "task_t_001", "workflow_id": "wf_001"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_task_projection("task_t_001")
        assert proj.current_workflow_id == "wf_001"

    def test_evidence_recorded(self):
        """EvidenceRecorded：evidence_count +1"""
        self._seed_task_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "EvidenceRecorded", 3,
            {"task_id": "task_t_001", "evidence_id": "ev_001"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_task_projection("task_t_001")
        assert proj.evidence_count == 1

    def test_approval_required(self):
        """ApprovalRequired：required_approval_count +1"""
        self._seed_task_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "ApprovalRequired", 3,
            {"task_id": "task_t_001", "approval_id": "appr_001"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_task_projection("task_t_001")
        assert proj.required_approval_count == 1

    def test_approval_granted(self):
        """ApprovalGranted：required_approval_count -1（min 0）"""
        self._seed_task_with_started()
        # 先 +1
        self.projector.apply_event(_mk_event(
            "evt_003", "ApprovalRequired", 3,
            {"task_id": "task_t_001", "approval_id": "appr_001"},
        ))
        # 再 -1
        result = self.projector.apply_event(_mk_event(
            "evt_004", "ApprovalGranted", 4,
            {"task_id": "task_t_001", "approval_id": "appr_001"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_task_projection("task_t_001")
        assert proj.required_approval_count == 0

    def test_unknown_event_type_rejected(self):
        """未知事件类型：VERSION_MISMATCH"""
        self._seed_task_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "RandomUnknown", 3,
            {"task_id": "task_t_001"},
        ))
        assert result.result == EventApplicationResult.VERSION_MISMATCH

    def test_event_without_existing_projection(self):
        """TaskStarted 在无 TaskCreated 的情况下：失败"""
        result = self.projector.apply_event(_mk_event(
            "evt_001", "TaskStarted", 1,
            {"task_id": "ghost", "started_at": datetime.now().isoformat()},
        ))
        assert result.result == EventApplicationResult.VERSION_MISMATCH

    # --- 辅助 ---
    def _seed_task(self):
        self.projector.apply_event(_mk_event(
            "evt_001", "TaskCreated", 1,
            {
                "task_id": "task_t_001", "organization_id": "org_001",
                "project_id": "proj_001", "repository_id": "repo_001",
                "creator_id": "user_001", "risk_level": "LOW",
                "base_revision": "abc", "created_at": datetime.now().isoformat(),
            },
        ))

    def _seed_task_with_started(self):
        self._seed_task()
        self.projector.apply_event(_mk_event(
            "evt_002", "TaskStarted", 2,
            {"task_id": "task_t_001", "started_at": datetime.now().isoformat(),
             "initial_step_id": "step_001"},
        ))


class TestTaskProjectorInvariantsFull:
    """TaskProjector 不变量校验完整路径"""

    def setup_method(self):
        self.storage = InMemoryProjectionStorage()
        self.projector = TaskProjector(self.storage)

    def test_state_invariants_invalid_status(self):
        """status 不合法：拒绝"""
        from src.runtime.projection.models import TaskProjection

        proj = TaskProjection(
            task_id="t1", organization_id="o1", project_id="p1",
            repository_id="r1", creator_id="u1", risk_level="LOW",
            base_revision="a", status="INVALID_STATE",  # 非法
            last_event_id="e1", last_sequence=1, last_event_type="TaskCreated",
            projection_version="v1", created_at=datetime.now(), updated_at=datetime.now(),
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid
        assert "状态" in msg

    def test_state_invariants_completed_at_in_running(self):
        """completed_at 出现在非终态：拒绝"""
        from src.runtime.projection.models import TaskProjection

        proj = TaskProjection(
            task_id="t1", organization_id="o1", project_id="p1",
            repository_id="r1", creator_id="u1", risk_level="LOW",
            base_revision="a", status="PLANNING",  # 合法但非终态
            last_event_id="e1", last_sequence=1, last_event_type="TaskStarted",
            projection_version="v1",
            created_at=datetime.now(), updated_at=datetime.now(),
            completed_at=datetime.now(),  # 非终态
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid
        assert "completed_at" in msg

    def test_state_invariants_started_after_completed(self):
        """started_at > completed_at：拒绝"""
        from src.runtime.projection.models import TaskProjection

        later = datetime.now()
        earlier = datetime(2020, 1, 1)
        proj = TaskProjection(
            task_id="t1", organization_id="o1", project_id="p1",
            repository_id="r1", creator_id="u1", risk_level="LOW",
            base_revision="a", status="COMPLETED",
            last_event_id="e1", last_sequence=1, last_event_type="TaskCompleted",
            projection_version="v1",
            created_at=earlier, updated_at=later,
            started_at=later, completed_at=earlier,
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid
        assert "started_at" in msg

    def test_state_invariants_empty_task_id(self):
        """task_id 为空：拒绝"""
        from src.runtime.projection.models import TaskProjection

        proj = TaskProjection(
            task_id="",  # 非法
            organization_id="o1", project_id="p1",
            repository_id="r1", creator_id="u1", risk_level="LOW",
            base_revision="a", status="CREATED",
            last_event_id="e1", last_sequence=1, last_event_type="TaskCreated",
            projection_version="v1",
            created_at=datetime.now(), updated_at=datetime.now(),
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid