"""
Bearer Token 鉴权中间件（src/api/middleware/auth.py）。

MVP 占位实现：
- 期望 `Authorization: Bearer <token>` 头；非空 token 视为有效
- 仅在 settings.auth_required=True 时启用（默认 True）
- 真正的 OAuth/JWT/Scope 校验留给 SEC-002 RBAC 接入时实现
- 不校验 token 签名/有效期（占位）；生产环境必须替换为 JWKS + RBAC

失败模式（AGENTS.md §7 Fail Secure）：
- 缺失 Authorization 头 → 401
- 格式错误（非 Bearer）→ 401
- Bearer 但 token 为空 → 401
- 所有 401 走 envelope 错误（不回 WWW-Authenticate 之外的任何细节）

存放在 request.state 的字段：
- principal_id: str（占位：取自 token 的派生标识）
- token: str（原始 token，便于审计/日志；不回客户端）
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.config import APISettings
from src.api.middleware.error_handler import APIError
from src.api.middleware.trace import get_trace_id
from src.api.schemas.common import APIErrorCode, error_response

# 无需鉴权的端点（探针 + OpenAPI）
_PUBLIC_PATHS = frozenset({"/health", "/ready", "/docs", "/redoc", "/openapi.json"})

AUTH_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "

STATE_PRINCIPAL = "principal_id"
STATE_TOKEN = "auth_token"


class BearerTokenAuthMiddleware(BaseHTTPMiddleware):
    """占位版 Bearer Token 鉴权。"""

    def __init__(self, app: object, settings: APISettings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._enabled = settings.auth_required

    async def _resolve_principal(self, request: Request) -> str:
        """将 bearer token 派生为稳定 principal_id（占位）。

        MVP：使用 token 派生确定 UUID（同一 token 同一 principal）。
        真正 RBAC（SEC-002）接入后改为从 JWT claims 提取。
        """
        import uuid

        token = getattr(request.state, "auth_token", "")
        # 占位：用 token 的 UUID5 命名空间生成稳定 UUID
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, token or "anonymous"))

    async def dispatch(  # type: ignore[no-untyped-def, override]
        self, request: Request, call_next
    ):
        if not self._enabled or request.url.path in _PUBLIC_PATHS:
            # 关闭鉴权或探针路径：放行
            return await call_next(request)

        raw = request.headers.get(AUTH_HEADER, "")
        if not raw or not raw.startswith(BEARER_PREFIX):
            return self._reject(request, "missing bearer token")
        token = raw[len(BEARER_PREFIX) :].strip()
        if not token:
            return self._reject(request, "empty bearer token")

        # 占位：principal_id 取 UUID5(token) 稳定映射
        request.state.principal_id = await self._resolve_principal(request)
        request.state.auth_token = token  # 仅服务端使用
        return await call_next(request)

    def _reject(self, request: Request, message: str) -> JSONResponse:
        """401 envelope。"""
        trace_id = get_trace_id(request)
        # 走 envelope 而非 raise APIError，避免中间件链顺序依赖
        return JSONResponse(
            status_code=401,
            content=error_response(
                APIErrorCode.UNAUTHENTICATED,
                "authentication required",
                trace_id=trace_id,
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )


__all__ = [
    "BEARER_PREFIX",
    "BearerTokenAuthMiddleware",
    "STATE_PRINCIPAL",
    "STATE_TOKEN",
    "APIError",  # 保留错误类引用以备 endpoint 内部使用
]