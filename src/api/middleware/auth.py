"""
Bearer Token 鉴权中间件（src/api/middleware/auth.py）。

单组织部署的令牌鉴权：
- 期望 `Authorization: Bearer <token>` 头；仅接受配置中的令牌
- 仅在 settings.auth_required=True 时启用（默认 True）
- AI_API_AUTH_TOKENS 是 token 到 principal ID 的 JSON 映射
- 未配置令牌时业务端点返回 503，健康检查仍可用

失败模式（AGENTS.md §7 Fail Secure）：
- 缺失 Authorization 头 → 401
- 格式错误（非 Bearer）→ 401
- Bearer 但 token 为空 → 401
- 所有 401 走 envelope 错误（不回 WWW-Authenticate 之外的任何细节）

存放在 request.state 的字段：
- principal_id: str（配置中可信的主体标识；不保存原始令牌）
"""
from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.config import APISettings
from src.api.middleware.error_handler import APIError
from src.api.middleware.trace import get_trace_id
from src.api.schemas.common import APIErrorCode, error_response

# 无需普通 bearer 鉴权的端点（探针 + OpenAPI + Admin 走独立 X-Admin-Token）
_PUBLIC_PATHS = frozenset(
    {"/health", "/ready", "/docs", "/redoc", "/openapi.json"}
)

# 前缀白名单：这些 prefix 不要求普通 bearer token（各自有独立鉴权）
_PUBLIC_PREFIXES: tuple[str, ...] = ("/admin/",)

AUTH_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "

STATE_PRINCIPAL = "principal_id"
STATE_TOKEN = "auth_token"


class BearerTokenAuthMiddleware(BaseHTTPMiddleware):
    """校验显式配置的 Bearer Token。"""

    def __init__(self, app: object, settings: APISettings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._enabled = settings.auth_required
        self._tokens = dict(settings.auth_tokens)

    def _resolve_principal(self, token: str) -> str | None:
        """只从服务端配置中取得身份，使用恒定时间比较令牌。"""
        for expected, principal in self._tokens.items():
            if hmac.compare_digest(token.encode(), expected.encode()):
                return principal
        return None

    async def dispatch(  # type: ignore[no-untyped-def, override]
        self, request: Request, call_next
    ):
        if (
            not self._enabled
            or request.url.path in _PUBLIC_PATHS
            or any(
                request.url.path.startswith(prefix) for prefix in _PUBLIC_PREFIXES
            )
        ):
            # 关闭鉴权或探针/admin 路径：放行
            return await call_next(request)

        raw = request.headers.get(AUTH_HEADER, "")
        if not raw or not raw.lower().startswith(BEARER_PREFIX.lower()):
            return self._reject(request, "missing bearer token")
        token = raw[len(BEARER_PREFIX) :].strip()
        if not token:
            return self._reject(request, "empty bearer token")

        if not self._tokens:
            return JSONResponse(
                status_code=503,
                content=error_response(
                    APIErrorCode.UPSTREAM_UNAVAILABLE,
                    "authentication is not configured",
                    trace_id=get_trace_id(request),
                ),
            )
        principal = self._resolve_principal(token)
        if principal is None:
            return self._reject(request, "invalid bearer token")
        request.state.principal_id = principal
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
