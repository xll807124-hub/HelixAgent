"""
Worker 核心实体（REQ-RT-001 §5.3）。

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.3（Worker）

职责：表示 Workflow 中一个具有明确职责、工具集、资源边界和预算的执行实例
（§5.3 职责）。

本模块只做 Schema 字段声明与可在创建时校验的不变量（§5.3 不变量 1/2/3/9 的
格式/必填层面）；不实现：最终授权判定（归 REQ-SEC-002/003 Policy Gateway，
本模型的 allowed_tools/allowed_resources 只是能力声明字段）、状态迁移合法性
（REQ-RT-002）、跨实体资源范围校验（不变量5，需要查询所属 Task/Workflow，
归调用方/服务层负责）。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from src.runtime.common.types import (
    Budget,
    ResourceRef,
    SafeMetadata,
    ensure_utc,
    is_valid_entity_id,
    is_valid_trace_id,
)


class WorkerType(str, Enum):
    """Worker 职责类型（REQ-RT-001 §5.3）。

    注意：`worker_type` 只表示职责类别，不替代 `worker_id`（§5.3 不变量1）；
    本模型不因 `worker_type` 自动授予任何写权限（§5.3 不变量6）。
    """

    EXPLORER = "EXPLORER"
    PLANNER = "PLANNER"
    CODER = "CODER"
    TESTER = "TESTER"
    REVIEWER = "REVIEWER"
    RESOLVER = "RESOLVER"
    RELEASE = "RELEASE"


class WorkerStatus(str, Enum):
    """Worker 状态投影类型（REQ-RT-001 §5.3）。

    合法迁移和终态规则由 REQ-RT-002 定义；本枚举只声明合法取值集合。
    """

    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Worker(BaseModel):
    """Worker 实体（REQ-RT-001 §5.3）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="runtime.worker.v1")
    worker_id: str
    workflow_id: str
    task_id: str
    step_id: str = Field(min_length=1, max_length=200)
    worker_type: WorkerType
    attempt: int = Field(ge=1)
    parent_worker_id: str | None = None
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_resources: list[ResourceRef] = Field(default_factory=list)
    agent_profile_id: str = Field(min_length=1, max_length=200)
    agent_profile_version: str = Field(min_length=1, max_length=100)
    toolset_id: str = Field(min_length=1, max_length=200)
    toolset_version: str = Field(min_length=1, max_length=100)
    source_revision: str = Field(min_length=1, max_length=200)
    budget: Budget = Field(default_factory=Budget)
    status_projection: WorkerStatus | None = None
    trace_id: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: SafeMetadata = Field(default_factory=SafeMetadata)

    # ------------------------------------------------------------------
    # 字段级校验
    # ------------------------------------------------------------------

    @field_validator("worker_id", "workflow_id", "task_id")
    @classmethod
    def _validate_entity_id_fields(cls, v: str, info: ValidationInfo) -> str:
        if not is_valid_entity_id(v):
            raise ValueError(f"{info.field_name} 不是合法的 EntityId（UUID）格式: {v!r}")
        return v

    @field_validator("parent_worker_id")
    @classmethod
    def _validate_parent_worker_id(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_entity_id(v):
            raise ValueError(f"parent_worker_id 不是合法的 EntityId（UUID）格式: {v!r}")
        return v

    @field_validator("input_artifact_ids", "output_artifact_ids")
    @classmethod
    def _validate_artifact_id_lists(cls, v: list[str], info: ValidationInfo) -> list[str]:
        for item in v:
            if not is_valid_entity_id(item):
                raise ValueError(
                    f"{info.field_name} 中包含非法的 EntityId（UUID）格式: {item!r}"
                )
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
        """source_revision 表示 Worker 实例开始处理时所依据的代码版本，禁止动态引用。"""
        if v.strip().lower() in {"latest", "main", "head", "master"}:
            raise ValueError(
                f"source_revision 不能使用动态引用 {v!r}；"
                "必须是具体 commit SHA（REQ-RT-001 §5.3 不变量9）"
            )
        return v

    @field_validator("created_at", "updated_at", "started_at", "completed_at")
    @classmethod
    def _validate_timestamps_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return ensure_utc(v)

    @model_validator(mode="after")
    def _validate_lifecycle_order(self) -> Worker:
        """补充校验：生命周期时间字段的基本先后关系（不涉及状态机合法性判定）。"""
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at 不能早于 created_at")
        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at 不能早于 started_at")
        return self

    @model_validator(mode="after")
    def _validate_no_self_parent(self) -> Worker:
        """禁止自引用：parent_worker_id 不能指向自身（同一 step_id 的不同 attempt
        不能复用 worker_id，见不变量3；本校验是其中「不能自我复用」的最小防护）。"""
        if self.parent_worker_id is not None and self.parent_worker_id == self.worker_id:
            raise ValueError("parent_worker_id 不能指向自身 worker_id")
        return self
