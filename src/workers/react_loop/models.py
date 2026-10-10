"""
ReAct Loop 数据模型

对齐：REQ-RT-001 (Action/Evidence)、REQ-RT-005 (Checkpoint)
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.runtime.entities.action import ActionType


class ReActLoopState(str, Enum):
    """循环状态机状态"""

    INITIALIZING = "INITIALIZING"
    OBSERVING = "OBSERVING"
    REASONING = "REASONING"
    ACTING = "ACTING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Observation(BaseModel):
    """观察结果"""

    iteration: int = Field(ge=0)
    context_summary: str = ""
    available_tools: list[str] = Field(default_factory=list)
    last_observation_result: str | None = None
    remaining_budget: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Reasoning(BaseModel):
    """推理结果"""

    iteration: int = Field(ge=0)
    thought: str = ""
    next_action_type: ActionType | None = None
    next_tool_name: str | None = None
    next_tool_args: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning_time_ms: int = Field(default=0, ge=0)
    should_continue: bool = True
    termination_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReActLoopConfig(BaseModel):
    """循环配置"""

    max_iterations: int = Field(default=10, ge=1)
    timeout_seconds: int = Field(default=300, ge=1)
    max_tokens: int | None = Field(default=None, ge=0)
    max_cost_cents: int | None = Field(default=None, ge=0)


class ReActLoopCheckpoint(BaseModel):
    """循环检查点（用于故障恢复）"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    loop_id: str
    worker_id: str
    task_id: str
    current_state: ReActLoopState
    current_iteration: int = Field(ge=0)
    observations: list[Observation] = Field(default_factory=list)
    reasonings: list[Reasoning] = Field(default_factory=list)
    actions: list[Any] = Field(default_factory=list)
    evidences: list[Any] = Field(default_factory=list)
    total_iterations_completed: int = Field(default=0, ge=0)
    total_time_ms: int = Field(default=0, ge=0)
    total_tokens_consumed: int | None = None
    total_cost_cents: int | None = None


class ReActLoopResult(BaseModel):
    """循环执行结果"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    loop_id: str
    worker_id: str
    task_id: str
    final_state: ReActLoopState
    termination_reason: str = ""
    succeeded: bool
    error_message: str | None = None
    iteration_count: int = Field(ge=0)
    all_observations: list[Observation] = Field(default_factory=list)
    all_reasonings: list[Reasoning] = Field(default_factory=list)
    all_actions: list[Any] = Field(default_factory=list)
    all_evidences: list[Any] = Field(default_factory=list)
    final_artifacts: list[Any] = Field(default_factory=list)
    total_execution_time_ms: int = Field(default=0, ge=0)
    total_tokens_consumed: int | None = None
    total_cost_cents: int | None = None
