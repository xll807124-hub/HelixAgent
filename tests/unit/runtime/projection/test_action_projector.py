"""
ActionProjector 单元测试（REQ-RT-004 §5.5）

补齐覆盖率：ActionProjector 原覆盖率 23%，目标 ≥ 90%。
"""

from datetime import datetime

from src.runtime.projection.action_projector import ActionProjector
from src.runtime.projection.in_memory_storage import InMemoryProjectionStorage
from src.runtime.projection.projector import EventApplicationResult


def _mk_event(
    event_id: str,
    event_type: str,
    sequence: int,
    payload: dict,
    partition_key: str = "workflow:wf_action_test",
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


class TestActionProjectorBasic:
    """ActionProjector 基础事件应用"""

    def setup_method(self):
        self.storage = InMemoryProjectionStorage()
        self.projector = ActionProjector(self.storage)

    def test_action_proposed_initial(self):
        """ActionProposed：创建初始投影，状态=PROPOSED"""
        event = _mk_event(
            "evt_001",
            "ActionProposed",
            1,
            {
                "action_id": "action_001",
                "task_id": "task_001",
                "workflow_id": "wf_001",
                "worker_id": "worker_001",
                "step_id": "step_001",
                "attempt": 1,
                "type": "TOOL_CALL",
                "tool_name": "file_read",
                "tool_schema_version": "v1",
                "target_resource_hash": "abc123",
                "source_revision": "def456",
                "risk_level": "LOW",
                "proposed_at": datetime.now().isoformat(),
            },
        )
        result = self.projector.apply_event(event)
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_action_projection("action_001")
        assert proj is not None
        assert proj.status == "PROPOSED"
        assert proj.risk_level == "LOW"
        assert proj.attempt == 1

    def test_action_approved(self):
        """ActionApproved：状态=APPROVED，approval_id 写入"""
        self._seed_action()
        result = self.projector.apply_event(
            _mk_event(
                "evt_002",
                "ActionApproved",
                2,
                {"action_id": "action_001", "approval_id": "appr_001"},
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_action_projection("action_001")
        assert proj.status == "APPROVED"
        assert proj.approval_id == "appr_001"

    def test_action_started(self):
        """ActionStarted：状态=EXECUTING，记录 started_at"""
        self._seed_action()
        result = self.projector.apply_event(
            _mk_event(
                "evt_002",
                "ActionStarted",
                2,
                {"action_id": "action_001", "started_at": datetime.now().isoformat()},
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_action_projection("action_001")
        assert proj.status == "EXECUTING"
        assert proj.started_at is not None

    def test_action_completed(self):
        """ActionCompleted：状态=COMPLETED，记录 observation_artifact_id"""
        self._seed_action_with_started()
        result = self.projector.apply_event(
            _mk_event(
                "evt_003",
                "ActionCompleted",
                3,
                {
                    "action_id": "action_001",
                    "completed_at": datetime.now().isoformat(),
                    "observation_artifact_id": "art_001",
                },
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_action_projection("action_001")
        assert proj.status == "COMPLETED"
        assert proj.observation_artifact_id == "art_001"

    def test_action_failed(self):
        """ActionFailed：状态=FAILED，记录 failure_ref 与 completed_at"""
        self._seed_action_with_started()
        result = self.projector.apply_event(
            _mk_event(
                "evt_003",
                "ActionFailed",
                3,
                {
                    "action_id": "action_001",
                    "failed_at": datetime.now().isoformat(),
                    "failure_ref": "fail_001",
                },
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_action_projection("action_001")
        assert proj.status == "FAILED"
        assert proj.failure_ref == "fail_001"
        assert proj.completed_at is not None

    def test_policy_decision_made_no_approval(self):
        """PolicyDecisionMade（不需审批）：写入 decision_id，状态不变"""
        self._seed_action()
        result = self.projector.apply_event(
            _mk_event(
                "evt_002",
                "PolicyDecisionMade",
                2,
                {
                    "action_id": "action_001",
                    "decision_id": "dec_001",
                    "requires_approval": False,
                },
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_action_projection("action_001")
        assert proj.policy_decision_id == "dec_001"
        assert proj.status == "PROPOSED"  # 无需审批时状态保持 PROPOSED

    def test_policy_decision_made_requires_approval(self):
        """PolicyDecisionMade（需审批）：状态变为 WAITING_APPROVAL"""
        self._seed_action()
        result = self.projector.apply_event(
            _mk_event(
                "evt_002",
                "PolicyDecisionMade",
                2,
                {
                    "action_id": "action_001",
                    "decision_id": "dec_002",
                    "requires_approval": True,
                },
            )
        )
        assert result.result == EventApplicationResult.APPLIED
        proj = self.storage.load_action_projection("action_001")
        assert proj.status == "WAITING_APPROVAL"

    def test_unknown_event_type_rejected(self):
        """未知事件类型：抛 ValueError（被 projector 捕获为 VERSION_MISMATCH）"""
        self._seed_action()
        result = self.projector.apply_event(
            _mk_event(
                "evt_002",
                "UnknownEvent",
                2,
                {"action_id": "action_001"},
            )
        )
        assert result.result == EventApplicationResult.VERSION_MISMATCH

    def test_event_without_existing_projection_rejected(self):
        """ActionStarted 在无 ActionProposed 的情况下：投影不存在"""
        result = self.projector.apply_event(
            _mk_event(
                "evt_001",
                "ActionStarted",
                1,
                {"action_id": "ghost", "started_at": datetime.now().isoformat()},
            )
        )
        assert result.result == EventApplicationResult.VERSION_MISMATCH

    # --------- 工具方法 ---------
    def _seed_action(self):
        """应用 ActionProposed 创建初始投影"""
        self.projector.apply_event(
            _mk_event(
                "evt_001",
                "ActionProposed",
                1,
                {
                    "action_id": "action_001",
                    "task_id": "task_001",
                    "workflow_id": "wf_001",
                    "worker_id": "worker_001",
                    "step_id": "step_001",
                    "type": "TOOL_CALL",
                    "tool_name": "file_read",
                    "tool_schema_version": "v1",
                    "target_resource_hash": "abc",
                    "source_revision": "def",
                    "risk_level": "LOW",
                    "proposed_at": datetime.now().isoformat(),
                },
            )
        )

    def _seed_action_with_started(self):
        """应用 ActionProposed → ActionStarted"""
        self._seed_action()
        self.projector.apply_event(
            _mk_event(
                "evt_002",
                "ActionStarted",
                2,
                {"action_id": "action_001", "started_at": datetime.now().isoformat()},
            )
        )


class TestActionProjectorInvariants:
    """ActionProjector 状态不变量校验"""

    def setup_method(self):
        self.storage = InMemoryProjectionStorage()
        self.projector = ActionProjector(self.storage)

    def test_state_machine_violation_invalid_risk_level(self):
        """无效 risk_level：触发 STATE_MACHINE_VIOLATION"""
        # Pydantic ActionProjection.risk_level 字段是 str，会接受 "INVALID"
        # 然后 _validate_state_invariants 触发 STATE_MACHINE_VIOLATION
        event = _mk_event(
            "evt_001",
            "ActionProposed",
            1,
            {
                "action_id": "action_001",
                "task_id": "task_001",
                "workflow_id": "wf_001",
                "worker_id": "worker_001",
                "step_id": "step_001",
                "type": "TOOL_CALL",
                "tool_name": "f",
                "tool_schema_version": "v1",
                "target_resource_hash": "a",
                "source_revision": "b",
                "risk_level": "INVALID_LEVEL",  # 故意写非法值
                "proposed_at": datetime.now().isoformat(),
            },
        )
        result = self.projector.apply_event(event)
        assert result.result == EventApplicationResult.STATE_MACHINE_VIOLATION
        assert "风险级别" in result.message or "INVALID" in result.message

    def test_state_invariants_completed_at_in_non_terminal(self):
        """完成时间只能存在于终态：通过直接构造 + 测试不变量校验"""
        from src.runtime.projection.models import ActionProjection

        proj = ActionProjection(
            action_id="a1",
            task_id="t1",
            workflow_id="w1",
            worker_id="wk1",
            step_id="s1",
            attempt=1,
            type="TOOL_CALL",
            tool_name="f",
            tool_schema_version="v1",
            target_resource_hash="a",
            source_revision="b",
            risk_level="LOW",
            status="RUNNING",  # 非终态
            last_event_id="e1",
            last_sequence=1,
            projection_version="v1",
            proposed_at=datetime.now(),
            updated_at=datetime.now(),
            completed_at=datetime.now(),  # 但有完成时间
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid
        assert "completed_at" in msg

    def test_state_invariants_started_after_completed(self):
        """started_at > completed_at 视为非法"""
        from src.runtime.projection.models import ActionProjection

        later = datetime.now()
        earlier = datetime(2020, 1, 1)
        proj = ActionProjection(
            action_id="a1",
            task_id="t1",
            workflow_id="w1",
            worker_id="wk1",
            step_id="s1",
            attempt=1,
            type="TOOL_CALL",
            tool_name="f",
            tool_schema_version="v1",
            target_resource_hash="a",
            source_revision="b",
            risk_level="LOW",
            status="COMPLETED",
            last_event_id="e1",
            last_sequence=1,
            projection_version="v1",
            proposed_at=earlier,
            updated_at=later,
            started_at=later,  # 晚于 completed_at
            completed_at=earlier,
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid
        assert "started_at" in msg

    def test_state_invariants_attempt_zero_rejected(self):
        """attempt < 1 应被拒绝"""
        import pydantic
        import pytest

        from src.runtime.projection.models import ActionProjection

        # Pydantic 的 attempt=0 会在创建时就抛 ValidationError（ge=1）
        with pytest.raises(pydantic.ValidationError):
            ActionProjection(
                action_id="a1",
                task_id="t1",
                workflow_id="w1",
                worker_id="wk1",
                step_id="s1",
                attempt=0,  # 非法
                type="TOOL_CALL",
                tool_name="f",
                tool_schema_version="v1",
                target_resource_hash="a",
                source_revision="b",
                risk_level="LOW",
                status="PROPOSED",
                last_event_id="e1",
                last_sequence=1,
                projection_version="v1",
                proposed_at=datetime.now(),
                updated_at=datetime.now(),
            )

    def test_state_invariants_empty_action_id_rejected(self):
        """空 action_id 应被拒绝（不变量层）"""
        from src.runtime.projection.models import ActionProjection

        # Pydantic 不会拦空字符串（str 字段无 min_length），所以测试不变量层。
        proj = ActionProjection(
            action_id="",
            task_id="t1",
            workflow_id="w1",
            worker_id="wk1",
            step_id="s1",
            attempt=1,
            type="TOOL_CALL",
            tool_name="f",
            tool_schema_version="v1",
            target_resource_hash="a",
            source_revision="b",
            risk_level="LOW",
            status="PROPOSED",
            last_event_id="e1",
            last_sequence=1,
            projection_version="v1",
            proposed_at=datetime.now(),
            updated_at=datetime.now(),
        )
        is_valid, msg = self.projector._validate_state_invariants(proj)
        assert not is_valid
        assert msg != "OK"


class TestActionProjectorProjectionNameVersion:
    """ActionProjector 元数据"""

    def test_projection_name_and_version(self):
        storage = InMemoryProjectionStorage()
        projector = ActionProjector(storage)
        assert projector.get_projection_name() == "action_projection"
        assert projector.get_projection_version() == "v1.0.0"
        assert projector.PROJECTION_NAME == "action_projection"
        assert projector.PROJECTION_VERSION == "v1.0.0"