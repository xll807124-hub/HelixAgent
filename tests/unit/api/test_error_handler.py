"""统一异常处理测试。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware.error_handler import APIError, register_exception_handlers
from src.api.schemas.common import APIErrorCode


def _make_test_app() -> FastAPI:
    """构造一个会主动 raise APIError 的小应用。"""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/api-error")
    async def trigger_api_error() -> None:
        raise APIError(
            status_code=418,
            code=APIErrorCode.BUSINESS_VALIDATION,
            message="teapot",
        )

    @app.get("/runtime-error")
    async def trigger_runtime_error() -> None:
        raise RuntimeError("boom")  # noqa: EM101

    return app


class TestAPIErrorHandler:
    """APIError → envelope。"""

    def test_api_error_envelope_shape(self) -> None:
        """APIError 必须包成 envelope。"""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api-error")
        assert r.status_code == 418
        body = r.json()
        assert body["code"] == int(APIErrorCode.BUSINESS_VALIDATION)
        assert body["message"] == "teapot"
        assert body["data"] is None

    def test_unhandled_exception_returns_500_no_stack(self) -> None:
        """未捕获异常 → 500 + 无栈泄露。"""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/runtime-error")
        assert r.status_code == 500
        body = r.json()
        assert body["code"] == int(APIErrorCode.INTERNAL_ERROR)
        assert "boom" not in body["message"]  # 关键断言：不暴露内部消息
        assert "RuntimeError" not in body["message"]  # 不暴露异常类型
