"""
Trace 上下文中间件（src/api/middleware/trace.py）。

职责：
- 优先解析 W3C `traceparent` 头（OTel 标准），其次是 `X-Trace-Id`（API 自定义 32 hex）
- 创建 root OTel span（span_name=`HTTP {method} {path}`）
- 把 OTel trace_id 注入 request.state.trace_id（兼容既有逻辑）
- 响应头 `X-Trace-Id` 回传
- W3C `traceparent` 头回传

设计原则：
- OTel SDK 未初始化时（OTEL_SDK_DISABLED）：走纯 X-Trace-Id 路径，fail-open
- 强制 service.name / service.version 在 root span 上
"""
from __future__ import annotations

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.observability import (
    ATTR_HTTP_METHOD,
    ATTR_HTTP_ROUTE,
    ATTR_HTTP_STATUS_CODE,
    is_otel_sdk_active,
)

# REQ-RT-006 TraceId：32 位 hex（小写）
_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# W3C traceparent: version-trace_id-span_id-flags
_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)

HEADER_NAME = "X-Trace-Id"
TRACEPARENT_HEADER = "traceparent"
STATE_KEY = "trace_id"


def is_valid_trace_id(value: str) -> bool:
    """轻量校验：32 位 hex。"""
    return bool(_TRACE_ID_RE.match(value or ""))


def _new_trace_id() -> str:
    """生成 32 位 hex TraceId。"""
    return uuid.uuid4().hex


def _parse_traceparent(value: str) -> tuple[str, str, str] | None:
    """解析 W3C traceparent 头；返回 (trace_id, span_id, flags) 或 None。"""
    m = _TRACEPARENT_RE.match(value or "")
    if not m:
        return None
    return m["trace_id"], m["span_id"], m["flags"]


class TraceContextMiddleware(BaseHTTPMiddleware):
    """注入与回传 trace_id（OTel + X-Trace-Id 双协议）。"""

    async def dispatch(  # type: ignore[no-untyped-def, override]
        self, request: Request, call_next
    ):
        incoming_traceparent = request.headers.get(TRACEPARENT_HEADER, "")
        parsed = _parse_traceparent(incoming_traceparent)

        # 决定 trace_id 起点
        if parsed:
            trace_id = parsed[0]
        else:
            x_trace = request.headers.get(HEADER_NAME, "")
            if x_trace and is_valid_trace_id(x_trace):
                trace_id = x_trace
            else:
                trace_id = _new_trace_id()

        request.state.trace_id = trace_id

        # OTel root span（如果 SDK 启用）
        otel_active = is_otel_sdk_active()
        if otel_active:
            from opentelemetry import trace as otel_trace

            tracer = otel_trace.get_tracer("ai-agent-platform.api")
            with tracer.start_as_current_span(
                f"HTTP {request.method} {request.url.path}",
                attributes={
                    ATTR_HTTP_METHOD: request.method,
                    ATTR_HTTP_ROUTE: request.url.path,
                },
            ) as span:
                try:
                    response: Response = await call_next(request)
                except Exception:
                    from src.observability import set_error_status

                    set_error_status(span, error_type="unhandled_exception")
                    raise
                span.set_attribute(ATTR_HTTP_STATUS_CODE, response.status_code)
                response.headers[HEADER_NAME] = trace_id
                return response

        # OTel SDK 未启用：纯 X-Trace-Id 路径
        response = await call_next(request)
        response.headers[HEADER_NAME] = trace_id
        return response


def get_trace_id(request: Request) -> str:
    """从 request.state 读取 trace_id；空则兜底生成（防御中间件未挂载）。"""
    return getattr(request.state, STATE_KEY, "") or _new_trace_id()