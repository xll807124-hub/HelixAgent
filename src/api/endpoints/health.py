"""
健康检查端点（src/api/endpoints/health.py）。

- GET /health：存活探针（不依赖下游；返回 200 即代表进程在跑）
- GET /ready：就绪探针（依赖：tool_registry 与 policy_gateway 已初始化）

设计原则（AGENTS.md §7）：
- 不依赖数据库/Redis（保留 MVP 用 MEM）
- 不回显内部状态细节（避免被指纹扫描）
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.api.middleware.trace import get_trace_id
from src.api.schemas.common import APIErrorCode

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def liveness(request: Request) -> JSONResponse:
    """存活探针：仅返回 200。"""
    trace_id = get_trace_id(request)
    return JSONResponse(
        status_code=200,
        content={"code": 0, "message": "ok", "data": {"status": "alive"}, "trace_id": trace_id},
    )


@router.get("/ready", summary="Readiness probe")
async def readiness(request: Request) -> JSONResponse:
    """就绪探针：检查关键组件是否已初始化。"""
    trace_id = get_trace_id(request)
    components: dict[str, str] = {}

    tool_registry = getattr(request.app.state, "tool_registry", None)
    components["tool_registry"] = "ok" if tool_registry is not None else "missing"

    policy_gateway = getattr(request.app.state, "policy_gateway", None)
    components["policy_gateway"] = "ok" if policy_gateway is not None else "missing"

    task_repository = getattr(request.app.state, "task_repository", None)
    components["task_repository"] = "ok" if task_repository is not None else "missing"

    all_ok = all(v == "ok" for v in components.values())
    payload = {
        "code": 0 if all_ok else int(APIErrorCode.UPSTREAM_UNAVAILABLE),
        "message": "ok" if all_ok else "not ready",
        "data": {"components": components} if all_ok else None,
        "trace_id": trace_id,
    }
    return JSONResponse(status_code=200 if all_ok else 503, content=payload)