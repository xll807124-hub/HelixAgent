"""Explicit environment configuration. Invalid values are never echoed in diagnostics."""

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from pydantic import SecretStr

from .config import GatewayConfig, ModelProfile

REQUIRED_ENV = (
    "OPENAI_API_KEY",
    "AI_MODEL_ID",
    "AI_MODEL_REVISION",
    "AI_MODEL_CONTEXT_WINDOW",
    "AI_MODEL_PRICE_INPUT_MICROUSD_PER_MTOKEN",
    "AI_MODEL_PRICE_OUTPUT_MICROUSD_PER_MTOKEN",
    "AI_MODEL_PRICING_VERSION",
    "AI_MODEL_PRICING_VALID_UNTIL",
    "AI_MODEL_BUDGET_DB",
)


class ConfigurationError(ValueError):
    def __init__(self, missing: tuple[str, ...] = ()):
        super().__init__(
            "Missing configuration: " + ", ".join(missing)
            if missing
            else "Invalid model configuration"
        )
        self.missing = missing


def load_config(environ: Mapping[str, str] | None = None) -> GatewayConfig:
    env = os.environ if environ is None else environ
    missing = tuple(name for name in REQUIRED_ENV if not env.get(name, "").strip())
    if missing:
        raise ConfigurationError(missing)
    try:
        return GatewayConfig(
            api_key=SecretStr(env["OPENAI_API_KEY"]),
            budget_db=Path(env["AI_MODEL_BUDGET_DB"]),
            profile=ModelProfile(
                profile_ref=env.get("AI_MODEL_PROFILE_REF", "openai-responses-v1"),
                model_id=env["AI_MODEL_ID"],
                model_revision=env["AI_MODEL_REVISION"],
                context_window=int(env["AI_MODEL_CONTEXT_WINDOW"]),
                max_output_tokens=int(env.get("AI_MODEL_MAX_OUTPUT_TOKENS", "2048")),
                input_microusd_per_mtoken=int(env["AI_MODEL_PRICE_INPUT_MICROUSD_PER_MTOKEN"]),
                output_microusd_per_mtoken=int(env["AI_MODEL_PRICE_OUTPUT_MICROUSD_PER_MTOKEN"]),
                pricing_version=env["AI_MODEL_PRICING_VERSION"],
                pricing_valid_until=datetime.fromisoformat(env["AI_MODEL_PRICING_VALID_UNTIL"]),
            ),
        )
    except (ValueError, TypeError, OverflowError):
        raise ConfigurationError() from None
