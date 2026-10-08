"""
单元测试：src/runtime/entities/artifact.py

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.5（Artifact）
覆盖：冒烟（正常创建）、边界（content_inline/content_ref 组合）、
异常（非法 ID/动态 revision/内容双空）场景。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.runtime.common.types import (
    ContentRef,
    DataSensitivity,
    generate_entity_id,
    generate_trace_id,
    utc_now,
)
from src.runtime.entities.artifact import Artifact, ArtifactType

_DEFAULT_CONTENT_REF = ContentRef(
    storage_provider="s3",
    object_key="artifacts/abc123.json",
    media_type="application/json",
    byte_size=1024,
    content_hash="sha256:abc",
)


def _valid_artifact_kwargs(**overrides):
    now = utc_now()
    base = dict(
        artifact_id=generate_entity_id(),
        task_id=generate_entity_id(),
        workflow_id=generate_entity_id(),
        producer_worker_id=generate_entity_id(),
        type=ArtifactType.CODE_CHANGES,
        content_schema="runtime.artifact.code_changes.v1",
        content_schema_version="1.0.0",
        source_revision="git:abc123",
        content_hash="sha256:abc",
        content_size_bytes=1024,
        content_inline={"files_changed": 2},
        sensitivity=DataSensitivity.INTERNAL,
        trace_id=generate_trace_id(),
        created_at=now,
    )
    base.update(overrides)
    return base


class TestArtifactSmoke:
    def test_smoke_create_minimal_valid_artifact_with_inline_content(self):
        artifact = Artifact(**_valid_artifact_kwargs())
        assert artifact.schema_version == "runtime.artifact.v1"
        assert artifact.content_inline == {"files_changed": 2}
        assert artifact.content_ref is None

    def test_smoke_create_artifact_with_content_ref(self):
        artifact = Artifact(
            **_valid_artifact_kwargs(content_inline=None, content_ref=_DEFAULT_CONTENT_REF)
        )
        assert artifact.content_ref.storage_provider == "s3"
        assert artifact.content_inline is None

    def test_smoke_artifact_is_frozen(self):
        """不变量1：Artifact 创建后不可原地修改。"""
        artifact = Artifact(**_valid_artifact_kwargs())
        with pytest.raises(ValidationError):
            artifact.content_hash = "sha256:changed"

    def test_smoke_all_artifact_type_values_accepted(self):
        for artifact_type in ArtifactType:
            artifact = Artifact(**_valid_artifact_kwargs(type=artifact_type))
            assert artifact.type == artifact_type

    def test_smoke_all_data_sensitivity_values_accepted(self):
        for sensitivity in DataSensitivity:
            artifact = Artifact(**_valid_artifact_kwargs(sensitivity=sensitivity))
            assert artifact.sensitivity == sensitivity


class TestArtifactBoundary:
    def test_boundary_content_size_zero_accepted(self):
        artifact = Artifact(**_valid_artifact_kwargs(content_size_bytes=0))
        assert artifact.content_size_bytes == 0

    def test_boundary_content_size_negative_rejected(self):
        with pytest.raises(ValidationError):
            Artifact(**_valid_artifact_kwargs(content_size_bytes=-1))

    def test_boundary_both_content_inline_and_ref_present_accepted(self):
        """不变量3只要求"至少有一个"，两者同时存在不违反该不变量。"""
        artifact = Artifact(
            **_valid_artifact_kwargs(
                content_inline={"summary": "ok"}, content_ref=_DEFAULT_CONTENT_REF
            )
        )
        assert artifact.content_inline is not None
        assert artifact.content_ref is not None

    def test_boundary_producer_action_id_optional_none(self):
        artifact = Artifact(**_valid_artifact_kwargs())
        assert artifact.producer_action_id is None

    def test_boundary_valid_producer_action_id_accepted(self):
        action_id = generate_entity_id()
        artifact = Artifact(**_valid_artifact_kwargs(producer_action_id=action_id))
        assert artifact.producer_action_id == action_id


class TestArtifactException:
    def test_exception_missing_required_field_rejected(self):
        kwargs = _valid_artifact_kwargs()
        del kwargs["producer_worker_id"]
        with pytest.raises(ValidationError):
            Artifact(**kwargs)

    def test_exception_invalid_artifact_id_rejected(self):
        with pytest.raises(ValidationError, match="artifact_id"):
            Artifact(**_valid_artifact_kwargs(artifact_id="not-a-uuid"))

    def test_exception_invalid_trace_id_rejected(self):
        with pytest.raises(ValidationError, match="trace_id"):
            Artifact(**_valid_artifact_kwargs(trace_id="not-hex"))

    def test_exception_invalid_producer_action_id_rejected(self):
        with pytest.raises(ValidationError, match="producer_action_id"):
            Artifact(**_valid_artifact_kwargs(producer_action_id="not-a-uuid"))

    def test_exception_unknown_artifact_type_rejected(self):
        with pytest.raises(ValidationError):
            Artifact(**_valid_artifact_kwargs(type="UNKNOWN"))

    def test_exception_unknown_sensitivity_rejected(self):
        with pytest.raises(ValidationError):
            Artifact(**_valid_artifact_kwargs(sensitivity="UNKNOWN"))

    @pytest.mark.parametrize("dynamic_ref", ["latest", "main", "HEAD", "master"])
    def test_exception_dynamic_source_revision_rejected(self, dynamic_ref):
        with pytest.raises(ValidationError, match="source_revision"):
            Artifact(**_valid_artifact_kwargs(source_revision=dynamic_ref))

    def test_exception_both_content_fields_empty_rejected(self):
        """不变量3：content_inline 与 content_ref 不能同时为空。"""
        with pytest.raises(ValidationError, match="content_inline"):
            Artifact(**_valid_artifact_kwargs(content_inline=None, content_ref=None))

    def test_exception_naive_datetime_rejected(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValidationError, match="时区"):
            Artifact(**_valid_artifact_kwargs(created_at=naive))

    def test_exception_empty_content_hash_rejected(self):
        with pytest.raises(ValidationError):
            Artifact(**_valid_artifact_kwargs(content_hash=""))
