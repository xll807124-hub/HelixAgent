"""
Evidence 核心实体（REQ-RT-001 §5.6）。

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.6（Evidence）

职责：Evidence 是经过某个验证者或确定性工具确认、可用于判断任务质量和完成
条件的结构化证据（§5.6 职责）。

本模块只做 Schema 字段声明与可在创建时校验的不变量（§5.6 不变量 1/4/5 的
格式/必填层面）；不实现：verifier_type=WORKER 时的门禁豁免判定（不变量3，
归 Policy Gateway REQ-SEC-003 负责）、Artifact 版本兼容关系校验（不变量6，
需要跨实体查询，归调用方/服务层负责）、过期/撤销后的完成条件重判定（不变量8，
归状态机/业务流程 REQ-RT-002 负责，本模型只声明 expires_at 字段语义）。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from src.runtime.common.types import (
    ContentRef,
    SafeMetadata,
    ensure_utc,
    is_valid_entity_id,
    is_valid_trace_id,
)


class EvidenceType(str, Enum):
    """Evidence 类型（REQ-RT-001 §5.6）。"""

    PLAN_APPROVED = "PLAN_APPROVED"
    TEST_PASSED = "TEST_PASSED"
    TEST_FAILED = "TEST_FAILED"
    LINT_PASSED = "LINT_PASSED"
    BUILD_PASSED = "BUILD_PASSED"
    SCAN_CLEAN = "SCAN_CLEAN"
    REVIEW_APPROVED = "REVIEW_APPROVED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    DIFF_VERIFIED = "DIFF_VERIFIED"
    PR_CREATED = "PR_CREATED"


class EvidenceSource(str, Enum):
    """Evidence 来源（REQ-RT-001 §5.6）。"""

    TOOL = "TOOL"
    WORKER = "WORKER"
    USER = "USER"
    SYSTEM = "SYSTEM"
    EXTERNAL_PROVIDER = "EXTERNAL_PROVIDER"


class VerificationMethod(str, Enum):
    """验证方式（REQ-RT-001 §5.6）。"""

    DETERMINISTIC_CHECK = "DETERMINISTIC_CHECK"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    POLICY_DECISION = "POLICY_DECISION"
    SIGNATURE_VERIFICATION = "SIGNATURE_VERIFICATION"
    STRUCTURED_ANALYSIS = "STRUCTURED_ANALYSIS"


class VerifierType(str, Enum):
    """验证者类型（REQ-RT-001 §5.6）。

    不变量3：verifier_type=WORKER 时，不能自动满足高风险或最终交付门禁，
    除非策略明确允许；该门禁判定逻辑归 Policy Gateway（REQ-SEC-003），
    本模型只声明该枚举值，不实现门禁豁免逻辑。
    """

    SYSTEM = "SYSTEM"
    USER = "USER"
    SERVICE = "SERVICE"
    WORKER = "WORKER"


class EvidenceResult(str, Enum):
    """证据结果（REQ-RT-001 §5.6）。"""

    PASSED = "PASSED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Evidence(BaseModel):
    """Evidence 实体（REQ-RT-001 §5.6）。

    不变量7：Evidence 创建后不可覆盖；修正结果必须创建新的 Evidence。
    本类使用 `frozen=True` 在语言层面强制实现该不变量。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="runtime.evidence.v1")
    evidence_id: str
    task_id: str
    workflow_id: str
    producer_worker_id: str | None = None
    source_action_id: str | None = None
    artifact_id: str | None = None
    type: EvidenceType
    source: EvidenceSource
    source_revision: str = Field(min_length=1, max_length=200)
    verification_method: VerificationMethod
    verifier_type: VerifierType
    verifier_id: str = Field(min_length=1, max_length=200)
    result: EvidenceResult
    content_schema: str = Field(min_length=1, max_length=200)
    content_schema_version: str = Field(min_length=1, max_length=100)
    content_hash: str = Field(min_length=1, max_length=200)
    content_inline: dict[str, Any] | None = None
    content_ref: ContentRef | None = None
    trace_id: str
    created_at: datetime
    verified_at: datetime
    expires_at: datetime | None = None
    metadata: SafeMetadata = Field(default_factory=SafeMetadata)

    # ------------------------------------------------------------------
    # 字段级校验
    # ------------------------------------------------------------------

    @field_validator("evidence_id", "task_id", "workflow_id")
    @classmethod
    def _validate_entity_id_fields(cls, v: str, info: ValidationInfo) -> str:
        if not is_valid_entity_id(v):
            raise ValueError(f"{info.field_name} 不是合法的 EntityId（UUID）格式: {v!r}")
        return v

    @field_validator("producer_worker_id", "source_action_id", "artifact_id")
    @classmethod
    def _validate_optional_entity_id_fields(
        cls, v: str | None, info: ValidationInfo
    ) -> str | None:
        if v is not None and not is_valid_entity_id(v):
            raise ValueError(f"{info.field_name} 不是合法的 EntityId（UUID）格式: {v!r}")
        return v

    @field_validator("trace_id")
    @classmethod
    def _validate_trace_id(cls, v: str) -> str:
        if not is_valid_trace_id(v):
            raise ValueError(f"trace_id 不是合法的 32 位十六进制字符串: {v!r}")
        return v

    @field_validator("source_revision")
    @classmethod
    def _validate_source_revision_not_dynamic(cls, v: str) -> str:
        """不变量1：Evidence 必须绑定 source_revision，禁止动态引用。"""
        if v.strip().lower() in {"latest", "main", "head", "master"}:
            raise ValueError(
                f"source_revision 不能使用动态引用 {v!r}；"
                "必须是具体 commit SHA（REQ-RT-001 §5.6 不变量1）"
            )
        return v

    @field_validator("created_at", "verified_at", "expires_at")
    @classmethod
    def _validate_timestamps_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return ensure_utc(v)

    @model_validator(mode="after")
    def _validate_content_presence(self) -> Evidence:
        """content_inline 与 content_ref 至少有一个存在（与 Artifact §5.5 不变量3同构）。"""
        if self.content_inline is None and self.content_ref is None:
            raise ValueError(
                "content_inline 和 content_ref 不能同时为空（REQ-RT-001 §5.6，类比 §5.5 不变量3）"
            )
        return self

    @model_validator(mode="after")
    def _validate_verified_at_order(self) -> Evidence:
        """补充校验：verified_at 不能早于 created_at。"""
        if self.verified_at < self.created_at:
            raise ValueError("verified_at 不能早于 created_at")
        if self.expires_at is not None and self.expires_at < self.verified_at:
            raise ValueError("expires_at 不能早于 verified_at")
        return self

    @model_validator(mode="after")
    def _validate_evidence_type_result_consistency(self) -> Evidence:
        """不变量4：Evidence 不能只依赖模型文字声明，必须有验证方式和来源（本校验
        补充一条最基本的类型-结果一致性检查，防止明显矛盾数据，如 TEST_FAILED
        却标记 result=PASSED）。"""
        contradictions = {
            EvidenceType.TEST_FAILED: EvidenceResult.PASSED,
        }
        if contradictions.get(self.type) == self.result:
            raise ValueError(
                f"type={self.type.value} 与 result={self.result.value} "
                "矛盾（REQ-RT-001 §5.6 不变量4）"
            )
        return self
