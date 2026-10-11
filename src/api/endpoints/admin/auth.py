"""
Admin token 鉴权（src/api/endpoints/admin/auth.py）。

与普通 bearer token 不同：admin token 通过 `AI_API_ADMIN_TOKEN` 配置。
设计原则：
- 单 admin token（够 MVP）；多 token / RBAC 留给 SEC-002
- 缺失/错误 token → 403 PERMISSION_DENIED
- token 校验放在 endpoint 依赖层（保持与普通 auth 解耦）
- 通过 Depends 注入；测试时可覆盖
"""
from __future__ import annotations

import hmac
import os

from fastapi import Header

from src.api.middleware.error_handler import APIError
from src.api.schemas.common import APIErrorCode

ADMIN_TOKEN_HEADER = "X-Admin-Token"


def _expected_admin_token() -> str | None:
    """读取环境变量中的 admin token；未配置则视为禁用 admin 端点。"""
    return os.environ.get("AI_API_ADMIN_TOKEN") or None


def require_admin_token(
    x_admin_token: str | None = Header(default=None, alias=ADMIN_TOKEN_HEADER),
) -> str:
    """FastAPI 依赖：要求请求头携带有效 admin token。

    使用 hmac.compare_digest 防时序攻击。
    """
    expected = _expected_admin_token()
    if expected is None:
        raise APIError(
            status_code=503,
            code=APIErrorCode.UPSTREAM_UNAVAILABLE,
            message="admin endpoints disabled (AI_API_ADMIN_TOKEN not configured)",
        )
    if x_admin_token is None:
        raise APIError(
            status_code=403,
            code=APIErrorCode.PERMISSION_DENIED,
            message="admin token required",
        )
    if not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise APIError(
            status_code=403,
            code=APIErrorCode.PERMISSION_DENIED,
            message="invalid admin token",
        )
    return x_admin_token