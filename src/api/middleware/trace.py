"""
Trace 上下文中间件（src/api/middleware/trace.py）。

职责：
- 优先从请求头 `X-Trace-Id` 读取；无则生成新的 32 位 hex
- 校验格式：必须 32 位 hex（对齐 REQ-RT-006 TraceId 语义）
- 注入到 request.state.trace_id，供 endpoint / 错误响应 / 日志读取
- 响应头 `X-Trace-Id` 回传，便于客户端关联日志

设计原则：
- 不创建 span（避免引入 OTel exporter；T-5 时接入 REQ-OBS-001）
- 不依赖任何外部包（标准库 uuid）
"""
from __future__ import annotations

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# REQ-RT-006 TraceId：32 位 hex（小写）
_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

HEADER_NAME = "X-Trace-Id"
STATE_KEY = "trace_id"


def is_valid_trace_id(value: str) -> bool:
    """轻量校验：32 位 hex。"""
    return bool(_TRACE_ID_RE.match(value or ""))


def _new_trace_id() -> str:
    """生成 32 位 hex TraceId。"""
    return uuid.uuid4().hex


class TraceContextMiddleware(BaseHTTPMiddleware):
    """注入与回传 trace_id。"""

    async def dispatch(  # type: ignore[no-untyped-def, override]
        self, request: Request, call_next
    ):
        incoming = request.headers.get(HEADER_NAME, "")
        if incoming and is_valid_trace_id(incoming):
            trace_id = incoming
        else:
            trace_id = _new_trace_id()
        request.state.trace_id = trace_id
        response: Response = await call_next(request)
        response.headers[HEADER_NAME] = trace_id
        return response


def get_trace_id(request: Request) -> str:
    """从 request.state 读取 trace_id；空则兜底生成（防御中间件未挂载）。"""
    return getattr(request.state, STATE_KEY, "") or _new_trace_id()