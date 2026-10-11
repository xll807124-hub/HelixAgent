"""
统一响应/错误 schema（src/api/schemas/common.py）。

设计要点（对标：Cursor 后端 envelope + Anthropic 错误结构）：
- 成功：{code:0, message:"ok", data:..., trace_id}
- 失败：{code:4xxxx, message, data:null, trace_id}
- code 分段：4xxx 业务校验；403xx 权限；404xx 资源；409xx 状态冲突；422xx 参数；5xxx 内部。
"""
from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field


class APIErrorCode(IntEnum):
    """API 业务错误码。"""

    OK = 0
    # 4xxx 业务校验
    BUSINESS_VALIDATION = 40001
    # 403xx 鉴权/授权
    UNAUTHENTICATED = 40301
    PERMISSION_DENIED = 40302
    # 404xx 资源
    NOT_FOUND = 40401
    TOOL_NOT_FOUND = 40402
    # 409xx 状态冲突
    STATE_CONFLICT = 40901
    TASK_ALREADY_TERMINAL = 40902
    # 422xx 参数
    INVALID_PARAMS = 42201
    # 5xxx 内部
    INTERNAL_ERROR = 50001
    UPSTREAM_UNAVAILABLE = 50301


def _default_trace_id() -> str:
    """默认 trace_id 字段填充（在中间件注入前临时占位）。"""
    return ""


class SuccessResponse(BaseModel):
    """统一成功响应（envelope 风格）。"""

    code: int = Field(default=APIErrorCode.OK, description="0 表示成功")
    message: str = Field(default="ok", max_length=500)
    data: Any | None = None
    trace_id: str = Field(default_factory=_default_trace_id, max_length=64)


class ErrorResponse(BaseModel):
    """统一错误响应（envelope 风格）。"""

    code: int = Field(description="非 0 错误码（见 APIErrorCode）")
    message: str = Field(max_length=500)
    data: None = None
    trace_id: str = Field(default_factory=_default_trace_id, max_length=64)


def success_response(data: Any, *, trace_id: str = "", message: str = "ok") -> dict[str, Any]:
    """构造成功响应字典（FastAPI 兼容）。"""
    return {
        "code": int(APIErrorCode.OK),
        "message": message,
        "data": data,
        "trace_id": trace_id,
    }


def error_response(
    code: APIErrorCode,
    message: str,
    *,
    trace_id: str = "",
) -> dict[str, Any]:
    """构造错误响应字典。"""
    return {
        "code": int(code),
        "message": message,
        "data": None,
        "trace_id": trace_id,
    }