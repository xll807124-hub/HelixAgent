"""
Kill Switch 数据模型（src/security/kill_switch/models.py）。

提供：
- TriggerEvent：触发事件（含 reason/actor/scope/timestamp）
- RecoveryEvent：恢复事件（二阶段：request / confirm）
- StatusView：当前状态对外视图
- BlockReason：被 Kill Switch 拒绝时的具体原因

对齐：SEC-009 §4（事件 schema）
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.runtime.common.types import ensure_utc
from src.security.kill_switch.state import KillSwitchScope, KillSwitchState


class TriggerEvent(BaseModel):
    """触发事件。"""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    scope: KillSwitchScope
    reason: str = Field(min_length=1, max_length=2000)
    actor_id: str = Field(min_length=1, max_length=200)
    triggered_at: datetime
    trigger_source: str = Field(
        default="manual",
        min_length=1,
        max_length=100,
        description="manual / policy_violation / credential_leak / anomaly",
    )
    metadata: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def _validate_timestamp(cls, v: datetime) -> datetime:
        return ensure_utc(v)


class RecoveryRequestEvent(BaseModel):
    """恢复请求事件（阶段 1：进入 RECOVERING）。"""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    confirm_token: str = Field(
        min_length=16,
        max_length=200,
        description="服务端返回的二次确认 token；调用方必须用它来 confirm",
    )
    requested_at: datetime
    actor_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=2000)


class RecoveryConfirmEvent(BaseModel):
    """恢复确认事件（阶段 2：解除 TRIGGERED/RECOVERING）。"""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    confirm_token: str = Field(min_length=1, max_length=200)
    confirmed_at: datetime
    actor_id: str = Field(min_length=1, max_length=200)


class StatusView(BaseModel):
    """Kill Switch 当前状态对外视图。"""

    state: KillSwitchState
    current_trigger: TriggerEvent | None = None
    current_recovery: RecoveryRequestEvent | None = None
    total_triggers: int = Field(ge=0, default=0)
    last_updated_at: datetime | None = None


class BlockReason(BaseModel):
    """被 Kill Switch 拒绝时的具体原因。"""

    blocked: bool
    reason: str = ""
    current_state: KillSwitchState
    current_scope: KillSwitchScope | None = None
    trigger_event_id: str | None = None


__all__ = [
    "BlockReason",
    "RecoveryConfirmEvent",
    "RecoveryRequestEvent",
    "StatusView",
    "TriggerEvent",
]