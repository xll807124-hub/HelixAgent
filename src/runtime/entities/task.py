"""
AgentTask 核心实体（REQ-RT-001 §5.1）。

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.1（AgentTask）

职责：表示用户提出的一项研发意图和其完整交付边界，是用户、组织、项目、
仓库、预算和 Workflow 的业务根实体（§5.1 职责）。

本模块只做 Schema 字段声明与可在创建时校验的不变量（§5.1 Task 不变量 1/4/7/8）；
不实现：状态迁移合法性（REQ-RT-002）、权限授权判定（REQ-SEC-002）、
事件事实历史（REQ-RT-003）。`status_projection` 仅作为投影字段类型存在，
本模型不提供状态迁移方法。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from src.runtime.common.types import (
    Budget,
    SafeMetadata,
    ensure_utc,
    is_valid_entity_id,
    is_valid_trace_id,
)


class SourceType(str, Enum):
    """任务来源类型（REQ-RT-001 §5.1 枚举）。"""

    ISSUE = "ISSUE"
    NATURAL_LANGUAGE = "NATURAL_LANGUAGE"
    PULL_REQUEST = "PULL_REQUEST"
    REVIEW_COMMENT = "REVIEW_COMMENT"
    WEBHOOK = "WEBHOOK"


class RiskLevel(str, Enum):
    """风险等级（REQ-RT-001 §5.1 枚举，Action §5.4 复用同一枚举）。"""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TaskStatus(str, Enum):
    """Task 状态投影类型（REQ-RT-001 §5.1）。

    合法迁移和终态规则由 REQ-RT-002 定义；本枚举只声明合法取值集合。
    """

    CREATED = "CREATED"
    AUTHORIZING = "AUTHORIZING"
    PLANNING = "PLANNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PREPARING_WORKSPACE = "PREPARING_WORKSPACE"
    EXECUTING = "EXECUTING"
    VALIDATING = "VALIDATING"
    CREATING_PR = "CREATING_PR"
    WAITING_REVIEW = "WAITING_REVIEW"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class SourceReference(BaseModel):
    """任务来源引用（REQ-RT-001 §5.1 SourceReference）。

    必须保存来源快照或可验证引用，不能只保存一个可能随后变化的外部 URL
    （§5.1 SourceReference 说明）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: SourceType
    provider: str | None = Field(default=None, max_length=100)
    external_id: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2000)
    snapshot_hash: str | None = Field(default=None, max_length=200)


class AgentTask(BaseModel):
    """AgentTask 实体（REQ-RT-001 §5.1）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="runtime.task.v1")
    task_id: str
    organization_id: str
    project_id: str
    repository_id: str
    creator_id: str
    source_type: SourceType
    source_reference: SourceReference | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20000)
    risk_level: RiskLevel
    workflow_template_id: str = Field(min_length=1, max_length=200)
    workflow_template_version: str = Field(min_length=1, max_length=100)
    workflow_id: str | None = None
    base_revision: str = Field(min_length=1, max_length=200)
    working_branch: str | None = Field(default=None, max_length=500)
    working_revision: str | None = Field(default=None, max_length=200)
    budget: Budget = Field(default_factory=Budget)
    status_projection: TaskStatus | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: SafeMetadata = Field(default_factory=SafeMetadata)
    trace_id: str

    # ------------------------------------------------------------------
    # 字段级校验
    # ------------------------------------------------------------------

    @field_validator("task_id", "organization_id", "project_id", "repository_id", "creator_id")
    @classmethod
    def _validate_entity_id_fields(cls, v: str, info: ValidationInfo) -> str:
        if not is_valid_entity_id(v):
            raise ValueError(f"{info.field_name} 不是合法的 EntityId（UUID）格式: {v!r}")
        return v

    @field_validator("workflow_id")
    @classmethod
    def _validate_workflow_id(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_entity_id(v):
            raise ValueError(f"workflow_id 不是合法的 EntityId（UUID）格式: {v!r}")
        return v

    @field_validator("trace_id")
    @classmethod
    def _validate_trace_id(cls, v: str) -> str:
        if not is_valid_trace_id(v):
            raise ValueError(f"trace_id 不是合法的 32 位十六进制字符串: {v!r}")
        return v

    @field_validator("base_revision")
    @classmethod
    def _validate_base_revision_not_dynamic(cls, v: str) -> str:
        """Task 不变量 4：base_revision 创建时必须确定，不能用"最新代码"动态字符串替代。"""
        if v.strip().lower() in {"latest", "main", "head", "master"}:
            raise ValueError(
                f"base_revision 不能使用动态引用 {v!r}；"
                "必须是具体 commit SHA（REQ-RT-001 §5.1 不变量4）"
            )
        return v

    @field_validator("created_at", "updated_at", "started_at", "completed_at")
    @classmethod
    def _validate_timestamps_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return ensure_utc(v)

    @model_validator(mode="after")
    def _validate_lifecycle_order(self) -> AgentTask:
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
