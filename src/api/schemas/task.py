"""Task 资源 schema（src/api/schemas/task.py）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.runtime.entities.task import RiskLevel, SourceType

# 与 REQ-RT-001 §5.1 Task 不变量4 对齐：API 层 fail-fast 拦截动态 base_revision
_FORBIDDEN_BASE_REVISIONS = frozenset({"latest", "main", "head", "master"})


class TaskCreateRequest(BaseModel):
    """POST /api/v1/tasks 请求体。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20000)
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    source_type: SourceType = Field(default=SourceType.NATURAL_LANGUAGE)
    workflow_template_id: str = Field(min_length=1, max_length=200)
    workflow_template_version: str = Field(min_length=1, max_length=100)
    base_revision: str = Field(
        min_length=1,
        max_length=200,
        description="必须为具体 commit SHA；禁止 latest/main/head/master",
    )
    working_branch: str | None = Field(default=None, max_length=500)
    budget_max_tokens: int = Field(default=100000, ge=0, le=10_000_000)
    budget_max_cost_microusd: int = Field(default=500_000, ge=0, le=10_000_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("base_revision")
    @classmethod
    def _validate_base_revision_not_dynamic(cls, v: str) -> str:
        """API 层 fail-fast：动态 base_revision 必须在 schema 阶段拒，避免延迟到
        AgentTask 构造才报错（与 REQ-RT-001 §5.1 不变量 4 对齐）。"""
        if v.strip().lower() in _FORBIDDEN_BASE_REVISIONS:
            raise ValueError(
                f"base_revision 不能使用动态引用 {v!r}；"
                "必须是具体 commit SHA（REQ-RT-001 §5.1 不变量4）"
            )
        return v


class TaskResponse(BaseModel):
    """Task 资源对外视图（仅暴露稳定字段，避免泄露内部 metadata 键）。"""

    model_config = ConfigDict(extra="ignore")

    task_id: str
    organization_id: str
    project_id: str
    repository_id: str
    creator_id: str
    title: str
    description: str
    risk_level: RiskLevel
    source_type: SourceType
    workflow_template_id: str
    workflow_template_version: str
    workflow_id: str | None
    base_revision: str
    working_branch: str | None
    status: str | None = Field(
        default=None,
        description="当前 Task 投影状态（可能为 None 表示未启动）",
    )
    trace_id: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class TaskListResponse(BaseModel):
    """GET /api/v1/tasks 分页响应。"""

    items: list[TaskResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)