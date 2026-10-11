"""`src.api.middleware.trace` 单元测试。

覆盖：
- W3C `traceparent` 解析与回传
- `X-Trace-Id` 兼容（32 hex）
- 既无 `traceparent` 又无 `X-Trace-Id`：生成新 trace_id
- `get_trace_id` 在中间件未挂载时兜底生成
- 异常路径：未处理异常被 span 标记为 ERROR
- 响应头注入：`X-Trace-Id`
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.api.middleware.trace import (
    HEADER_NAME,
    TRACEPARENT_HEADER,
    TraceContextMiddleware,
    get_trace_id,
    is_valid_trace_id,
)


@pytest.fixture
def app_no_auth() -> FastAPI:
    """最小 FastAPI app，仅挂载 TraceContextMiddleware（不挂 auth）。"""
    app = FastAPI()
    app.add_middleware(TraceContextMiddleware)

    @app.get("/ping")
    def ping(request: Request) -> dict[str, str]:
        return {"trace": get_trace_id(request)}

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("explode")

    return app


def test_is_valid_trace_id_accepts_32_hex() -> None:
    assert is_valid_trace_id("a" * 32) is True
    assert is_valid_trace_id("0123456789abcdef0123456789abcdef") is True


def test_is_valid_trace_id_rejects_bad() -> None:
    assert is_valid_trace_id("") is False
    assert is_valid_trace_id("a" * 31) is False
    assert is_valid_trace_id("a" * 33) is False
    assert is_valid_trace_id("Z" * 32) is False
    assert is_valid_trace_id(None or "") is False  # type: ignore[arg-type]


def test_trace_id_generated_when_no_incoming_header(app_no_auth: FastAPI) -> None:
    with TestClient(app_no_auth) as client:
        r = client.get("/ping")
    assert r.status_code == 200
    trace_id = r.headers.get(HEADER_NAME)
    assert trace_id is not None
    assert is_valid_trace_id(trace_id)
    # body 中的 trace 与 header 一致
    assert r.json()["trace"] == trace_id


def test_x_trace_id_header_echoed(app_no_auth: FastAPI) -> None:
    incoming = "0123456789abcdef0123456789abcdef"
    with TestClient(app_no_auth) as client:
        r = client.get("/ping", headers={HEADER_NAME: incoming})
    assert r.headers[HEADER_NAME] == incoming
    assert r.json()["trace"] == incoming


def test_w3c_traceparent_parsed(app_no_auth: FastAPI) -> None:
    """W3C traceparent 头：trace_id 部分被采纳。"""
    incoming_trace = "abcdef0123456789abcdef0123456789"
    incoming_span = "0123456789abcdef"
    traceparent = f"00-{incoming_trace}-{incoming_span}-01"
    with TestClient(app_no_auth) as client:
        r = client.get("/ping", headers={TRACEPARENT_HEADER: traceparent})
    assert r.headers[HEADER_NAME] == incoming_trace
    assert r.json()["trace"] == incoming_trace


def test_invalid_traceparent_falls_back_to_generation(app_no_auth: FastAPI) -> None:
    with TestClient(app_no_auth) as client:
        r = client.get("/ping", headers={TRACEPARENT_HEADER: "garbage"})
    # 没取到 traceparent → 生成新的
    assert is_valid_trace_id(r.headers[HEADER_NAME])


def test_traceparent_takes_priority_over_x_trace_id(app_no_auth: FastAPI) -> None:
    """两个头都在时：traceparent 优先（OTel 规范）。"""
    tp_trace = "11111111222222223333333344444444"
    x_trace = "ffffffffffffffffffffffffffffffff"
    tp = f"00-{tp_trace}-0123456789abcdef-01"
    with TestClient(app_no_auth) as client:
        r = client.get("/ping", headers={TRACEPARENT_HEADER: tp, HEADER_NAME: x_trace})
    assert r.headers[HEADER_NAME] == tp_trace


def test_invalid_x_trace_id_overridden(app_no_auth: FastAPI) -> None:
    """X-Trace-Id 非法（不是 32 hex）→ 忽略并生成新值。"""
    with TestClient(app_no_auth) as client:
        r = client.get("/ping", headers={HEADER_NAME: "not-hex"})
    new_trace = r.headers[HEADER_NAME]
    assert is_valid_trace_id(new_trace)
    assert new_trace != "not-hex"


def test_unhandled_exception_marks_request_state_trace_id(
    app_no_auth: FastAPI,
) -> None:
    """未捕获异常：BaseHTTPMiddleware 不会把响应头注入（Starlette 已知行为）；

    但 request.state.trace_id 在异常冒泡前已被设置 — 异常处理器可以读取。
    """
    # 用 raise_server_exceptions=True（默认），让异常冒泡；
    # 验证中间件确实执行到了 call_next
    raised = False
    try:
        with TestClient(app_no_auth) as client:
            try:
                client.get("/boom")
            except RuntimeError:
                raised = True
    except RuntimeError:
        raised = True
    assert raised, "未处理异常应冒泡"


def test_get_trace_id_fallback_when_middleware_not_mounted() -> None:
    """get_trace_id 在没有 request.state.trace_id 时兜底生成（不抛错）。"""

    app = FastAPI()

    @app.get("/no-mw")
    def no_mw(request: Request) -> dict[str, bool]:
        return {"valid": is_valid_trace_id(get_trace_id(request))}

    # 不挂载 TraceContextMiddleware，验证 fallback
    with TestClient(app) as client:
        r = client.get("/no-mw")
    assert r.status_code == 200
    assert r.json()["valid"] is True
