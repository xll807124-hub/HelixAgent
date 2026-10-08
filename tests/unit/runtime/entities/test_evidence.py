"""
单元测试：src/runtime/entities/evidence.py

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.6（Evidence）
覆盖：冒烟（正常创建）、边界（content_inline/content_ref 组合、expires_at 可选）、
异常（非法 ID/动态 revision/内容双空/时间顺序/类型-结果矛盾）场景。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.runtime.common.types import (
    ContentRef,
    generate_entity_id,
    generate_trace_id,
    utc_now,
)
from src.runtime.entities.evidence import (
    Evidence,
    EvidenceResult,
    EvidenceSource,
    EvidenceType,
    VerificationMethod,
    VerifierType,
)

_DEFAULT_CONTENT_REF = ContentRef(
    storage_provider="s3",
    object_key="evidence/abc123.json",
    media_type="application/json",
    byte_size=512,
    content_hash="sha256:def",
)


def _valid_evidence_kwargs(**overrides):
    now = utc_now()
    base = dict(
        evidence_id=generate_entity_id(),
        task_id=generate_entity_id(),
        workflow_id=generate_entity_id(),
        type=EvidenceType.TEST_PASSED,
        source=EvidenceSource.TOOL,
        source_revision="git:abc123",
        verification_method=VerificationMethod.DETERMINISTIC_CHECK,
        verifier_type=VerifierType.SYSTEM,
        verifier_id="pytest-runner",
        result=EvidenceResult.PASSED,
        content_schema="runtime.evidence.test_results.v1",
        content_schema_version="1.0.0",
        content_hash="sha256:def",
        content_inline={"passed": 42, "failed": 0},
        trace_id=generate_trace_id(),
        created_at=now,
        verified_at=now,
    )
    base.update(overrides)
    return base


class TestEvidenceSmoke:
    def test_smoke_create_minimal_valid_evidence_with_inline_content(self):
        evidence = Evidence(**_valid_evidence_kwargs())
        assert evidence.schema_version == "runtime.evidence.v1"
        assert evidence.result == EvidenceResult.PASSED
        assert evidence.content_ref is None

    def test_smoke_create_evidence_with_content_ref(self):
        evidence = Evidence(
            **_valid_evidence_kwargs(content_inline=None, content_ref=_DEFAULT_CONTENT_REF)
        )
        assert evidence.content_ref.storage_provider == "s3"
        assert evidence.content_inline is None

    def test_smoke_evidence_is_frozen(self):
        """不变量7：Evidence 创建后不可覆盖。"""
        evidence = Evidence(**_valid_evidence_kwargs())
        with pytest.raises(ValidationError):
            evidence.result = EvidenceResult.FAILED

    def test_smoke_all_evidence_type_values_accepted(self):
        for evidence_type in EvidenceType:
            kwargs = _valid_evidence_kwargs(type=evidence_type)
            if evidence_type == EvidenceType.TEST_FAILED:
                kwargs["result"] = EvidenceResult.FAILED
            evidence = Evidence(**kwargs)
            assert evidence.type == evidence_type

    def test_smoke_all_evidence_source_values_accepted(self):
        for source in EvidenceSource:
            evidence = Evidence(**_valid_evidence_kwargs(source=source))
            assert evidence.source == source

    def test_smoke_all_verification_method_values_accepted(self):
        for method in VerificationMethod:
            evidence = Evidence(**_valid_evidence_kwargs(verification_method=method))
            assert evidence.verification_method == method

    def test_smoke_all_verifier_type_values_accepted(self):
        for verifier_type in VerifierType:
            evidence = Evidence(**_valid_evidence_kwargs(verifier_type=verifier_type))
            assert evidence.verifier_type == verifier_type

    def test_smoke_all_evidence_result_values_accepted(self):
        for result in EvidenceResult:
            evidence = Evidence(**_valid_evidence_kwargs(result=result))
            assert evidence.result == result


class TestEvidenceBoundary:
    def test_boundary_expires_at_optional_none(self):
        evidence = Evidence(**_valid_evidence_kwargs())
        assert evidence.expires_at is None

    def test_boundary_expires_at_equal_verified_at_accepted(self):
        now = utc_now()
        evidence = Evidence(
            **_valid_evidence_kwargs(created_at=now, verified_at=now, expires_at=now)
        )
        assert evidence.expires_at == evidence.verified_at

    def test_boundary_verified_at_equal_created_at_accepted(self):
        now = utc_now()
        evidence = Evidence(**_valid_evidence_kwargs(created_at=now, verified_at=now))
        assert evidence.verified_at == evidence.created_at

    def test_boundary_both_content_inline_and_ref_present_accepted(self):
        evidence = Evidence(
            **_valid_evidence_kwargs(
                content_inline={"summary": "ok"}, content_ref=_DEFAULT_CONTENT_REF
            )
        )
        assert evidence.content_inline is not None
        assert evidence.content_ref is not None

    def test_boundary_optional_reference_fields_default_none(self):
        evidence = Evidence(**_valid_evidence_kwargs())
        assert evidence.producer_worker_id is None
        assert evidence.source_action_id is None
        assert evidence.artifact_id is None

    def test_boundary_valid_artifact_id_accepted(self):
        artifact_id = generate_entity_id()
        evidence = Evidence(**_valid_evidence_kwargs(artifact_id=artifact_id))
        assert evidence.artifact_id == artifact_id


class TestEvidenceException:
    def test_exception_missing_required_field_rejected(self):
        kwargs = _valid_evidence_kwargs()
        del kwargs["workflow_id"]
        with pytest.raises(ValidationError):
            Evidence(**kwargs)

    def test_exception_invalid_evidence_id_rejected(self):
        with pytest.raises(ValidationError, match="evidence_id"):
            Evidence(**_valid_evidence_kwargs(evidence_id="not-a-uuid"))

    def test_exception_invalid_trace_id_rejected(self):
        with pytest.raises(ValidationError, match="trace_id"):
            Evidence(**_valid_evidence_kwargs(trace_id="not-hex"))

    def test_exception_invalid_artifact_id_rejected(self):
        with pytest.raises(ValidationError, match="artifact_id"):
            Evidence(**_valid_evidence_kwargs(artifact_id="not-a-uuid"))

    def test_exception_unknown_evidence_type_rejected(self):
        with pytest.raises(ValidationError):
            Evidence(**_valid_evidence_kwargs(type="UNKNOWN"))

    def test_exception_unknown_evidence_result_rejected(self):
        with pytest.raises(ValidationError):
            Evidence(**_valid_evidence_kwargs(result="UNKNOWN"))

    @pytest.mark.parametrize("dynamic_ref", ["latest", "main", "HEAD", "master"])
    def test_exception_dynamic_source_revision_rejected(self, dynamic_ref):
        with pytest.raises(ValidationError, match="source_revision"):
            Evidence(**_valid_evidence_kwargs(source_revision=dynamic_ref))

    def test_exception_both_content_fields_empty_rejected(self):
        with pytest.raises(ValidationError, match="content_inline"):
            Evidence(**_valid_evidence_kwargs(content_inline=None, content_ref=None))

    def test_exception_naive_datetime_rejected(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValidationError, match="时区"):
            Evidence(**_valid_evidence_kwargs(created_at=naive))

    def test_exception_verified_before_created_rejected(self):
        now = utc_now()
        earlier = now - timedelta(hours=1)
        with pytest.raises(ValidationError, match="verified_at"):
            Evidence(**_valid_evidence_kwargs(created_at=now, verified_at=earlier))

    def test_exception_expires_before_verified_rejected(self):
        now = utc_now()
        earlier = now - timedelta(hours=1)
        with pytest.raises(ValidationError, match="expires_at"):
            Evidence(
                **_valid_evidence_kwargs(created_at=now, verified_at=now, expires_at=earlier)
            )

    def test_exception_test_failed_with_passed_result_rejected(self):
        """不变量4类比：TEST_FAILED 类型与 result=PASSED 矛盾，必须拒绝。"""
        with pytest.raises(ValidationError, match="矛盾"):
            Evidence(
                **_valid_evidence_kwargs(
                    type=EvidenceType.TEST_FAILED, result=EvidenceResult.PASSED
                )
            )

    def test_exception_empty_content_hash_rejected(self):
        with pytest.raises(ValidationError):
            Evidence(**_valid_evidence_kwargs(content_hash=""))
