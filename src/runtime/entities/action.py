"""
Action 核心实体（REQ-RT-001 §5.4）。

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §5.4（Action）

职责：表示 Worker 提议的一次结构化动作，是模型/Worker 与 Policy Gateway、
工具执行器之间的契约对象（§5.4 职责）。

本模块只做 Schema 字段声明与可在创建时校验的不变量（§5.4 不变量 1/5/6 的
格式/必填层面）；不实现：参数 Schema 校验（归 REQ-HAR-003 Tool Adapter）、
Policy Gateway 授权判定（归 REQ-SEC-002/003，`requires_approval`/
`policy_decision_id` 只是声明/引用字段，本模型不赋予放行语义）、
幂等键生成算法（归 REQ-RT-007，本模型只接受外部传入的 idempotency_key 作为
稳定引用）。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from src.runtime.common.types import (
    ResourceRef,
    SafeMetadata,
    ensure_utc,
    is_valid_entity_id,
    is_valid_trace_id,
)
from src.runtime.entities.task import RiskLevel


class ActionType(str, Enum):
    """Action 类型（REQ-RT-001 §5.4）。"""

    READ = "READ"
    ANALYZE = "ANALYZE"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    DELEGATE = "DELEGATE"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    REPORT = "REPORT"


class ActionStatus(str, Enum):
    """Action 状态投影类型（REQ-RT-001 §5.4）。

    合法迁移和终态规则由 REQ-RT-002 定义；本枚举只声明合法取值集合。
    """

    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Action 不变量6：source_revision 对 WRITE/EXECUTE/REPORT 类型必须存在。
_SOURCE_REVISION_REQUIRED_TYPES = {ActionType.WRITE, ActionType.EXECUTE, ActionType.REPORT}


class Action(BaseModel):
    """Action 实体（REQ-RT-001 §5.4）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="runtime.action.v1")
    action_id: str
    task_id: str
    workflow_id: str
    worker_id: str
    step_id: str = Field(min_length=1, max_length=200)
    type: ActionType
    tool_name: str = Field(min_length=1, max_length=200)
    tool_schema_version: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    target_resources: list[ResourceRef] = Field(min_length=1)
    source_revision: str | None = Field(default=None, max_length=200)
    risk_level: RiskLevel
    requires_approval: bool = False
    policy_decision_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)
    expected_observation_schema: str | None = Field(default=None, max_length=200)
    status_projection: ActionStatus | None = None
    trace_id: str
    created_at: datetime
    updated_at: datetime
    proposed_at: datetime
    authorized_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: SafeMetadata = Field(default_factory=SafeMetadata)

    # ------------------------------------------------------------------
    # 字段级校验
    # ------------------------------------------------------------------

    @field_validator("action_id", "task_id", "workflow_id", "worker_id")
    @classmethod
    def _validate_entity_id_fields(cls, v: str, info: ValidationInfo) -> str:
        if not is_valid_entity_id(v):
            raise ValueError(f"{info.field_name} 不是合法的 EntityId（UUID）格式: {v!r}")
        return v

    @field_validator("policy_decision_id")
    @classmethod
    def _validate_policy_decision_id(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_entity_id(v):
            raise ValueError(f"policy_decision_id 不是合法的 EntityId（UUID）格式: {v!r}")
        return v

    @field_validator("trace_id")
    @classmethod
    def _validate_trace_id(cls, v: str) -> str:
        if not is_valid_trace_id(v):
            raise ValueError(f"trace_id 不是合法的 32 位十六进制字符串: {v!r}")
        return v

    @field_validator("source_revision")
    @classmethod
    def _validate_source_revision_not_dynamic(cls, v: str | None) -> str | None:
        if v is not None and v.strip().lower() in {"latest", "main", "head", "master"}:
            raise ValueError(
                f"source_revision 不能使用动态引用 {v!r}；"
                "必须是具体 commit SHA（REQ-RT-001 §5.4 不变量6）"
            )
        return v

    @field_validator(
        "created_at", "updated_at", "proposed_at", "authorized_at", "started_at", "completed_at"
    )
    @classmethod
    def _validate_timestamps_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        return ensure_utc(v)

    @model_validator(mode="after")
    def _validate_source_revision_required_for_type(self) -> Action:
        """Action 不变量6：WRITE/EXECUTE/REPORT 类型必须存在 source_revision。"""
        if self.type in _SOURCE_REVISION_REQUIRED_TYPES and self.source_revision is None:
            raise ValueError(
                f"type={self.type.value} 时 source_revision 必须存在（REQ-RT-001 §5.4 不变量6）"
            )
        return self

    @model_validator(mode="after")
    def _validate_lifecycle_order(self) -> Action:
        """补充校验：生命周期时间字段的基本先后关系（不涉及状态机合法性判定）。"""
        if self.started_at is not None and self.started_at < self.proposed_at:
            raise ValueError("started_at 不能早于 proposed_at")
        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at 不能早于 started_at")
        return self
