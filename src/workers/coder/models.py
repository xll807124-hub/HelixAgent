"""
Coder Worker 数据模型

对齐：REQ-RT-001（实体 ID / 具体 commit SHA）、REQ-RT-005（Checkpoint）
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.runtime.common.types import is_valid_entity_id, is_valid_trace_id


class CoderTaskSpec(BaseModel):
    """Coder Worker 的输入：一次 Issue → 修复任务的完整描述。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # 身份与追踪（Action 实体要求 UUID / 32 位十六进制 trace_id）
    task_id: str
    workflow_id: str
    worker_id: str
    trace_id: str
    user_id: str = "user-001"
    organization_id: str = "org-001"
    project_id: str = "proj-001"

    # 任务内容
    issue_title: str = Field(min_length=1, max_length=200)
    issue_description: str = Field(default="", max_length=20_000)

    # 仓库与分支
    repo_path: str = Field(min_length=1)
    base_branch: str = "main"
    task_branch: str = Field(min_length=1)
    test_path: str = Field(min_length=1)

    # 权限边界：只允许在这些路径内读写（Least Agency）
    allowed_paths: list[str] = Field(min_length=1)

    # 预算
    max_iterations: int = Field(default=20, ge=1, le=200)
    timeout_seconds: int = Field(default=600, ge=1)
    max_tokens: int | None = Field(default=None, ge=0)
    max_cost_cents: int | None = Field(default=None, ge=0)

    @field_validator("task_id", "workflow_id", "worker_id")
    @classmethod
    def _check_entity_id(cls, v: str) -> str:
        if not is_valid_entity_id(v):
            raise ValueError(f"不是合法的 EntityId（UUID）: {v!r}")
        return v

    @field_validator("trace_id")
    @classmethod
    def _check_trace_id(cls, v: str) -> str:
        if not is_valid_trace_id(v):
            raise ValueError(f"不是合法的 32 位十六进制 trace_id: {v!r}")
        return v

    @field_validator("task_branch")
    @classmethod
    def _check_task_branch(cls, v: str, info: Any) -> str:
        base = info.data.get("base_branch")
        if v == base:
            raise ValueError("task_branch 不能等于 base_branch（Coder 只允许写任务分支）")
        return v


class VerificationReport(BaseModel):
    """完成闸门的核对结果。"""

    passed: bool
    tests_passed_after_last_write: bool = False
    diff_non_empty: bool = False
    diff_within_allowed_paths: bool = False
    committed: bool = False
    failures: list[str] = Field(default_factory=list)


class CoderResult(BaseModel):
    """Coder Worker 的输出。

    success 以完成闸门为准，不信任模型自述，也不直接取 loop.succeeded。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_id: str
    worker_id: str
    loop_id: str
    success: bool
    termination_reason: str = ""
    error_message: str | None = None
    iteration_count: int = Field(default=0, ge=0)
    summary: str = ""
    commit_sha: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    pr_url: str | None = None
    verification: VerificationReport | None = None
    total_tokens_consumed: int | None = None
    total_cost_cents: int | None = None
    total_execution_time_ms: int = Field(default=0, ge=0)
