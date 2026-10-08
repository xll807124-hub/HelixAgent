"""
WorkerProjector 单元测试（REQ-RT-004 §5.3）

补齐覆盖率：WorkerProjector 原覆盖率未测，目标 ≥ 90%。
"""

from datetime import datetime

from src.runtime.projection.in_memory_storage import InMemoryProjectionStorage
from src.runtime.projection.projector import EventApplicationResult
from src.runtime.projection.worker_projector import WorkerProjector


def _mk_event(
    event_id: str,
    event_type: str,
    sequence: int,
    payload: dict,
    partition_key: str = "workflow:wf_worker_test",
):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "event_type_version": "v1",
        "sequence": sequence,
        "partition_key": partition_key,
        "occurred_at": datetime.now().isoformat(),
        "payload": payload,
    }


class TestWorkerProjectorBasic:
    """WorkerProjector 基础事件应用"""

    def setup_method(self):
        self.storage = InMemoryProjectionStorage()
        self.projector = WorkerProjector(self.storage)

    def test_worker_created_initial(self):
        """WorkerCreated：创建初始投影，状态=READY"""
        event = _mk_event(
            "evt_001",
            "WorkerCreated",
            1,
            {
                "worker_id": "worker_001",
                "workflow_id": "wf_001",
                "task_id": "task_001",
                "step_id": "step_001",
                "worker_type": "CODER",
                "attempt": 1,
                "source_revision": "abc123",
                "created_at": datetime.now().isoformat(),
            },
        )
        result = self.projector.apply_event(event)
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_worker_projection("worker_001")
        assert proj is not None
        assert proj.status == "READY"
        assert proj.worker_type == "CODER"

    def test_worker_started(self):
        """WorkerStarted：状态=RUNNING"""
        self._seed_worker()
        result = self.projector.apply_event(
            _mk_event(
                "evt_002",
                "WorkerStarted",
                2,
                {"worker_id": "worker_001", "started_at": datetime.now().isoformat()},
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_worker_projection("worker_001")
        assert proj.status == "RUNNING"
        assert proj.started_at is not None

    def test_worker_status_changed(self):
        """WorkerStatusChanged：new_status 与 reason 写入"""
        self._seed_worker()
        result = self.projector.apply_event(
            _mk_event(
                "evt_002",
                "WorkerStatusChanged",
                2,
                {"worker_id": "worker_001", "new_status": "PAUSED", "reason": "wait for approval"},
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_worker_projection("worker_001")
        assert proj.status == "PAUSED"
        assert proj.status_reason == "wait for approval"

    def test_worker_completed(self):
        """WorkerCompleted：状态=COMPLETED，output_artifact_ids 写入"""
        self._seed_worker_with_started()
        result = self.projector.apply_event(
            _mk_event(
                "evt_003",
                "WorkerCompleted",
                3,
                {
                    "worker_id": "worker_001",
                    "completed_at": datetime.now().isoformat(),
                    "output_artifact_ids": ["art_1", "art_2"],
                },
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_worker_projection("worker_001")
        assert proj.status == "COMPLETED"
        assert proj.output_artifact_ids == ["art_1", "art_2"]

    def test_worker_failed(self):
        """WorkerFailed：状态=FAILED，failure_reason 写入"""
        self._seed_worker_with_started()
        result = self.projector.apply_event(
            _mk_event(
                "evt_003",
                "WorkerFailed",
                3,
                {
                    "worker_id": "worker_001",
                    "failed_at": datetime.now().isoformat(),
                    "failure_reason": "tool timeout",
                },
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_worker_projection("worker_001")
        assert proj.status == "FAILED"
        assert proj.status_reason == "tool timeout"

    def test_action_proposed_increments_waiting(self):
        """ActionProposed：waiting_action_count +1"""
        self._seed_worker_with_started()
        result = self.projector.apply_event(
            _mk_event(
                "evt_003",
                "ActionProposed",
                3,
                {"worker_id": "worker_001", "action_id": "action_001"},
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_worker_projection("worker_001")
        assert proj.waiting_action_count == 1

    def test_action_started_increments_active_decrements_waiting(self):
        """ActionStarted：waiting -1，active +1，last_action_id 写入"""
        self._seed_worker_with_started()
        # 先有一个 ActionProposed
        self.projector.apply_event(
            _mk_event(
                "evt_003",
                "ActionProposed",
                3,
                {"worker_id": "worker_001", "action_id": "action_001"},
            )
        )
        result = self.projector.apply_event(
            _mk_event(
                "evt_004",
                "ActionStarted",
                4,
                {"worker_id": "worker_001", "action_id": "action_001"},
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_worker_projection("worker_001")
        assert proj.waiting_action_count == 0
        assert proj.active_action_count == 1
        assert proj.last_action_id == "action_001"

    def test_action_completed_decrements_active(self):
        """ActionCompleted：active_action_count -1"""
        self._seed_worker_with_active_action()
        result = self.projector.apply_event(
            _mk_event(
                "evt_005",
                "ActionCompleted",
                5,
                {"worker_id": "worker_001", "action_id": "action_001"},
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_worker_projection("worker_001")
        assert proj.active_action_count == 0

    def test_action_failed_decrements_active_increments_failed(self):
        """ActionFailed：active -1，failed_action_count +1"""
        self._seed_worker_with_active_action()
        result = self.projector.apply_event(
            _mk_event(
                "evt_005",
                "ActionFailed",
                5,
                {"worker_id": "worker_001", "action_id": "action_001"},
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_worker_projection("worker_001")
        assert proj.active_action_count == 0
        assert proj.failed_action_count == 1

    def test_artifact_consumed_appends_to_input_ids(self):
        """ArtifactConsumed：artifact_id 加入 input_artifact_ids"""
        self._seed_worker()
        self.projector.apply_event(
            _mk_event(
                "evt_002",
                "ArtifactConsumed",
                2,
                {"worker_id": "worker_001", "artifact_id": "art_in_1"},
            )
        )
        self.projector.apply_event(
            _mk_event(
                "evt_003",
                "ArtifactConsumed",
                3,
                {"worker_id": "worker_001", "artifact_id": "art_in_2"},
            )
        )
        # 重复不应再添加
        self.projector.apply_event(
            _mk_event(
                "evt_004",
                "ArtifactConsumed",
                4,
                {"worker_id": "worker_001", "artifact_id": "art_in_1"},
            )
        )
        proj = self.storage.load_worker_projection("worker_001")
        assert proj.input_artifact_ids == ["art_in_1", "art_in_2"]

    def test_unknown_event_type_rejected(self):
        """未知事件类型：VERSION_MISMATCH"""
        self._seed_worker()
        result = self.projector.apply_event(
            _mk_event(
                "evt_002",
                "UnknownEvent",
                2,
                {"worker_id": "worker_001"},
            )
        )
        assert result.result == EventApplicationResult.VERSION_MISMATCH

    def test_event_without_existing_projection_rejected(self):
        """WorkerStarted 在无 WorkerCreated 的情况下：投影不存在"""
        result = self.projector.apply_event(
            _mk_event(
                "evt_001",
                "WorkerStarted",
                1,
                {"worker_id": "ghost", "started_at": datetime.now().isoformat()},
            )
        )
        assert result.result == EventApplicationResult.VERSION_MISMATCH

    def test_action_started_without_proposed_does_not_underflow(self):
        """ActionStarted 在 waiting=0 时不应变成负数"""
        self._seed_worker_with_started()
        # 直接 ActionStarted，没有 ActionProposed
        result = self.projector.apply_event(
            _mk_event(
                "evt_003",
                "ActionStarted",
                3,
                {"worker_id": "worker_001", "action_id": "action_001"},
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_worker_projection("worker_001")
        assert proj.waiting_action_count == 0  # 不为负
        assert proj.active_action_count == 1

    # --------- 工具方法 ---------
    def _seed_worker(self):
        self.projector.apply_event(
            _mk_event(
                "evt_001",
                "WorkerCreated",
                1,
                {
                    "worker_id": "worker_001",
                    "workflow_id": "wf_001",
                    "task_id": "task_001",
                    "step_id": "step_001",
                    "worker_type": "CODER",
                    "source_revision": "abc",
                    "created_at": datetime.now().isoformat(),
                },
            )
        )

    def _seed_worker_with_started(self):
        self._seed_worker()
        self.projector.apply_event(
            _mk_event(
                "evt_002",
                "WorkerStarted",
                2,
                {"worker_id": "worker_001", "started_at": datetime.now().isoformat()},
            )
        )

    def _seed_worker_with_active_action(self):
        self._seed_worker_with_started()
        self.projector.apply_event(
            _mk_event(
                "evt_003",
                "ActionProposed",
                3,
                {"worker_id": "worker_001", "action_id": "action_001"},
            )
        )
        self.projector.apply_event(
            _mk_event(
                "evt_004",
                "ActionStarted",
                4,
                {"worker_id": "worker_001", "action_id": "action_001"},
            )
        )


class TestWorkerProjectorInvariants:
    """WorkerProjector 状态不变量校验"""

    def setup_method(self):
        self.storage = InMemoryProjectionStorage()
        self.projector = WorkerProjector(self.storage)

    def test_state_machine_violation_negative_count(self):
        """计数字段为负：触发不变量校验失败（通过直接构造）"""
        import pydantic
        import pytest

        from src.runtime.projection.models import WorkerProjection

        # Pydantic 的 ge=0 会在构造时即抛 ValidationError
        with pytest.raises(pydantic.ValidationError):
            WorkerProjection(
                worker_id="w1",
                workflow_id="wf1",
                task_id="t1",
                step_id="s1",
                worker_type="CODER",
                attempt=1,
                source_revision="a",
                status="READY",
                last_event_id="e1",
                last_sequence=1,
                projection_version="v1",
                created_at=datetime.now(),
                updated_at=datetime.now(),
                active_action_count=-1,  # 非法
            )

    def test_state_invariants_completed_at_in_non_terminal(self):
        """完成时间只能存在于终态"""
        from src.runtime.projection.models import WorkerProjection

        proj = WorkerProjection(
            worker_id="w1",
            workflow_id="wf1",
            task_id="t1",
            step_id="s1",
            worker_type="CODER",
            attempt=1,
            source_revision="a",
            status="RUNNING",  # 非终态
            last_event_id="e1",
            last_sequence=1,
            projection_version="v1",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            completed_at=datetime.now(),
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid
        assert "completed_at" in msg

    def test_state_invariants_empty_worker_id_rejected(self):
        """空 worker_id：拒绝"""
        from src.runtime.projection.models import WorkerProjection

        proj = WorkerProjection(
            worker_id="",
            workflow_id="wf1",
            task_id="t1",
            step_id="s1",
            worker_type="CODER",
            attempt=1,
            source_revision="a",
            status="READY",
            last_event_id="e1",
            last_sequence=1,
            projection_version="v1",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid


class TestWorkerProjectorMetadata:
    def test_projection_name_and_version(self):
        storage = InMemoryProjectionStorage()
        projector = WorkerProjector(storage)
        assert projector.get_projection_name() == "worker_projection"
        assert projector.get_projection_version() == "v1.0.0"