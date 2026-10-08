"""
单元测试：src/runtime/entities/action.py

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.4（Action）
覆盖：冒烟（正常创建）、边界（target_resources 最小长度）、
异常（非法 ID/动态 revision/source_revision 必填规则/生命周期顺序）场景。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.runtime.common.types import (
    ResourceRef,
    ResourceType,
    generate_entity_id,
    generate_trace_id,
    utc_now,
)
from src.runtime.entities.action import Action, ActionStatus, ActionType
from src.runtime.entities.task import RiskLevel

_DEFAULT_RESOURCE = ResourceRef(
    resource_type=ResourceType.FILE,
    resource_id="src/app.py",
    scope="repo-123",
)


def _valid_action_kwargs(**overrides):
    now = utc_now()
    base = dict(
        action_id=generate_entity_id(),
        task_id=generate_entity_id(),
        workflow_id=generate_entity_id(),
        worker_id=generate_entity_id(),
        step_id="step-1",
        type=ActionType.READ,
        tool_name="file_read",
        tool_schema_version="1.0.0",
        target_resources=[_DEFAULT_RESOURCE],
        risk_level=RiskLevel.LOW,
        trace_id=generate_trace_id(),
        created_at=now,
        updated_at=now,
        proposed_at=now,
    )
    base.update(overrides)
    return base


class TestActionSmoke:
    def test_smoke_create_minimal_read_action(self):
        action = Action(**_valid_action_kwargs())
        assert action.schema_version == "runtime.action.v1"
        assert action.type == ActionType.READ
        assert action.source_revision is None
        assert action.requires_approval is False

    def test_smoke_action_is_frozen(self):
        action = Action(**_valid_action_kwargs())
        with pytest.raises(ValidationError):
            action.tool_name = "changed"

    def test_smoke_write_action_with_source_revision(self):
        action = Action(
            **_valid_action_kwargs(
                type=ActionType.WRITE,
                source_revision="git:abc123",
                risk_level=RiskLevel.MEDIUM,
            )
        )
        assert action.source_revision == "git:abc123"

    def test_smoke_all_action_type_values_accepted(self):
        for action_type in ActionType:
            kwargs = _valid_action_kwargs(type=action_type)
            if action_type in {ActionType.WRITE, ActionType.EXECUTE, ActionType.REPORT}:
                kwargs["source_revision"] = "git:abc123"
            action = Action(**kwargs)
            assert action.type == action_type

    def test_smoke_all_action_status_values_accepted(self):
        for status in ActionStatus:
            action = Action(**_valid_action_kwargs(status_projection=status))
            assert action.status_projection == status


class TestActionBoundary:
    def test_boundary_target_resources_minimum_one_accepted(self):
        action = Action(**_valid_action_kwargs(target_resources=[_DEFAULT_RESOURCE]))
        assert len(action.target_resources) == 1

    def test_boundary_target_resources_empty_rejected(self):
        """不变量5：target_resources 必须显式列出动作目标，不能用空数组表达"全部资源"。"""
        with pytest.raises(ValidationError):
            Action(**_valid_action_kwargs(target_resources=[]))

    def test_boundary_optional_fields_default_none(self):
        action = Action(**_valid_action_kwargs())
        assert action.policy_decision_id is None
        assert action.idempotency_key is None
        assert action.authorized_at is None
        assert action.started_at is None
        assert action.completed_at is None

    def test_boundary_started_at_equal_proposed_at_accepted(self):
        now = utc_now()
        action = Action(
            **_valid_action_kwargs(created_at=now, updated_at=now, proposed_at=now, started_at=now)
        )
        assert action.started_at == action.proposed_at

    def test_boundary_arguments_empty_dict_default(self):
        action = Action(**_valid_action_kwargs())
        assert action.arguments == {}


class TestActionException:
    def test_exception_missing_required_field_rejected(self):
        kwargs = _valid_action_kwargs()
        del kwargs["worker_id"]
        with pytest.raises(ValidationError):
            Action(**kwargs)

    def test_exception_invalid_action_id_rejected(self):
        with pytest.raises(ValidationError, match="action_id"):
            Action(**_valid_action_kwargs(action_id="not-a-uuid"))

    def test_exception_invalid_trace_id_rejected(self):
        with pytest.raises(ValidationError, match="trace_id"):
            Action(**_valid_action_kwargs(trace_id="not-hex"))

    def test_exception_invalid_policy_decision_id_rejected(self):
        with pytest.raises(ValidationError, match="policy_decision_id"):
            Action(**_valid_action_kwargs(policy_decision_id="not-a-uuid"))

    def test_exception_unknown_action_type_rejected(self):
        with pytest.raises(ValidationError):
            Action(**_valid_action_kwargs(type="UNKNOWN"))

    def test_exception_unknown_action_status_rejected(self):
        with pytest.raises(ValidationError):
            Action(**_valid_action_kwargs(status_projection="UNKNOWN"))

    @pytest.mark.parametrize("dynamic_ref", ["latest", "main", "HEAD", "master"])
    def test_exception_dynamic_source_revision_rejected(self, dynamic_ref):
        with pytest.raises(ValidationError, match="source_revision"):
            Action(
                **_valid_action_kwargs(
                    type=ActionType.WRITE,
                    source_revision=dynamic_ref,
                )
            )

    @pytest.mark.parametrize(
        "action_type", [ActionType.WRITE, ActionType.EXECUTE, ActionType.REPORT]
    )
    def test_exception_missing_source_revision_for_required_type_rejected(self, action_type):
        """不变量6：WRITE/EXECUTE/REPORT 类型必须存在 source_revision。"""
        with pytest.raises(ValidationError, match="source_revision"):
            Action(**_valid_action_kwargs(type=action_type, source_revision=None))

    def test_exception_started_before_proposed_rejected(self):
        now = utc_now()
        earlier = now - timedelta(hours=1)
        with pytest.raises(ValidationError, match="started_at"):
            Action(
                **_valid_action_kwargs(
                    created_at=now, updated_at=now, proposed_at=now, started_at=earlier
                )
            )

    def test_exception_completed_before_started_rejected(self):
        now = utc_now()
        later_started = now + timedelta(minutes=10)
        with pytest.raises(ValidationError, match="completed_at"):
            Action(
                **_valid_action_kwargs(
                    created_at=now,
                    updated_at=now,
                    proposed_at=now,
                    started_at=later_started,
                    completed_at=now,
                )
            )

    def test_exception_naive_datetime_rejected(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValidationError, match="时区"):
            Action(**_valid_action_kwargs(created_at=naive))

    def test_exception_invalid_target_resource_type_rejected(self):
        with pytest.raises(ValidationError):
            Action(**_valid_action_kwargs(target_resources=[{"resource_type": "UNKNOWN"}]))
