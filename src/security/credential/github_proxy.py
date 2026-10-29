"""
GitHub App 凭据代理

对齐设计文档：REQ-SEC-005 凭据代理 / REQ-SEC-002 认证
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TokenType(str, Enum):
    """凭据类型"""

    GITHUB_APP = "github_app"
    INSTALLATION = "installation"
    USER_ACCESS = "user_access"
    OAUTH = "oauth"


@dataclass
class CredentialToken:
    """凭据令牌"""

    token: str  # 实际令牌值
    token_type: TokenType  # 令牌类型
    scopes: list[str]  # 权限范围
    expires_at: datetime  # 过期时间
    created_at: datetime  # 创建时间
    metadata: dict[str, Any] | None = None  # 额外元数据


@dataclass
class GitHubAppConfig:
    """GitHub App 配置"""

    app_id: str  # App ID
    private_key: str  # 私钥（PEM 格式）
    webhook_secret: str  # Webhook 密钥
    installation_id: str | None = None  # 安装 ID


class GitHubCredentialProxy:
    """
    GitHub 凭据代理

    职责：
    1. 签发短期 GitHub App 令牌
    2. 管理令牌生命周期（创建、过期、轮换）
    3. 审计凭据使用
    4. 防止长期凭据存储

    设计原则（REQ-SEC-005）：
    - 默认签发 1 小时有效期的令牌
    - 支持细粒度的权限范围控制
    - 所有凭据操作完整审计
    """

    def __init__(self, config: GitHubAppConfig, http_client: httpx.AsyncClient | None = None):
        """
        初始化凭据代理

        Args:
            config: GitHub App 配置
        """
        self.config = config
        self._http_client = http_client
        self._jwt_cache: dict[str, str] = {}
        self._jwt_cache_ttl = 600  # JWT 缓存 10 分钟
        self._token_audit_log: list[dict] = []

    async def get_installation_token(
        self,
        scopes: list[str] | None = None,
        ttl_seconds: int = 3600,
    ) -> CredentialToken:
        """
        获取安装令牌

        Args:
            scopes: 权限范围（默认：["contents:read", "pull_requests:read"]）
            ttl_seconds: 本地允许使用的最长时间；GitHub 端过期时间由服务端决定

        Returns:
            CredentialToken: 短期凭据令牌
        """
        if not self.config.installation_id:
            raise ValueError("installation_id not configured")

        if scopes is None:
            scopes = ["contents:read", "pull_requests:read"]
        if not scopes:
            raise ValueError("At least one explicit permission is required")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")

        # 验证权限范围（防止权限提升）
        self._validate_scopes(scopes)

        # 构建 JWT
        jwt_token = await self._get_jwt_token()

        # 调用 GitHub API 获取安装令牌
        token_response = await self._request_installation_token(
            jwt_token,
            scopes,
            ttl_seconds,
        )

        token_value = token_response.get("token")
        if not isinstance(token_value, str) or not token_value:
            raise ValueError("GitHub response is missing a valid token")
        try:
            server_expiry = datetime.fromisoformat(
                token_response["expires_at"].replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError("GitHub response is missing a valid expiry") from exc
        now = datetime.now(UTC)
        if server_expiry.utcoffset() is None or server_expiry <= now:
            raise ValueError("GitHub token expiry must be a future timezone-aware timestamp")
        # GitHub controls remote expiry; ttl_seconds only bounds our local use.
        expires_at = min(server_expiry, now + timedelta(seconds=ttl_seconds))
        permissions = token_response.get("permissions", {})
        requested = dict(scope.split(":", 1) for scope in scopes)
        if not isinstance(permissions, dict) or any(
            not isinstance(level, str)
            or (
                (name != "metadata" or level != "read")
                and (
                    name not in requested
                    or level not in ({"read", "write"} if requested[name] == "write" else {"read"})
                )
            )
            for name, level in permissions.items()
        ):
            raise ValueError("GitHub returned permissions beyond the requested scope")

        credential = CredentialToken(
            token=token_value,
            token_type=TokenType.INSTALLATION,
            scopes=scopes,
            expires_at=expires_at,
            created_at=now,
            metadata={
                "installation_id": self.config.installation_id,
                "permissions": permissions,
            },
        )

        # 审计记录
        await self._audit_token_issuance(credential)

        logger.info(f"Issued GitHub token with scopes: {scopes}, TTL: {ttl_seconds}s")

        return credential

    async def _get_jwt_token(self) -> str:
        """
        生成 GitHub App JWT 令牌

        Returns:
            JWT 令牌字符串
        """
        now = int(time.time())
        cache_key = f"jwt_{self.config.app_id}_{now // 300}"  # 5 分钟缓存 key

        if cache_key in self._jwt_cache:
            return self._jwt_cache[cache_key]

        try:
            import jwt
        except ImportError as e:
            raise RuntimeError("PyJWT package not installed") from e

        # 构建 JWT payload
        payload = {
            "iat": now,
            "exp": now + 600,  # 有效期 10 分钟
            "iss": self.config.app_id,
        }

        # 签名 JWT
        try:
            token = jwt.encode(
                payload,
                self.config.private_key,
                algorithm="RS256",
            )
        except Exception as e:
            logger.error(f"JWT signing failed: {e}")
            raise

        self._jwt_cache.clear()
        self._jwt_cache[cache_key] = token
        return token

    async def _request_installation_token(
        self,
        jwt_token: str,
        scopes: list[str],
        ttl_seconds: int,
    ) -> dict[str, Any]:
        """
        向 GitHub 请求安装令牌

        Args:
            jwt_token: GitHub App JWT
            scopes: 权限范围
            ttl_seconds: 有效期

        Returns:
            API 响应字典
        """
        url = (
            f"https://api.github.com/app/installations/"
            f"{self.config.installation_id}/access_tokens"
        )

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        payload = {
            "permissions": dict(scope.split(":", 1) for scope in scopes),
        }
        response = await self._http_request("POST", url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid GitHub token response")
        return data

    async def _http_request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._http_client is not None:
            return await self._http_client.request(method, url, **kwargs)
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.request(method, url, **kwargs)

    def _validate_scopes(self, scopes: list[str]) -> None:
        """
        验证权限范围（防止权限提升）

        Args:
            scopes: 权限范围列表

        Raises:
            ValueError: 如果包含不允许的权限
        """
        # 危险权限黑名单
        dangerous_scopes = {
            "admin",
            "admin:org_hook",
            "admin:repo_hook",
            "admin:gpg_key",
            "admin:public_key",
            "delete_repo",
            "repo",
            "repo_deployment",
        }

        for scope in scopes:
            if scope in dangerous_scopes:
                raise ValueError(f"Dangerous scope not allowed: {scope}")
            parts = scope.split(":")
            if (
                len(parts) != 2
                or parts[0]
                not in {
                    "contents",
                    "pull_requests",
                    "issues",
                    "checks",
                    "statuses",
                    "actions",
                    "metadata",
                    "workflows",
                }
                or parts[1] not in {"read", "write"}
            ):
                raise ValueError(f"Unsupported scope: {scope}")

    async def _audit_token_issuance(self, credential: CredentialToken) -> None:
        """记录凭据签发审计"""
        audit_record = {
            "timestamp": datetime.now().isoformat(),
            "action": "token_issued",
            "token_type": credential.token_type.value,
            "scopes": credential.scopes,
            "expires_at": credential.expires_at.isoformat(),
            "token_hash": self._hash_token(credential.token),
        }
        self._token_audit_log.append(audit_record)
        logger.info(f"Audit: {audit_record}")

    @staticmethod
    def _hash_token(token: str) -> str:
        """对令牌进行哈希（用于审计）"""
        import hashlib

        return hashlib.sha256(token.encode()).hexdigest()[:16]

    async def is_token_valid(self, token: str) -> bool:
        """
        验证令牌是否有效

        Args:
            token: 令牌字符串

        Returns:
            True 如果令牌有效
        """
        if not token:
            return False
        try:
            response = await self._http_request(
                "GET",
                "https://api.github.com/installation/repositories",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                params={"per_page": 1},
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def revoke_token(self, token: str) -> bool:
        """
        撤销令牌

        Args:
            token: 令牌字符串

        Returns:
            True 如果撤销成功
        """
        if not token:
            return False
        try:
            response = await self._http_request(
                "DELETE",
                "https://api.github.com/installation/token",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
        except httpx.HTTPError:
            return False
        if response.status_code != 204:
            return False
        self._token_audit_log.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "token_revoked",
                "token_hash": self._hash_token(token),
            }
        )
        return True

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """获取审计日志"""
        return self._token_audit_log[-limit:]
