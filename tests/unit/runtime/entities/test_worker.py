"""
单元测试：src/runtime/entities/worker.py

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.3（Worker）
覆盖：冒烟（正常创建）、边界（attempt 边界/空列表）、异常（非法 ID/动态 revision/自引用）场景。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.runtime.common.types import (
    Budget,
    ResourceRef,
    ResourceType,
    generate_entity_id,
    generate_trace_id,
    utc_now,
)
from src.runtime.entities.worker import Worker, WorkerStatus, WorkerType


def _valid_worker_kwargs(**overrides):
    now = utc_now()
    base = dict(
        worker_id=generate_entity_id(),
        workflow_id=generate_entity_id(),
        task_id=generate_entity_id(),
        step_id="step-1",
        worker_type=WorkerType.CODER,
        attempt=1,
        agent_profile_id="default-agent-profile",
        agent_profile_version="1.0.0",
        toolset_id="default-toolset",
        toolset_version="1.0.0",
        source_revision="git:abc123",
        budget=Budget(),
        trace_id=generate_trace_id(),
        created_at=now,
        updated_at=now,
    )
    base.update(overrides)
    return base


class TestWorkerSmoke:
    def test_smoke_create_minimal_valid_worker(self):
        worker = Worker(**_valid_worker_kwargs())
        assert worker.schema_version == "runtime.worker.v1"
        assert worker.attempt == 1
        assert worker.status_projection is None

    def test_smoke_worker_is_frozen(self):
        worker = Worker(**_valid_worker_kwargs())
        with pytest.raises(ValidationError):
            worker.attempt = 2

    def test_smoke_all_worker_type_values_accepted(self):
        for worker_type in WorkerType:
            worker = Worker(**_valid_worker_kwargs(worker_type=worker_type))
            assert worker.worker_type == worker_type

    def test_smoke_all_worker_status_values_accepted(self):
        for status in WorkerStatus:
            worker = Worker(**_valid_worker_kwargs(status_projection=status))
            assert worker.status_projection == status

    def test_smoke_with_allowed_resources(self):
        resource = ResourceRef(
            resource_type=ResourceType.FILE,
            resource_id="src/app.py",
            scope="repo-123",
        )
        worker = Worker(**_valid_worker_kwargs(allowed_resources=[resource]))
        assert worker.allowed_resources[0].resource_type == ResourceType.FILE


class TestWorkerBoundary:
    def test_boundary_attempt_minimum_value_accepted(self):
        worker = Worker(**_valid_worker_kwargs(attempt=1))
        assert worker.attempt == 1

    def test_boundary_attempt_zero_rejected(self):
        with pytest.raises(ValidationError):
            Worker(**_valid_worker_kwargs(attempt=0))

    def test_boundary_attempt_negative_rejected(self):
        with pytest.raises(ValidationError):
            Worker(**_valid_worker_kwargs(attempt=-1))

    def test_boundary_empty_artifact_and_tool_lists_default(self):
        worker = Worker(**_valid_worker_kwargs())
        assert worker.input_artifact_ids == []
        assert worker.output_artifact_ids == []
        assert worker.allowed_tools == []
        assert worker.allowed_resources == []

    def test_boundary_optional_fields_default_none(self):
        worker = Worker(**_valid_worker_kwargs())
        assert worker.parent_worker_id is None
        assert worker.started_at is None
        assert worker.completed_at is None

    def test_boundary_valid_artifact_ids_accepted(self):
        artifact_id = generate_entity_id()
        worker = Worker(**_valid_worker_kwargs(input_artifact_ids=[artifact_id]))
        assert worker.input_artifact_ids == [artifact_id]

    def test_boundary_started_at_equal_created_at_accepted(self):
        now = utc_now()
        worker = Worker(**_valid_worker_kwargs(created_at=now, updated_at=now, started_at=now))
        assert worker.started_at == worker.created_at


class TestWorkerException:
    def test_exception_missing_required_field_rejected(self):
        kwargs = _valid_worker_kwargs()
        del kwargs["workflow_id"]
        with pytest.raises(ValidationError):
            Worker(**kwargs)

    def test_exception_invalid_worker_id_rejected(self):
        with pytest.raises(ValidationError, match="worker_id"):
            Worker(**_valid_worker_kwargs(worker_id="not-a-uuid"))

    def test_exception_invalid_trace_id_rejected(self):
        with pytest.raises(ValidationError, match="trace_id"):
            Worker(**_valid_worker_kwargs(trace_id="not-hex"))

    def test_exception_invalid_parent_worker_id_rejected(self):
        with pytest.raises(ValidationError, match="parent_worker_id"):
            Worker(**_valid_worker_kwargs(parent_worker_id="not-a-uuid"))

    def test_exception_invalid_artifact_id_in_list_rejected(self):
        with pytest.raises(ValidationError, match="input_artifact_ids"):
            Worker(**_valid_worker_kwargs(input_artifact_ids=["not-a-uuid"]))

    def test_exception_unknown_worker_type_rejected(self):
        with pytest.raises(ValidationError):
            Worker(**_valid_worker_kwargs(worker_type="UNKNOWN"))

    def test_exception_unknown_worker_status_rejected(self):
        with pytest.raises(ValidationError):
            Worker(**_valid_worker_kwargs(status_projection="UNKNOWN"))

    @pytest.mark.parametrize("dynamic_ref", ["latest", "main", "HEAD", "master"])
    def test_exception_dynamic_source_revision_rejected(self, dynamic_ref):
        with pytest.raises(ValidationError, match="source_revision"):
            Worker(**_valid_worker_kwargs(source_revision=dynamic_ref))

    def test_exception_started_before_created_rejected(self):
        now = utc_now()
        earlier = now - timedelta(hours=1)
        with pytest.raises(ValidationError, match="started_at"):
            Worker(**_valid_worker_kwargs(created_at=now, updated_at=now, started_at=earlier))

    def test_exception_completed_before_started_rejected(self):
        now = utc_now()
        later_started = now + timedelta(minutes=10)
        with pytest.raises(ValidationError, match="completed_at"):
            Worker(
                **_valid_worker_kwargs(
                    created_at=now,
                    updated_at=now,
                    started_at=later_started,
                    completed_at=now,
                )
            )

    def test_exception_naive_datetime_rejected(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValidationError, match="时区"):
            Worker(**_valid_worker_kwargs(created_at=naive))

    def test_exception_self_referencing_parent_worker_id_rejected(self):
        worker_id = generate_entity_id()
        with pytest.raises(ValidationError, match="parent_worker_id"):
            Worker(**_valid_worker_kwargs(worker_id=worker_id, parent_worker_id=worker_id))
