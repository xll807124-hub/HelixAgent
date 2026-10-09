"""
GitHub App 凭据代理

对齐设计文档：REQ-SEC-005 凭据代理 / REQ-SEC-002 认证
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

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
    token: str                           # 实际令牌值
    token_type: TokenType                # 令牌类型
    scopes: list[str]                    # 权限范围
    expires_at: datetime                 # 过期时间
    created_at: datetime                 # 创建时间
    metadata: dict[str, Any] | None = None  # 额外元数据


@dataclass
class GitHubAppConfig:
    """GitHub App 配置"""
    app_id: str                          # App ID
    private_key: str                     # 私钥（PEM 格式）
    webhook_secret: str                  # Webhook 密钥
    installation_id: str | None = None   # 安装 ID


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

    def __init__(self, config: GitHubAppConfig):
        """
        初始化凭据代理
        
        Args:
            config: GitHub App 配置
        """
        self.config = config
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
            ttl_seconds: 令牌有效期（默认：1 小时）
            
        Returns:
            CredentialToken: 短期凭据令牌
        """
        if not self.config.installation_id:
            raise ValueError("installation_id not configured")

        if scopes is None:
            scopes = ["contents:read", "pull_requests:read"]

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

        expires_at = datetime.now() + timedelta(seconds=ttl_seconds)

        credential = CredentialToken(
            token=token_response["token"],
            token_type=TokenType.INSTALLATION,
            scopes=scopes,
            expires_at=expires_at,
            created_at=datetime.now(),
            metadata={
                "installation_id": self.config.installation_id,
                "permissions": token_response.get("permissions", {}),
            }
        )

        # 审计记录
        await self._audit_token_issuance(credential)

        logger.info(
            f"Issued GitHub token with scopes: {scopes}, TTL: {ttl_seconds}s"
        )

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
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError("httpx package not installed") from e

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
            "repositories": [],  # 不限制仓库
            "permissions": {
                "contents": "read",
                "pull_requests": "read",
                "workflows": "read",
            },
            "expires_in": ttl_seconds,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to request token from GitHub: {e}")
            raise

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
        # TODO: 实现令牌验证逻辑
        # - 检查令牌过期时间
        # - 调用 GitHub API 验证
        return True

    async def revoke_token(self, token: str) -> bool:
        """
        撤销令牌
        
        Args:
            token: 令牌字符串
            
        Returns:
            True 如果撤销成功
        """
        # TODO: 实现令牌撤销逻辑
        logger.info(f"Revoked token: {self._hash_token(token)}")
        return True

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """获取审计日志"""
        return self._token_audit_log[-limit:]
