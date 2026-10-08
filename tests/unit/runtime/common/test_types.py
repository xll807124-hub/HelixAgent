"""
单元测试：src/runtime/common/types.py

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §4
覆盖：冒烟（正常生成/校验）、边界（空值/非法格式）、异常（类型错误）场景。
"""
from __future__ import annotations

from datetime import UTC, datetime, timezone

import pytest
from pydantic import ValidationError

from src.runtime.common.types import (
    ActorRef,
    ActorType,
    Budget,
    ContentRef,
    DataSensitivity,
    ResourceRef,
    ResourceType,
    RevisionRef,
    SafeMetadata,
    ensure_utc,
    generate_entity_id,
    generate_trace_id,
    is_valid_entity_id,
    is_valid_span_id,
    is_valid_trace_id,
    utc_now,
)


class TestGenerateEntityId:
    """冒烟 + 边界：EntityId 生成与校验。"""

    def test_smoke_generated_id_is_valid_uuid(self):
        entity_id = generate_entity_id()
        assert is_valid_entity_id(entity_id)

    def test_smoke_generated_ids_are_unique(self):
        ids = {generate_entity_id() for _ in range(100)}
        assert len(ids) == 100

    def test_generated_id_has_uuid_version_7(self):
        entity_id = generate_entity_id()
        # RFC 9562: version 字段位于 UUID 第 13 个十六进制字符
        assert entity_id[14] == "7"

    @pytest.mark.parametrize(
        "value",
        ["", "not-a-uuid", "12345", None, 12345, "0198b2d2-6a6e-7c12-9c6b"],
    )
    def test_boundary_invalid_ids_rejected(self, value):
        assert is_valid_entity_id(value) is False

    def test_boundary_valid_uuid4_also_accepted(self):
        """is_valid_entity_id 只校验 UUID 格式，不强制 version=7（兼容旧数据/第三方 ID）。"""
        assert is_valid_entity_id("550e8400-e29b-41d4-a716-446655440000") is True


class TestTraceAndSpanId:
    """冒烟 + 边界：TraceId/SpanId 格式校验（REQ-RT-001 §4.1）。"""

    def test_smoke_generated_trace_id_is_valid(self):
        trace_id = generate_trace_id()
        assert is_valid_trace_id(trace_id)
        assert len(trace_id) == 32

    @pytest.mark.parametrize(
        "value",
        ["", "A" * 32, "f" * 31, "f" * 33, "zz" * 16, None],
    )
    def test_boundary_invalid_trace_id_rejected(self, value):
        assert is_valid_trace_id(value) is False

    @pytest.mark.parametrize(
        "value",
        ["", "a" * 15, "a" * 17, "G" * 16, None],
    )
    def test_boundary_invalid_span_id_rejected(self, value):
        assert is_valid_span_id(value) is False

    def test_smoke_valid_span_id_accepted(self):
        assert is_valid_span_id("00f067aa0ba902b7") is True


class TestEnsureUtc:
    """异常：时间字段必须带时区（REQ-RT-001 §4.3）。"""

    def test_smoke_utc_now_has_tzinfo(self):
        now = utc_now()
        assert now.tzinfo is not None

    def test_exception_naive_datetime_rejected(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="必须带时区"):
            ensure_utc(naive)

    def test_boundary_non_utc_timezone_normalized_to_utc(self):
        from datetime import timedelta

        plus8 = timezone(timedelta(hours=8))
        dt = datetime(2026, 1, 1, 20, 0, 0, tzinfo=plus8)
        normalized = ensure_utc(dt)
        assert normalized.tzinfo == UTC
        assert normalized.hour == 12  # 20:00+08:00 == 12:00 UTC


class TestActorRef:
    """冒烟 + 异常：ActorRef 模型校验。"""

    def test_smoke_valid_actor_ref(self):
        actor = ActorRef(actor_type=ActorType.USER, actor_id="user-123")
        assert actor.actor_type == ActorType.USER
        assert actor.actor_id == "user-123"

    def test_exception_blank_actor_id_rejected(self):
        with pytest.raises(ValidationError, match="actor_id 不能为空白字符串"):
            ActorRef(actor_type=ActorType.USER, actor_id="   ")

    def test_exception_empty_actor_id_rejected(self):
        with pytest.raises(ValidationError):
            ActorRef(actor_type=ActorType.USER, actor_id="")

    def test_exception_unknown_actor_type_rejected(self):
        with pytest.raises(ValidationError):
            ActorRef(actor_type="UNKNOWN_TYPE", actor_id="user-123")

    def test_boundary_actor_id_max_length(self):
        """REQ-RT-001 §7.1：自由文本字段必须有最大长度。"""
        with pytest.raises(ValidationError):
            ActorRef(actor_type=ActorType.USER, actor_id="a" * 201)

    def test_frozen_actor_ref_is_immutable(self):
        actor = ActorRef(actor_type=ActorType.USER, actor_id="user-123")
        with pytest.raises(ValidationError):
            actor.actor_id = "changed"


class TestBudget:
    """冒烟 + 边界：Budget 非负约束（REQ-RT-001 §4.4）。"""

    def test_smoke_default_budget_all_zero(self):
        budget = Budget()
        assert budget.max_input_tokens == 0
        assert budget.max_tool_calls == 0

    def test_smoke_explicit_budget(self):
        budget = Budget(
            max_input_tokens=50000,
            max_output_tokens=20000,
            max_total_tokens=70000,
            max_cost_microusd=5_000_000,
            max_duration_seconds=3600,
            max_tool_calls=200,
        )
        assert budget.max_total_tokens == 70000

    @pytest.mark.parametrize(
        "field",
        [
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "max_cost_microusd",
            "max_duration_seconds",
            "max_tool_calls",
        ],
    )
    def test_exception_negative_budget_field_rejected(self, field):
        with pytest.raises(ValidationError):
            Budget(**{field: -1})

    def test_boundary_zero_budget_is_valid(self):
        """0 是合法边界值（表示未授予该维度预算），不应被拒绝。"""
        budget = Budget(max_input_tokens=0)
        assert budget.max_input_tokens == 0


class TestDataSensitivity:
    def test_smoke_all_levels_present(self):
        assert {m.value for m in DataSensitivity} == {
            "PUBLIC",
            "INTERNAL",
            "CONFIDENTIAL",
            "RESTRICTED",
        }


class TestResourceRef:
    """冒烟 + 边界 + 异常：ResourceRef 模型校验（REQ-RT-001 §4.5）。"""

    def test_smoke_valid_resource_ref(self):
        ref = ResourceRef(
            resource_type=ResourceType.FILE,
            resource_id="src/app.py",
            scope="repo-123",
        )
        assert ref.resource_type == ResourceType.FILE
        assert ref.locator is None
        assert ref.revision is None

    def test_smoke_resource_ref_with_locator_and_revision(self):
        ref = ResourceRef(
            resource_type=ResourceType.REPOSITORY,
            resource_id="repo-123",
            scope="org-1",
            locator="https://github.com/org/repo",
            revision="git:abc123",
        )
        assert ref.locator == "https://github.com/org/repo"
        assert ref.revision == "git:abc123"

    def test_smoke_all_resource_type_values_accepted(self):
        for resource_type in ResourceType:
            ref = ResourceRef(resource_type=resource_type, resource_id="x", scope="y")
            assert ref.resource_type == resource_type

    def test_exception_unknown_resource_type_rejected(self):
        with pytest.raises(ValidationError):
            ResourceRef(resource_type="UNKNOWN", resource_id="x", scope="y")

    def test_exception_empty_resource_id_rejected(self):
        with pytest.raises(ValidationError):
            ResourceRef(resource_type=ResourceType.FILE, resource_id="", scope="y")

    def test_exception_empty_scope_rejected(self):
        with pytest.raises(ValidationError):
            ResourceRef(resource_type=ResourceType.FILE, resource_id="x", scope="")

    def test_frozen_resource_ref_is_immutable(self):
        ref = ResourceRef(resource_type=ResourceType.FILE, resource_id="x", scope="y")
        with pytest.raises(ValidationError):
            ref.resource_id = "changed"


class TestRevisionRef:
    """冒烟 + 异常：RevisionRef 模型校验（代码版本表达，REQ-RT-001 §14 决策3）。"""

    def test_smoke_valid_revision_ref(self):
        now = utc_now()
        ref = RevisionRef(
            repository_id="repo-123",
            commit_sha="abc123def456",
            branch="feature/login-fix",
            captured_at=now,
        )
        assert ref.commit_sha == "abc123def456"
        assert ref.captured_at.tzinfo is not None

    def test_smoke_branch_optional_none(self):
        ref = RevisionRef(repository_id="repo-123", commit_sha="abc123", captured_at=utc_now())
        assert ref.branch is None

    @pytest.mark.parametrize("dynamic_ref", ["latest", "main", "HEAD", "head", "master"])
    def test_exception_dynamic_commit_sha_rejected(self, dynamic_ref):
        """REQ-RT-001 §7.3：source_revision 不能使用动态引用替代具体 commit SHA。"""
        with pytest.raises(ValidationError, match="commit_sha"):
            RevisionRef(repository_id="repo-123", commit_sha=dynamic_ref, captured_at=utc_now())

    def test_exception_naive_captured_at_rejected(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValidationError, match="时区"):
            RevisionRef(repository_id="repo-123", commit_sha="abc123", captured_at=naive)

    def test_exception_empty_commit_sha_rejected(self):
        with pytest.raises(ValidationError):
            RevisionRef(repository_id="repo-123", commit_sha="", captured_at=utc_now())


class TestContentRef:
    """冒烟 + 边界：ContentRef 模型校验（REQ-RT-001 §5.5）。"""

    def test_smoke_valid_content_ref(self):
        ref = ContentRef(
            storage_provider="s3",
            object_key="artifacts/abc123.json",
            media_type="application/json",
            byte_size=1024,
            content_hash="sha256:abc",
        )
        assert ref.byte_size == 1024
        assert ref.encryption_key_ref is None

    def test_boundary_byte_size_zero_accepted(self):
        ref = ContentRef(
            storage_provider="s3",
            object_key="k",
            media_type="text/plain",
            byte_size=0,
            content_hash="sha256:abc",
        )
        assert ref.byte_size == 0

    def test_exception_byte_size_negative_rejected(self):
        with pytest.raises(ValidationError):
            ContentRef(
                storage_provider="s3",
                object_key="k",
                media_type="text/plain",
                byte_size=-1,
                content_hash="sha256:abc",
            )

    def test_exception_empty_object_key_rejected(self):
        with pytest.raises(ValidationError):
            ContentRef(
                storage_provider="s3",
                object_key="",
                media_type="text/plain",
                byte_size=0,
                content_hash="sha256:abc",
            )


class TestSafeMetadata:
    """冒烟 + 异常：SafeMetadata 敏感键名拦截（REQ-RT-001 §7.2）。"""

    def test_smoke_empty_metadata_accepted(self):
        metadata = SafeMetadata()
        assert metadata.model_extra == {}

    def test_smoke_allowed_extension_fields_accepted(self):
        metadata = SafeMetadata(labels=["bug", "auth"], data_classification="CONFIDENTIAL")
        assert metadata.model_extra["labels"] == ["bug", "auth"]

    @pytest.mark.parametrize(
        "forbidden_key",
        [
            "api_key",
            "access_token",
            "refresh_token",
            "private_key",
            "password",
            "secret",
            "git_token",
            "oauth_token",
            "API_KEY",  # 大小写不敏感
        ],
    )
    def test_exception_forbidden_key_rejected(self, forbidden_key):
        with pytest.raises(ValidationError, match="命中禁止的敏感字段键名"):
            SafeMetadata(**{forbidden_key: "value"})

    def test_exception_nested_key_name_not_scanned_at_top_level_only(self):
        """SafeMetadata 只扫描顶层键名；本测试确认顶层非敏感键可以正常通过。"""
        metadata = SafeMetadata(labels=["ok"])
        assert metadata.model_extra["labels"] == ["ok"]

    def test_frozen_safe_metadata_is_immutable(self):
        metadata = SafeMetadata(labels=["bug"])
        with pytest.raises(ValidationError):
            metadata.labels = ["changed"]
