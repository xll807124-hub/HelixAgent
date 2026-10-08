"""
Artifact 核心实体（REQ-RT-001 §5.5）。

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.5（Artifact）

职责：Artifact 是 Worker 之间传递的不可变、可引用、带版本来源的结构化产物
（§5.5 职责）。

本模块只做 Schema 字段声明与可在创建时校验的不变量（§5.5 不变量 1/2/3/7 的
格式/必填层面）；不实现：跨实体生产者归属校验（不变量5/6，需要查询所属
Worker/Action，归调用方/服务层负责）、内容实际哈希重算校验（不变量2，本模型
只做"必须提供 content_hash"的字段级要求，不读取 content_ref 的真实对象验证哈
希，归存储层/对象存储集成负责）。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from src.runtime.common.types import (
    ContentRef,
    DataSensitivity,
    SafeMetadata,
    ensure_utc,
    is_valid_entity_id,
    is_valid_trace_id,
)


class ArtifactType(str, Enum):
    """Artifact 类型（REQ-RT-001 §5.5）。"""

    PLAN = "PLAN"
    CODE_CHANGES = "CODE_CHANGES"
    TEST_RESULTS = "TEST_RESULTS"
    DIFF = "DIFF"
    REVIEW_FINDINGS = "REVIEW_FINDINGS"
    FAILURE_ANALYSIS = "FAILURE_ANALYSIS"
    RELEASE_SUMMARY = "RELEASE_SUMMARY"


class Artifact(BaseModel):
    """Artifact 实体（REQ-RT-001 §5.5）。

    不变量1：Artifact 创建后不可原地修改；内容变化必须产生新的 artifact_id。
    本类使用 `frozen=True` 在语言层面强制实现该不变量——任何尝试修改已创建
    实例字段的操作都会在 pydantic 层直接抛出 ValidationError。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="runtime.artifact.v1")
    artifact_id: str
    task_id: str
    workflow_id: str
    producer_worker_id: str
    producer_action_id: str | None = None
    type: ArtifactType
    content_schema: str = Field(min_length=1, max_length=200)
    content_schema_version: str = Field(min_length=1, max_length=100)
    source_revision: str = Field(min_length=1, max_length=200)
    content_hash: str = Field(min_length=1, max_length=200)
    content_size_bytes: int = Field(ge=0)
    content_inline: dict[str, Any] | None = None
    content_ref: ContentRef | None = None
    sensitivity: DataSensitivity
    trace_id: str
    created_at: datetime
    metadata: SafeMetadata = Field(default_factory=SafeMetadata)

    # ------------------------------------------------------------------
    # 字段级校验
    # ------------------------------------------------------------------

    @field_validator("artifact_id", "task_id", "workflow_id", "producer_worker_id")
    @classmethod
    def _validate_entity_id_fields(cls, v: str, info: ValidationInfo) -> str:
        if not is_valid_entity_id(v):
            raise ValueError(f"{info.field_name} 不是合法的 EntityId（UUID）格式: {v!r}")
        return v

    @field_validator("producer_action_id")
    @classmethod
    def _validate_producer_action_id(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_entity_id(v):
            raise ValueError(f"producer_action_id 不是合法的 EntityId（UUID）格式: {v!r}")
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
        if v.strip().lower() in {"latest", "main", "head", "master"}:
            raise ValueError(
                f"source_revision 不能使用动态引用 {v!r}；"
                "必须是具体 commit SHA（REQ-RT-001 §5.5 不变量7）"
            )
        return v

    @field_validator("created_at")
    @classmethod
    def _validate_created_at_utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)

    @model_validator(mode="after")
    def _validate_content_presence(self) -> Artifact:
        """不变量3：content_inline 与 content_ref 至少有一个存在，不能同时为空。"""
        if self.content_inline is None and self.content_ref is None:
            raise ValueError(
                "content_inline 和 content_ref 不能同时为空（REQ-RT-001 §5.5 不变量3）"
            )
        return self
