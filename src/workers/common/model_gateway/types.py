"""Typed, provider-independent request/result boundary (G-MODEL v1)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    REFUSAL = "REFUSAL"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION = "PERMISSION"
    POLICY_DENIED = "POLICY_DENIED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    BUDGET_PENDING = "BUDGET_PENDING"
    REQUEST_CONFLICT = "REQUEST_CONFLICT"
    RATE_LIMIT = "RATE_LIMIT"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    STREAM_INTERRUPTED = "STREAM_INTERRUPTED"
    CANCELLED = "CANCELLED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class GatewayError(Exception):
    """Safe errors never contain upstream response bodies or exception text."""

    def __init__(self, code: ErrorCode, retry_after: float | None = None):
        super().__init__(code.value)
        self.code = code
        self.retry_after = retry_after


class DTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, protected_namespaces=())


class RequestContext(DTO):
    organization_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    repository_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)
    worker_id: str = Field(min_length=1, max_length=128)
    step_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    span_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    request_id: str = Field(min_length=1, max_length=128)
    attempt: int = Field(default=1, ge=1)
    deadline_at: datetime

    @field_validator("deadline_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("deadline requires a timezone")
        return value

    @field_validator("trace_id", "span_id")
    @classmethod
    def nonzero_trace(cls, value: str) -> str:
        if int(value, 16) == 0:
            raise ValueError("trace coordinates must be nonzero")
        return value

    @property
    def account(self) -> tuple[str, str]:
        return self.organization_id, self.task_id

    @property
    def scope_digest(self) -> str:
        scope = (self.organization_id, self.project_id, self.repository_id, self.task_id)
        return hashlib.sha256(json.dumps(scope).encode()).hexdigest()


class Message(DTO):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(max_length=262144, repr=False)
    call_id: str | None = Field(default=None, max_length=128)
    tool_name: str | None = Field(default=None, max_length=64)
    arguments: dict[str, Any] | None = Field(default=None, repr=False)
    source: Literal["trusted_config", "user", "repository", "tool_output", "model"] = "user"
    trust: Literal["trusted", "untrusted"] = "untrusted"

    @model_validator(mode="after")
    def instruction_source(self) -> Message:
        if self.role == "system" and (self.source != "trusted_config" or self.trust != "trusted"):
            raise ValueError("system instructions require trusted configuration")
        if self.source in ("repository", "tool_output") and self.trust != "untrusted":
            raise ValueError("external content must remain untrusted")
        return self


class ToolDefinition(DTO):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str = Field(default="", max_length=4096)
    input_schema: dict[str, Any] = Field(repr=False)
    schema_version: str = Field(min_length=1, max_length=128)


class ModelRequest(DTO):
    schema_version: Literal["model.request.v1"] = "model.request.v1"
    context: RequestContext
    profile_ref: str = Field(min_length=1, max_length=128)
    messages: tuple[Message, ...] = Field(min_length=1, max_length=256, repr=False)
    tools: tuple[ToolDefinition, ...] = Field(default=(), max_length=32, repr=False)
    toolset_version: str = Field(min_length=1, max_length=128)
    mode: Literal["structured", "native"] = "structured"
    max_output_tokens: int = Field(default=2048, ge=1, le=1000000)

    def digest(self) -> str:
        # Request identity binds the complete immutable snapshot, not just the prompt.
        data = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class Usage(DTO):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_microusd: int = Field(ge=0)
    pricing_version: str
    currency: Literal["USD"] = "USD"
    source: Literal["provider_tokens_configured_price"] = "provider_tokens_configured_price"


class ToolProposal(DTO):
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(repr=False)
    tool_schema_version: str


class ModelResult(DTO):
    schema_version: Literal["model.result.v1"] = "model.result.v1"
    request_id: str
    provider_request_id: str
    model_id: str
    finish_reason: Literal["completed"] = "completed"
    usage: Usage
    tool_proposal: ToolProposal | None = None
    final_summary: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def outcome(self) -> ModelResult:
        if (self.tool_proposal is None) == (self.final_summary is None):
            raise ValueError("exactly one outcome required")
        if self.final_summary is not None and not self.final_summary.strip():
            raise ValueError("nonempty summary required")
        return self


class ModelEvent(DTO):
    schema_version: Literal["model.event.v1"] = "model.event.v1"
    request_id: str
    attempt: int
    sequence: int
    type: Literal[
        "started",
        "text_delta",
        "tool_arguments_delta",
        "usage",
        "completed",
        "failed",
        "cancelled",
        "timed_out",
    ]
    delta: str | None = Field(default=None, repr=False)
    result: ModelResult | None = Field(default=None, repr=False)
    error: ErrorCode | None = None
    retry_after: float | None = None


class CancellationToken:
    """Trusted composition can connect this token to Task cancellation/Kill Switch."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()

    def check(self) -> None:
        if self._event.is_set():
            raise GatewayError(ErrorCode.CANCELLED)
