"""Tool 资源 schema（src/api/schemas/tool.py）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolSummary(BaseModel):
    """工具列表项的对外视图（仅暴露注册信息，不含执行细节）。"""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str
    risk_level: str
    timeout_seconds: int = Field(ge=0, le=3600)
    capabilities: list[str] = Field(default_factory=list)


class ToolListResponse(BaseModel):
    """GET /api/v1/tools 响应。"""

    items: list[ToolSummary]
    total: int = Field(ge=0)


class ToolInvokeRequest(BaseModel):
    """POST /api/v1/tools/{name}/invoke 请求体。"""

    model_config = ConfigDict(extra="forbid")

    params: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None, max_length=200)


class ToolInvokeResponse(BaseModel):
    """工具调用结果（不直接暴露 ToolResult，避免字段不稳定）。"""

    tool_name: str
    success: bool
    output: Any | None = None
    error: str | None = None
    execution_time_ms: int = Field(ge=0)
    evidence_id: str | None = None
    action_status: str | None = None