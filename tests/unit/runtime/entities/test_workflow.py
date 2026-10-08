"""
单元测试：src/runtime/entities/workflow.py

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.2（Workflow）
覆盖：冒烟（正常创建）、边界（可选字段默认值）、异常（非法 ID/动态 revision/自引用）场景。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.runtime.common.types import Budget, generate_entity_id, generate_trace_id, utc_now
from src.runtime.entities.workflow import Workflow, WorkflowStatus


def _valid_workflow_kwargs(**overrides):
    now = utc_now()
    base = dict(
        workflow_id=generate_entity_id(),
        task_id=generate_entity_id(),
        organization_id=generate_entity_id(),
        project_id=generate_entity_id(),
        repository_id=generate_entity_id(),
        workflow_template_id="github.issue-to-pr",
        workflow_template_version="1.0.0",
        agent_profile_id="default-agent-profile",
        agent_profile_version="1.0.0",
        toolset_id="default-toolset",
        toolset_version="1.0.0",
        base_revision="git:abc123",
        budget=Budget(),
        trace_id=generate_trace_id(),
        created_at=now,
        updated_at=now,
    )
    base.update(overrides)
    return base


class TestWorkflowSmoke:
    def test_smoke_create_minimal_valid_workflow(self):
        workflow = Workflow(**_valid_workflow_kwargs())
        assert workflow.schema_version == "runtime.workflow.v1"
        assert workflow.status_projection is None

    def test_smoke_workflow_is_frozen(self):
        workflow = Workflow(**_valid_workflow_kwargs())
        with pytest.raises(ValidationError):
            workflow.workflow_template_version = "2.0.0"

    def test_smoke_all_workflow_status_values_accepted(self):
        for status in WorkflowStatus:
            workflow = Workflow(**_valid_workflow_kwargs(status_projection=status))
            assert workflow.status_projection == status


class TestWorkflowBoundary:
    def test_boundary_optional_fields_default_none(self):
        workflow = Workflow(**_valid_workflow_kwargs())
        assert workflow.working_branch is None
        assert workflow.working_revision is None
        assert workflow.parent_workflow_id is None
        assert workflow.started_at is None
        assert workflow.completed_at is None

    def test_boundary_started_at_equal_created_at_accepted(self):
        now = utc_now()
        workflow = Workflow(
            **_valid_workflow_kwargs(created_at=now, updated_at=now, started_at=now)
        )
        assert workflow.started_at == workflow.created_at

    def test_boundary_valid_parent_workflow_id_accepted(self):
        parent_id = generate_entity_id()
        workflow = Workflow(**_valid_workflow_kwargs(parent_workflow_id=parent_id))
        assert workflow.parent_workflow_id == parent_id


class TestWorkflowException:
    def test_exception_missing_required_field_rejected(self):
        kwargs = _valid_workflow_kwargs()
        del kwargs["task_id"]
        with pytest.raises(ValidationError):
            Workflow(**kwargs)

    def test_exception_invalid_task_id_rejected(self):
        with pytest.raises(ValidationError, match="task_id"):
            Workflow(**_valid_workflow_kwargs(task_id="not-a-uuid"))

    def test_exception_invalid_trace_id_rejected(self):
        with pytest.raises(ValidationError, match="trace_id"):
            Workflow(**_valid_workflow_kwargs(trace_id="not-hex"))

    def test_exception_invalid_parent_workflow_id_rejected(self):
        with pytest.raises(ValidationError, match="parent_workflow_id"):
            Workflow(**_valid_workflow_kwargs(parent_workflow_id="not-a-uuid"))

    @pytest.mark.parametrize("dynamic_ref", ["latest", "main", "HEAD", "master"])
    def test_exception_dynamic_base_revision_rejected(self, dynamic_ref):
        with pytest.raises(ValidationError, match="base_revision"):
            Workflow(**_valid_workflow_kwargs(base_revision=dynamic_ref))

    def test_exception_unknown_workflow_status_rejected(self):
        with pytest.raises(ValidationError):
            Workflow(**_valid_workflow_kwargs(status_projection="UNKNOWN"))

    def test_exception_started_before_created_rejected(self):
        now = utc_now()
        earlier = now - timedelta(hours=1)
        with pytest.raises(ValidationError, match="started_at"):
            Workflow(**_valid_workflow_kwargs(created_at=now, updated_at=now, started_at=earlier))

    def test_exception_completed_before_started_rejected(self):
        now = utc_now()
        later_started = now + timedelta(minutes=10)
        with pytest.raises(ValidationError, match="completed_at"):
            Workflow(
                **_valid_workflow_kwargs(
                    created_at=now,
                    updated_at=now,
                    started_at=later_started,
                    completed_at=now,
                )
            )

    def test_exception_naive_datetime_rejected(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValidationError, match="时区"):
            Workflow(**_valid_workflow_kwargs(created_at=naive))

    def test_exception_self_referencing_parent_workflow_id_rejected(self):
        """禁止 parent_workflow_id 指向自身（MVP 默认禁止无限递归创建的最小防护）。"""
        workflow_id = generate_entity_id()
        with pytest.raises(ValidationError, match="parent_workflow_id"):
            Workflow(
                **_valid_workflow_kwargs(workflow_id=workflow_id, parent_workflow_id=workflow_id)
            )
