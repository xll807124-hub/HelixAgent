"""
单元测试：src/runtime/entities/task.py

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.1（AgentTask）
覆盖：冒烟（正常创建）、边界（最大长度/空值）、异常（非法 ID/枚举/动态 revision）场景。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.runtime.common.types import Budget, generate_entity_id, generate_trace_id, utc_now
from src.runtime.entities.task import (
    AgentTask,
    RiskLevel,
    SourceReference,
    SourceType,
    TaskStatus,
)


def _valid_task_kwargs(**overrides):
    now = utc_now()
    base = dict(
        task_id=generate_entity_id(),
        organization_id=generate_entity_id(),
        project_id=generate_entity_id(),
        repository_id=generate_entity_id(),
        creator_id=generate_entity_id(),
        source_type=SourceType.ISSUE,
        title="修复登录权限校验",
        description="登录成功后应校验用户所属项目权限。",
        risk_level=RiskLevel.MEDIUM,
        workflow_template_id="github.issue-to-pr",
        workflow_template_version="1.0.0",
        base_revision="git:abc123",
        budget=Budget(),
        created_at=now,
        updated_at=now,
        trace_id=generate_trace_id(),
    )
    base.update(overrides)
    return base


class TestAgentTaskSmoke:
    def test_smoke_create_minimal_valid_task(self):
        task = AgentTask(**_valid_task_kwargs())
        assert task.schema_version == "runtime.task.v1"
        assert task.risk_level == RiskLevel.MEDIUM
        assert task.status_projection is None

    def test_smoke_create_with_source_reference(self):
        ref = SourceReference(
            source_type=SourceType.ISSUE,
            provider="github",
            external_id="issue-1842",
            snapshot_hash="sha256:abc",
        )
        task = AgentTask(**_valid_task_kwargs(source_reference=ref))
        assert task.source_reference.provider == "github"

    def test_smoke_task_is_frozen(self):
        task = AgentTask(**_valid_task_kwargs())
        with pytest.raises(ValidationError):
            task.title = "changed"


class TestAgentTaskBoundary:
    def test_boundary_title_max_length_accepted(self):
        task = AgentTask(**_valid_task_kwargs(title="a" * 200))
        assert len(task.title) == 200

    def test_boundary_title_exceeds_max_length_rejected(self):
        with pytest.raises(ValidationError):
            AgentTask(**_valid_task_kwargs(title="a" * 201))

    def test_boundary_title_empty_rejected(self):
        with pytest.raises(ValidationError):
            AgentTask(**_valid_task_kwargs(title=""))

    def test_boundary_description_max_length_accepted(self):
        task = AgentTask(**_valid_task_kwargs(description="d" * 20000))
        assert len(task.description) == 20000

    def test_boundary_description_exceeds_max_length_rejected(self):
        with pytest.raises(ValidationError):
            AgentTask(**_valid_task_kwargs(description="d" * 20001))

    def test_boundary_optional_fields_default_none(self):
        task = AgentTask(**_valid_task_kwargs())
        assert task.workflow_id is None
        assert task.working_branch is None
        assert task.started_at is None
        assert task.completed_at is None

    def test_boundary_started_at_equal_created_at_accepted(self):
        now = utc_now()
        task = AgentTask(**_valid_task_kwargs(created_at=now, updated_at=now, started_at=now))
        assert task.started_at == task.created_at


class TestAgentTaskException:
    def test_exception_missing_required_field_rejected(self):
        kwargs = _valid_task_kwargs()
        del kwargs["organization_id"]
        with pytest.raises(ValidationError):
            AgentTask(**kwargs)

    def test_exception_invalid_organization_id_rejected(self):
        with pytest.raises(ValidationError, match="organization_id"):
            AgentTask(**_valid_task_kwargs(organization_id="not-a-uuid"))

    def test_exception_invalid_trace_id_rejected(self):
        with pytest.raises(ValidationError, match="trace_id"):
            AgentTask(**_valid_task_kwargs(trace_id="not-hex"))

    def test_exception_unknown_source_type_rejected(self):
        with pytest.raises(ValidationError):
            AgentTask(**_valid_task_kwargs(source_type="UNKNOWN"))

    def test_exception_unknown_risk_level_rejected(self):
        with pytest.raises(ValidationError):
            AgentTask(**_valid_task_kwargs(risk_level="UNKNOWN"))

    @pytest.mark.parametrize("dynamic_ref", ["latest", "main", "HEAD", "master"])
    def test_exception_dynamic_base_revision_rejected(self, dynamic_ref):
        """Task 不变量4：base_revision 不能用动态字符串替代具体 commit SHA。"""
        with pytest.raises(ValidationError, match="base_revision"):
            AgentTask(**_valid_task_kwargs(base_revision=dynamic_ref))

    def test_exception_invalid_workflow_id_rejected(self):
        with pytest.raises(ValidationError, match="workflow_id"):
            AgentTask(**_valid_task_kwargs(workflow_id="not-a-uuid"))

    def test_exception_started_before_created_rejected(self):
        now = utc_now()
        earlier = now - timedelta(hours=1)
        with pytest.raises(ValidationError, match="started_at"):
            AgentTask(**_valid_task_kwargs(created_at=now, updated_at=now, started_at=earlier))

    def test_exception_completed_before_started_rejected(self):
        now = utc_now()
        later_started = now + timedelta(minutes=10)
        earlier_completed = now
        with pytest.raises(ValidationError, match="completed_at"):
            AgentTask(
                **_valid_task_kwargs(
                    created_at=now,
                    updated_at=now,
                    started_at=later_started,
                    completed_at=earlier_completed,
                )
            )

    def test_exception_naive_datetime_rejected(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValidationError, match="时区"):
            AgentTask(**_valid_task_kwargs(created_at=naive))

    def test_exception_unknown_task_status_rejected(self):
        with pytest.raises(ValidationError):
            AgentTask(**_valid_task_kwargs(status_projection="UNKNOWN"))

    def test_smoke_all_task_status_values_accepted(self):
        for status in TaskStatus:
            task = AgentTask(**_valid_task_kwargs(status_projection=status))
            assert task.status_projection == status
