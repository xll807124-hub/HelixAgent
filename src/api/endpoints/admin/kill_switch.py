"""
Kill Switch Admin API（src/api/endpoints/admin/kill_switch.py）。

端点（需 admin token）：
- GET  /admin/kill-switch/status           查询当前状态
- POST /admin/kill-switch/trigger          触发（紧急冻结）
- POST /admin/kill-switch/recover          进入恢复流程（返回 confirm_token）
- POST /admin/kill-switch/recover/confirm  二次确认解除
- POST /admin/kill-switch/triggers/{name}/enable   启用触发器
- POST /admin/kill-switch/triggers/{name}/disable  禁用触发器

设计原则：
- 所有写操作经 admin token 校验
- 触发器默认 disable（避免误触发）
- 二阶段恢复：recover → 30 分钟内必须 confirm，否则需重新 recover
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.endpoints.admin.auth import require_admin_token
from src.api.middleware.error_handler import APIError
from src.api.middleware.trace import get_trace_id
from src.api.schemas.common import APIErrorCode, success_response
from src.security.kill_switch import (
    KillSwitchManager,
    KillSwitchScope,
    TriggerRegistry,
)

router = APIRouter(prefix="/admin/kill-switch", tags=["admin:kill-switch"])


def _get_manager(request: Request) -> KillSwitchManager:
    """从 app.state 取 KillSwitchManager；未初始化则 503。"""
    manager: KillSwitchManager | None = getattr(
        request.app.state, "kill_switch_manager", None
    )
    if manager is None:
        raise APIError(
            status_code=503,
            code=APIErrorCode.UPSTREAM_UNAVAILABLE,
            message="kill switch manager not initialized",
        )
    return manager


def _get_trigger_registry(request: Request) -> TriggerRegistry:
    reg: TriggerRegistry | None = getattr(
        request.app.state, "kill_switch_trigger_registry", None
    )
    if reg is None:
        raise APIError(
            status_code=503,
            code=APIErrorCode.UPSTREAM_UNAVAILABLE,
            message="kill switch trigger registry not initialized",
        )
    return reg


# ============ Request Schemas ============


class TriggerRequest(BaseModel):
    """POST /admin/kill-switch/trigger 请求体。"""

    model_config = ConfigDict(extra="forbid")

    scope: KillSwitchScope
    reason: str = Field(min_length=1, max_length=2000)
    trigger_source: str = Field(
        default="manual", min_length=1, max_length=100
    )
    metadata: dict[str, str] = Field(default_factory=dict)


class RecoverRequest(BaseModel):
    """POST /admin/kill-switch/recover 请求体。"""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=2000)


class ConfirmRequest(BaseModel):
    """POST /admin/kill-switch/recover/confirm 请求体。"""

    model_config = ConfigDict(extra="forbid")

    confirm_token: str = Field(min_length=1, max_length=2000)


# ============ Endpoints ============


@router.get("/status", summary="Get kill switch status")
async def get_status(
    request: Request,
    _admin: str = Depends(require_admin_token),
) -> dict[str, Any]:
    """查询当前 Kill Switch 状态。"""
    manager = _get_manager(request)
    status = manager.get_status()
    return success_response(status.model_dump(mode="json"), trace_id=get_trace_id(request))


@router.post("/trigger", summary="Trigger kill switch")
async def trigger_kill_switch(
    request: Request,
    body: TriggerRequest,
    manager: KillSwitchManager = Depends(_get_manager),  # noqa: B008
    _admin: str = Depends(require_admin_token),  # noqa: B008
) -> dict[str, Any]:
    """触发 Kill Switch（IDLE → TRIGGERED）。"""
    event = await manager.trigger(
        scope=body.scope,
        reason=body.reason,
        actor_id=_admin[:8] + "***",  # 不回完整 token
        trigger_source=body.trigger_source,
        metadata=body.metadata,
    )
    return success_response(
        event.model_dump(mode="json"), trace_id=get_trace_id(request)
    )


@router.post("/recover", summary="Request recovery (stage 1)")
async def request_recovery(
    request: Request,
    body: RecoverRequest,
    manager: KillSwitchManager = Depends(_get_manager),  # noqa: B008
    _admin: str = Depends(require_admin_token),  # noqa: B008
) -> dict[str, Any]:
    """阶段 1：进入 RECOVERING；返回 confirm_token。"""
    try:
        event = await manager.request_recovery(
            actor_id=_admin[:8] + "***", reason=body.reason
        )
    except RuntimeError as exc:
        raise APIError(
            status_code=409,
            code=APIErrorCode.STATE_CONFLICT,
            message=str(exc),
        ) from exc
    return success_response(
        event.model_dump(mode="json"), trace_id=get_trace_id(request)
    )


@router.post("/recover/confirm", summary="Confirm recovery (stage 2)")
async def confirm_recovery(
    request: Request,
    body: ConfirmRequest,
    manager: KillSwitchManager = Depends(_get_manager),  # noqa: B008
    _admin: str = Depends(require_admin_token),  # noqa: B008
) -> dict[str, Any]:
    """阶段 2：解除冻结（RECOVERING → IDLE）。"""
    try:
        event = await manager.confirm_recovery(
            confirm_token=body.confirm_token,
            actor_id=_admin[:8] + "***",
        )
    except RuntimeError as exc:
        raise APIError(
            status_code=409,
            code=APIErrorCode.STATE_CONFLICT,
            message=str(exc),
        ) from exc
    except ValueError as exc:
        raise APIError(
            status_code=400,
            code=APIErrorCode.BUSINESS_VALIDATION,
            message=str(exc),
        ) from exc
    return success_response(
        event.model_dump(mode="json"), trace_id=get_trace_id(request)
    )


@router.post("/triggers/{name}/enable", summary="Enable a trigger")
async def enable_trigger(
    request: Request,
    name: str = Path(min_length=1, max_length=100),
    reg: TriggerRegistry = Depends(_get_trigger_registry),  # noqa: B008
    _admin: str = Depends(require_admin_token),  # noqa: B008
) -> dict[str, Any]:
    """启用指定 trigger。"""
    try:
        reg.enable(name)
    except KeyError as exc:
        raise APIError(
            status_code=404,
            code=APIErrorCode.NOT_FOUND,
            message=f"unknown trigger: {name}",
        ) from exc
    return success_response(
        {"name": name, "enabled": True}, trace_id=get_trace_id(request)
    )


@router.post("/triggers/{name}/disable", summary="Disable a trigger")
async def disable_trigger(
    request: Request,
    name: str = Path(min_length=1, max_length=100),
    reg: TriggerRegistry = Depends(_get_trigger_registry),  # noqa: B008
    _admin: str = Depends(require_admin_token),  # noqa: B008
) -> dict[str, Any]:
    """禁用指定 trigger。"""
    try:
        reg.disable(name)
    except KeyError as exc:
        raise APIError(
            status_code=404,
            code=APIErrorCode.NOT_FOUND,
            message=f"unknown trigger: {name}",
        ) from exc
    return success_response(
        {"name": name, "enabled": False}, trace_id=get_trace_id(request)
    )