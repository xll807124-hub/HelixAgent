"""
Workflow 核心实体（REQ-RT-001 §5.2）。

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.2（Workflow）

职责：表示一个 Task 的一次具体执行实例，绑定一个固定的 Workflow 模板版本和一组
运行范围（§5.2 职责）。

本模块只做 Schema 字段声明与可在创建时校验的不变量（§5.2 不变量 1/2/3）；
不实现：状态迁移合法性（REQ-RT-002）、与 Task 的作用域继承一致性校验
（不变量4，需要跨实体查询 Task，归调用方/服务层负责，本模型只做自身字段格式校验）。
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


class WorkflowStatus(str, Enum):
    """Workflow 状态投影类型（REQ-RT-001 §5.2）。

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


class Workflow(BaseModel):
    """Workflow 实体（REQ-RT-001 §5.2）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="runtime.workflow.v1")
    workflow_id: str
    task_id: str
    organization_id: str
    project_id: str
    repository_id: str
    workflow_template_id: str = Field(min_length=1, max_length=200)
    workflow_template_version: str = Field(min_length=1, max_length=100)
    agent_profile_id: str = Field(min_length=1, max_length=200)
    agent_profile_version: str = Field(min_length=1, max_length=100)
    toolset_id: str = Field(min_length=1, max_length=200)
    toolset_version: str = Field(min_length=1, max_length=100)
    base_revision: str = Field(min_length=1, max_length=200)
    working_branch: str | None = Field(default=None, max_length=500)
    working_revision: str | None = Field(default=None, max_length=200)
    status_projection: WorkflowStatus | None = None
    budget: Budget = Field(default_factory=Budget)
    trace_id: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parent_workflow_id: str | None = None
    metadata: SafeMetadata = Field(default_factory=SafeMetadata)

    # ------------------------------------------------------------------
    # 字段级校验
    # ------------------------------------------------------------------

    @field_validator("workflow_id", "task_id", "organization_id", "project_id", "repository_id")
    @classmethod
    def _validate_entity_id_fields(cls, v: str, info: ValidationInfo) -> str:
        if not is_valid_entity_id(v):
            raise ValueError(f"{info.field_name} 不是合法的 EntityId（UUID）格式: {v!r}")
        return v

    @field_validator("parent_workflow_id")
    @classmethod
    def _validate_parent_workflow_id(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_entity_id(v):
            raise ValueError(f"parent_workflow_id 不是合法的 EntityId（UUID）格式: {v!r}")
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
        """Workflow 必须继承 Task 的 base_revision 语义，同样禁止动态引用（§5.2 不变量4类比）。"""
        if v.strip().lower() in {"latest", "main", "head", "master"}:
            raise ValueError(
                f"base_revision 不能使用动态引用 {v!r}；必须是具体 commit SHA（REQ-RT-001 §5.2）"
            )
        return v

    @field_validator("created_at", "updated_at", "started_at", "completed_at")
    @classmethod
    def _validate_timestamps_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return ensure_utc(v)

    @model_validator(mode="after")
    def _validate_lifecycle_order(self) -> Workflow:
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
    def _validate_no_self_parent(self) -> Workflow:
        """Workflow 不变量5类比：禁止自引用（MVP 默认禁止无限递归创建的最小防护）。"""
        if self.parent_workflow_id is not None and self.parent_workflow_id == self.workflow_id:
            raise ValueError("parent_workflow_id 不能指向自身 workflow_id")
        return self
