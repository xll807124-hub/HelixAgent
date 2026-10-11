"""
统一异常处理（src/api/middleware/error_handler.py）。

将未捕获异常 → APIError envelope；保留可观察性（trace_id 回传），不泄露栈/密钥。

设计原则（AGENTS.md §7）：
- 对外错误必须安全（不回栈、不回 Prompt、不回密钥）
- 对内应当可诊断且无秘密（trace_id + 日志）
- Fail Secure：未授权一律 403（即使资源不存在），避免存在性泄漏

不变量：
- 所有 HTTP 错误响应（包括 4xx/5xx）必须符合 ErrorResponse schema
- 500 类错误必须包含 trace_id
- 不在响应中暴露内部异常类型 / 栈
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.middleware.trace import get_trace_id
from src.api.schemas.common import APIErrorCode, error_response

logger = logging.getLogger(__name__)


class APIError(Exception):
    """业务级异常；可携带 HTTP 状态码与错误码。"""

    def __init__(
        self,
        *,
        status_code: int,
        code: APIErrorCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _json_error(
    *,
    status_code: int,
    code: APIErrorCode,
    message: str,
    trace_id: str,
) -> JSONResponse:
    """构造 envelope 错误响应。"""
    return JSONResponse(
        status_code=status_code,
        content=error_response(code, message, trace_id=trace_id),
    )


async def _api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """APIError → envelope 响应。"""
    trace_id = get_trace_id(request)
    return _json_error(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        trace_id=trace_id,
    )


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Starlette HTTPException → envelope 响应。

    不允许泄漏 HTTPException 的内部 detail（避免反射攻击）；统一映射到通用错误码。
    """
    trace_id = get_trace_id(request)
    code = APIErrorCode.INTERNAL_ERROR
    message = "request failed"
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        code = APIErrorCode.UNAUTHENTICATED
        message = "authentication required"
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        code = APIErrorCode.PERMISSION_DENIED
        message = "permission denied"
    elif exc.status_code == status.HTTP_404_NOT_FOUND:
        code = APIErrorCode.NOT_FOUND
        message = "resource not found"
    elif exc.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        code = APIErrorCode.INVALID_PARAMS
        message = "method not allowed"
    elif exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        code = APIErrorCode.INVALID_PARAMS
        message = "request validation failed"
    elif 400 <= exc.status_code < 500:
        code = APIErrorCode.BUSINESS_VALIDATION
        message = "bad request"
    elif exc.status_code >= 500:
        code = APIErrorCode.INTERNAL_ERROR
        message = "internal server error"
    return _json_error(
        status_code=exc.status_code, code=code, message=message, trace_id=trace_id
    )


async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic 422 校验失败 → envelope 响应（不回原始 errors 数组，避免泄漏 schema）。"""
    trace_id = get_trace_id(request)
    return _json_error(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code=APIErrorCode.INVALID_PARAMS,
        message="request body or query parameters are invalid",
        trace_id=trace_id,
    )


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底：未捕获异常 → 500 + trace_id；不暴露栈/类型。日志记录完整栈（仅服务端可见）。"""
    trace_id = get_trace_id(request)
    logger.exception(
        "unhandled exception",
        extra={"trace_id": trace_id, "path": request.url.path},
    )
    return _json_error(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=APIErrorCode.INTERNAL_ERROR,
        message="internal server error",
        trace_id=trace_id,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """注册所有异常处理器。"""
    app.add_exception_handler(APIError, _api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_handler)  # type: ignore[arg-type, misc]