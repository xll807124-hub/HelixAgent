"""Explicit deployment profile; secrets and endpoint cannot come from prompts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator

from .types import DTO, ErrorCode, GatewayError

RESPONSES_URL = "https://api.openai.com/v1/responses"


class ModelProfile(DTO):
    profile_ref: str = Field(min_length=1)
    model_id: str = Field(min_length=1, max_length=128)
    model_revision: str = Field(min_length=1, max_length=128)
    context_window: int = Field(gt=0, le=10000000)
    max_output_tokens: int = Field(default=2048, gt=0, le=1000000)
    input_microusd_per_mtoken: int = Field(gt=0, le=10**12)
    output_microusd_per_mtoken: int = Field(gt=0, le=10**12)
    pricing_version: str = Field(min_length=1)
    pricing_valid_until: datetime
    structured_outputs: bool = True
    native_tools: bool = False

    @field_validator("pricing_valid_until")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("pricing validity requires timezone")
        return value

    def validate_at(self, now: datetime) -> None:
        if now >= self.pricing_valid_until:
            raise GatewayError(ErrorCode.INVALID_REQUEST)

    def cost(self, input_tokens: int, output_tokens: int) -> int:
        units = (
            input_tokens * self.input_microusd_per_mtoken
            + output_tokens * self.output_microusd_per_mtoken
        )
        return (units + 999999) // 1000000


class GatewayConfig(DTO):
    api_key: SecretStr = Field(repr=False)
    profile: ModelProfile
    budget_db: Path
    deployment: Literal["single_host"] = "single_host"
    connect_timeout: float = Field(default=5.0, gt=0, le=120)
    first_event_timeout: float = Field(default=30.0, gt=0, le=120)
    idle_timeout: float = Field(default=15.0, gt=0, le=120)
    total_timeout: float = Field(default=120.0, gt=0, le=600)
    max_body_bytes: int = Field(default=262144, ge=128, le=1048576)
    max_event_bytes: int = Field(default=262144, ge=128, le=1048576)
    max_response_bytes: int = Field(default=2097152, ge=128, le=8388608)
    max_events: int = Field(default=10000, ge=1, le=100000)
    queue_size: int = Field(default=32, ge=1, le=1024)

    @field_validator("api_key")
    @classmethod
    def secret_present(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("credential missing")
        return value

    @field_validator("budget_db")
    @classmethod
    def local_path(cls, value: Path) -> Path:
        if not value.is_absolute() or str(value).startswith(("\\\\", "//")):
            raise ValueError("budget database requires an absolute local path")
        return value
