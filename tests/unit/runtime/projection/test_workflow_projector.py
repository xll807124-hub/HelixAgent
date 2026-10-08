"""
WorkflowProjector 完整测试（RT-004-P3）

补齐覆盖率：WorkflowProjector 原 76%，目标 ≥ 90%。
覆盖被 REQ §3.5 父子投影汇聚规则约束的事件类型：
- WorkflowCreated / WorkflowStarted / WorkflowStatusChanged
- WorkflowCompleted / WorkflowFailed
- WorkerRegistered / WorkerStarted / WorkerCompleted / WorkerFailed
- WorkerWaitingApproval / WorkerApprovalGranted
"""

from datetime import datetime

from src.runtime.projection.in_memory_storage import InMemoryProjectionStorage
from src.runtime.projection.projector import EventApplicationResult
from src.runtime.projection.workflow_projector import WorkflowProjector


def _mk_event(event_id, event_type, sequence, payload, partition_key="workflow:wf_t_001"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "event_type_version": "v1",
        "sequence": sequence,
        "partition_key": partition_key,
        "occurred_at": datetime.now().isoformat(),
        "payload": payload,
    }


class TestWorkflowProjectorBasic:
    """WorkflowProjector 自身生命周期"""

    def setup_method(self):
        self.storage = InMemoryProjectionStorage()
        self.projector = WorkflowProjector(self.storage)

    def test_workflow_created(self):
        """WorkflowCreated：状态=READY"""
        ev = _mk_event(
            "evt_001", "WorkflowCreated", 1,
            {
                "workflow_id": "wf_t_001", "task_id": "task_t_001",
                "organization_id": "org_001", "project_id": "proj_001",
                "repository_id": "repo_001",
                "workflow_template_id": "tpl_v1",
                "workflow_template_version": "v1.0",
                "agent_profile_version": "ap_v1",
                "toolset_version": "ts_v1",
                "base_revision": "abc",
                "created_at": datetime.now().isoformat(),
            },
        )
        result = self.projector.apply_event(ev)
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.status == "READY"

    def test_workflow_started(self):
        """WorkflowStarted：状态=RUNNING"""
        self._seed_workflow()
        result = self.projector.apply_event(_mk_event(
            "evt_002", "WorkflowStarted", 2,
            {"workflow_id": "wf_t_001", "started_at": datetime.now().isoformat()},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.status == "RUNNING"
        assert proj.started_at is not None

    def test_workflow_status_changed(self):
        """WorkflowStatusChanged：更新 status 和 reason"""
        self._seed_workflow_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "WorkflowStatusChanged", 3,
            {"workflow_id": "wf_t_001", "new_status": "PAUSED",
             "reason": "wait for resource"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.status == "PAUSED"
        assert proj.status_reason == "wait for resource"

    def test_workflow_completed(self):
        """WorkflowCompleted：状态=COMPLETED，记录 final_revision"""
        self._seed_workflow_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "WorkflowCompleted", 3,
            {"workflow_id": "wf_t_001", "completed_at": datetime.now().isoformat(),
             "final_revision": "rev_final"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.status == "COMPLETED"
        assert proj.working_revision == "rev_final"

    def test_workflow_failed(self):
        """WorkflowFailed：状态=FAILED"""
        self._seed_workflow_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "WorkflowFailed", 3,
            {"workflow_id": "wf_t_001", "failure_reason": "branch aborted"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.status == "FAILED"
        assert proj.status_reason == "branch aborted"

    def test_unknown_workflow_event_rejected(self):
        """未知事件类型：失败"""
        self._seed_workflow_with_started()
        result = self.projector.apply_event(_mk_event(
            "evt_003", "RandomEvent", 3, {"workflow_id": "wf_t_001"}
        ))
        assert result.result == EventApplicationResult.VERSION_MISMATCH

    # --- 辅助 ---
    def _seed_workflow(self):
        self.projector.apply_event(_mk_event(
            "evt_001", "WorkflowCreated", 1,
            {
                "workflow_id": "wf_t_001", "task_id": "task_t_001",
                "organization_id": "org_001", "project_id": "proj_001",
                "repository_id": "repo_001",
                "workflow_template_id": "tpl_v1",
                "workflow_template_version": "v1.0",
                "agent_profile_version": "ap_v1",
                "toolset_version": "ts_v1",
                "base_revision": "abc",
                "created_at": datetime.now().isoformat(),
            },
        ))

    def _seed_workflow_with_started(self):
        self._seed_workflow()
        self.projector.apply_event(_mk_event(
            "evt_002", "WorkflowStarted", 2,
            {"workflow_id": "wf_t_001", "started_at": datetime.now().isoformat()},
        ))


class TestWorkflowProjectorChildWorkerAggregation:
    """父子汇聚计数（REQ-RT-004 §3.5）"""

    def setup_method(self):
        self.storage = InMemoryProjectionStorage()
        self.projector = WorkflowProjector(self.storage)
        self.projector.apply_event(_mk_event(
            "evt_001", "WorkflowCreated", 1,
            {
                "workflow_id": "wf_t_001", "task_id": "task_t_001",
                "organization_id": "org_001", "project_id": "proj_001",
                "repository_id": "repo_001",
                "workflow_template_id": "tpl_v1",
                "workflow_template_version": "v1.0",
                "agent_profile_version": "ap_v1",
                "toolset_version": "ts_v1",
                "base_revision": "abc",
                "created_at": datetime.now().isoformat(),
            },
        ))
        self.projector.apply_event(_mk_event(
            "evt_002", "WorkflowStarted", 2,
            {"workflow_id": "wf_t_001", "started_at": datetime.now().isoformat()},
        ))

    def test_worker_registered_increments_runnable_and_required(self):
        """WorkerRegistered: required +1, runnable +1"""
        result = self.projector.apply_event(_mk_event(
            "evt_003", "WorkerRegistered", 3,
            {"workflow_id": "wf_t_001", "worker_id": "wk_001"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.required_worker_count == 1
        assert proj.runnable_worker_count == 1

    def test_worker_started_moves_runnable_to_running(self):
        """WorkerStarted: runnable -1, running +1, active_attempt +1"""
        self.projector.apply_event(_mk_event(
            "evt_003", "WorkerRegistered", 3,
            {"workflow_id": "wf_t_001", "worker_id": "wk_001"},
        ))
        result = self.projector.apply_event(_mk_event(
            "evt_004", "WorkerStarted", 4,
            {"workflow_id": "wf_t_001", "worker_id": "wk_001"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.runnable_worker_count == 0
        assert proj.running_worker_count == 1
        assert proj.active_attempt_count == 1

    def test_worker_completed_moves_running_to_completed(self):
        """WorkerCompleted: running -1, completed +1"""
        self._seed_running_worker()
        result = self.projector.apply_event(_mk_event(
            "evt_005", "WorkerCompleted", 5,
            {"workflow_id": "wf_t_001", "worker_id": "wk_001"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.running_worker_count == 0
        assert proj.completed_worker_count == 1

    def test_worker_failed_moves_running_to_failed(self):
        """WorkerFailed: running -1, failed +1"""
        self._seed_running_worker()
        result = self.projector.apply_event(_mk_event(
            "evt_005", "WorkerFailed", 5,
            {"workflow_id": "wf_t_001", "worker_id": "wk_001",
             "failure_reason": "tool error"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.running_worker_count == 0
        assert proj.failed_worker_count == 1

    def test_worker_waiting_approval(self):
        """WorkerWaitingApproval: waiting_approval +1"""
        self._seed_running_worker()
        result = self.projector.apply_event(_mk_event(
            "evt_005", "WorkerWaitingApproval", 5,
            {"workflow_id": "wf_t_001", "worker_id": "wk_001"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.waiting_approval_count == 1

    def test_worker_approval_granted_decrements_waiting(self):
        """WorkerApprovalGranted: waiting_approval -1"""
        self._seed_running_worker()
        self.projector.apply_event(_mk_event(
            "evt_005", "WorkerWaitingApproval", 5,
            {"workflow_id": "wf_t_001", "worker_id": "wk_001"},
        ))
        result = self.projector.apply_event(_mk_event(
            "evt_006", "WorkerApprovalGranted", 6,
            {"workflow_id": "wf_t_001", "worker_id": "wk_001"},
        ))
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_workflow_projection("wf_t_001")
        assert proj.waiting_approval_count == 0

    def _seed_running_worker(self):
        self.projector.apply_event(_mk_event(
            "evt_003", "WorkerRegistered", 3,
            {"workflow_id": "wf_t_001", "worker_id": "wk_001"},
        ))
        self.projector.apply_event(_mk_event(
            "evt_004", "WorkerStarted", 4,
            {"workflow_id": "wf_t_001", "worker_id": "wk_001"},
        ))


class TestWorkflowProjectorInvariants:
    """WorkflowProjector 不变量校验"""

    def setup_method(self):
        self.storage = InMemoryProjectionStorage()
        self.projector = WorkflowProjector(self.storage)

    def test_state_invariants_empty_workflow_id(self):
        """workflow_id 为空：拒绝"""
        from src.runtime.projection.models import WorkflowProjection

        proj = WorkflowProjection(
            workflow_id="",  # 非法
            task_id="t1", organization_id="o1", project_id="p1", repository_id="r1",
            status="READY",
            workflow_template_id="tpl", workflow_template_version="v1",
            agent_profile_version="ap_v1", toolset_version="ts_v1",
            base_revision="a",
            last_event_id="e1", last_sequence=1, projection_version="v1",
            created_at=datetime.now(), updated_at=datetime.now(),
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid

    def test_state_invariants_completed_at_in_running(self):
        """completed_at 出现在非终态：拒绝"""
        from src.runtime.projection.models import WorkflowProjection

        proj = WorkflowProjection(
            workflow_id="wf1", task_id="t1", organization_id="o1",
            project_id="p1", repository_id="r1", status="RUNNING",
            workflow_template_id="tpl", workflow_template_version="v1",
            agent_profile_version="ap_v1", toolset_version="ts_v1",
            base_revision="a",
            last_event_id="e1", last_sequence=1, projection_version="v1",
            created_at=datetime.now(), updated_at=datetime.now(),
            completed_at=datetime.now(),
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid
        assert "completed_at" in msg

    def test_state_invariants_negative_count_rejected(self):
        """计数字段为负：拒绝（pydantic 层 ge=0 直接拦截，测试不变量逻辑则需要绕过）"""
        # WorkflowProjection 用 pydantic.ge=0 限制计数 >=0；pydantic 会先拦下。
        # 这里验证 pydantic 拦截正确，再用 allowed zero 来检验不变量 OK 路径。
        import pydantic
        import pytest

        with pytest.raises(pydantic.ValidationError):
            from src.runtime.projection.models import WorkflowProjection
            WorkflowProjection(
                workflow_id="wf1", task_id="t1", organization_id="o1",
                project_id="p1", repository_id="r1", status="READY",
                workflow_template_id="tpl", workflow_template_version="v1",
                agent_profile_version="ap_v1", toolset_version="ts_v1",
                base_revision="a",
                last_event_id="e1", last_sequence=1, projection_version="v1",
                created_at=datetime.now(), updated_at=datetime.now(),
                required_worker_count=-1,  # 非法
            )

    def test_state_invariants_over_workers_rejected(self):
        """已处理 Worker 总数远超 required_worker_count：拒绝"""
        from src.runtime.projection.models import WorkflowProjection

        proj = WorkflowProjection(
            workflow_id="wf1", task_id="t1", organization_id="o1",
            project_id="p1", repository_id="r1", status="RUNNING",
            workflow_template_id="tpl", workflow_template_version="v1",
            agent_profile_version="ap_v1", toolset_version="ts_v1",
            base_revision="a",
            last_event_id="e1", last_sequence=1, projection_version="v1",
            created_at=datetime.now(), updated_at=datetime.now(),
            required_worker_count=2,  # 只要求 2 个
            running_worker_count=10,  # 但运行 10 个
            completed_worker_count=10,  # 完成 10 个
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid
        assert "远超" in msg or "Worker" in msg

    def test_extract_entity_id_worker_event_uses_partition(self):
        """_extract_entity_id：Worker 事件走 partition_key"""
        event = {
            "event_type": "WorkerStarted",
            "partition_key": "workflow:wf_xyz",
            "payload": {"worker_id": "wk_xyz"},
        }
        eid = self.projector._extract_entity_id(event)
        assert eid == "wf_xyz"

    def test_extract_entity_id_workflow_event(self):
        """_extract_entity_id：Workflow 事件走 payload.workflow_id"""
        event = {
            "event_type": "WorkflowStarted",
            "partition_key": "workflow:wf_xyz",
            "payload": {"workflow_id": "wf_xyz_payload"},
        }
        eid = self.projector._extract_entity_id(event)
        assert eid == "wf_xyz_payload"