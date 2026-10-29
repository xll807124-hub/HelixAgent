"""
SEC-007: MCP Connector Governance - OAuth 2.1 Handler
OAuth 2.1 + PKCE (RFC 7636, S256) 授权处理器

Design Decisions (Q1):
- 强制 PKCE S256 验证
- state 绑定 + audience 验证
- 1小时短期 token + refresh token 轮转
- 异常重试 + 过期续期
"""

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from threading import RLock
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

logger = logging.getLogger(__name__)


class PKCEGenerator:
    """PKCE Code Verifier & Challenge 生成器"""

    @staticmethod
    def generate_code_verifier(length: int = 128) -> str:
        """
        生成 code_verifier (RFC 7636)

        Args:
            length: 长度 (43-128 字符)

        Returns:
            Base64URL 编码的随机字符串
        """
        if not 43 <= length <= 128:
            raise ValueError("code_verifier length must be 43-128")

        # 生成高熵随机字节
        verifier_bytes = secrets.token_bytes(96)  # 96 bytes -> 128 base64url chars
        verifier = base64.urlsafe_b64encode(verifier_bytes).decode("utf-8").rstrip("=")
        return verifier[:length]

    @staticmethod
    def generate_code_challenge(verifier: str, method: str = "S256") -> str:
        """
        生成 code_challenge

        Args:
            verifier: code_verifier
            method: 'S256' (强制) 或 'plain'

        Returns:
            code_challenge
        """
        if method == "S256":
            digest = hashlib.sha256(verifier.encode("utf-8")).digest()
            challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
            return challenge
        elif method == "plain":
            # 不推荐，仅用于测试
            logger.warning("Using plain PKCE method - not recommended for production")
            return verifier
        else:
            raise ValueError(f"Unsupported PKCE method: {method}")


class OAuth21Handler:
    """
    OAuth 2.1 授权处理器

    Features:
    - 强制 PKCE S256
    - state 验证防 CSRF
    - audience 绑定
    - Token 轮转
    """

    def __init__(
        self,
        client_id: str,
        authorization_endpoint: str,
        token_endpoint: str,
        redirect_uri: str,
        scopes: list[str],
        audience: str | None = None,
    ) -> None:
        self.client_id = client_id
        self.authorization_endpoint = authorization_endpoint
        self.token_endpoint = token_endpoint
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.audience = audience

        # PKCE 状态存储 (实际应存储在安全存储中)
        self._pkce_storage: dict[str, dict[str, Any]] = {}

    def generate_authorization_url(self) -> tuple[str, str]:
        """
        生成授权 URL

        Returns:
            (authorization_url, state)
        """
        # 生成 PKCE 参数
        code_verifier = PKCEGenerator.generate_code_verifier()
        code_challenge = PKCEGenerator.generate_code_challenge(code_verifier, "S256")

        # 生成 state (防 CSRF)
        state = secrets.token_urlsafe(32)

        # 存储 PKCE 上下文
        self._pkce_storage[state] = {
            "code_verifier": code_verifier,
            "created_at": datetime.utcnow(),
            "audience": self.audience,
        }

        # 构建授权 URL
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        if self.audience:
            params["audience"] = self.audience

        auth_url = f"{self.authorization_endpoint}?{urlencode(params)}"

        logger.info(
            "Generated OAuth authorization URL",
            extra={"client_id": self.client_id, "state": state[:8] + "...", "pkce_method": "S256"},
        )

        return auth_url, state

    async def exchange_code_for_token(self, code: str, state: str) -> dict[str, Any]:
        """
        用 authorization code 换取 access token

        Args:
            code: Authorization code
            state: State 参数

        Returns:
            Token 响应 (access_token, refresh_token, expires_in)
        """
        # 验证 state
        if state not in self._pkce_storage:
            raise ValueError("Invalid or expired state")

        pkce_context = self._pkce_storage.pop(state)

        # 检查 state 过期 (5分钟有效期)
        if datetime.utcnow() - pkce_context["created_at"] > timedelta(minutes=5):
            raise ValueError("State expired")

        code_verifier = pkce_context["code_verifier"]

        # 构建 token 请求
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": code_verifier,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_endpoint, data=token_data, timeout=10.0)

            if response.status_code != 200:
                logger.error(
                    "Token exchange failed",
                    extra={"status_code": response.status_code, "error": response.text},
                )
                raise Exception(f"Token exchange failed: {response.status_code}")

            token_response = response.json()

        logger.info(
            "Successfully exchanged code for token",
            extra={"client_id": self.client_id, "expires_in": token_response.get("expires_in")},
        )

        return token_response

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """
        刷新 access token

        Args:
            refresh_token: Refresh token

        Returns:
            新 token 响应
        """
        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_endpoint, data=token_data, timeout=10.0)

            if response.status_code != 200:
                logger.error(
                    "Token refresh failed",
                    extra={"status_code": response.status_code, "error": response.text},
                )
                raise Exception(f"Token refresh failed: {response.status_code}")

            token_response = response.json()

        logger.info("Successfully refreshed token", extra={"client_id": self.client_id})

        return token_response

    def validate_token_audience(
        self,
        token: str,
        *,
        issuer: str | None = None,
        signing_key: Any | None = None,
        algorithms: list[str] | None = None,
    ) -> bool:
        """
        验证 token 的 aud / exp / iss claim（AC2：防止 token passthrough）

        fail-closed 规则：
        - 未配置 audience：拒绝（无法证明 token 是签发给该连接器的）
        - token 不是合法 JWT（如不透明令牌）：拒绝
        - 缺少 aud 或 exp，或其中任一不匹配/已过期：拒绝
        - 配置了 issuer 时，iss 必须一致

        签名校验：
        - 提供 signing_key 时校验签名，且只允许 algorithms 中列出的算法（禁止 none）
        - 未提供 signing_key 时只做 claim 校验，不能证明令牌未被篡改。
          生产环境应通过 JWKS 传入 signing_key。

        Args:
            token: Access token
            issuer: 期望的 iss（可选）
            signing_key: 验签公钥/密钥（可选）
            algorithms: 允许的签名算法，提供 signing_key 时必填

        Returns:
            是否通过校验
        """
        if not self.audience:
            logger.warning("Audience validation refused: no audience configured")
            return False
        if not token or not isinstance(token, str):
            return False

        verify_signature = signing_key is not None
        if verify_signature and (not algorithms or "none" in [a.lower() for a in algorithms]):
            logger.error(
                "Audience validation refused: algorithms must be explicit and exclude 'none'"
            )
            return False

        # PyJWT 在 verify_signature=False 时会把 verify_exp/aud/iss 默认也关掉，这里必须显式开启
        options = {
            "verify_signature": verify_signature,
            "verify_exp": True,
            "verify_aud": True,
            "verify_iss": issuer is not None,
            "require": ["aud", "exp"] + (["iss"] if issuer else []),
        }
        try:
            jwt.decode(
                token,
                # 未验签时 PyJWT 忽略 key；传空串只为满足类型签名
                key=signing_key if signing_key is not None else "",
                algorithms=algorithms if verify_signature else None,
                audience=self.audience,
                issuer=issuer,
                options=options,  # type: ignore[arg-type]
            )
        except jwt.PyJWTError as exc:
            # 只记录异常类型，不记录 token 内容
            logger.warning(
                "Token audience validation failed",
                extra={"client_id": self.client_id, "reason": type(exc).__name__},
            )
            return False
        return True


class TokenManager:
    """
    Token 生命周期管理器

    Features:
    - 自动续期 (过期前 5 分钟)
    - Token 轮转
    - 异常重试
    """

    def __init__(self, oauth_handler: OAuth21Handler, *, org_id: str = "") -> None:
        self.oauth_handler = oauth_handler
        self.org_id = org_id
        self._tokens: dict[tuple[str, str], dict[str, Any]] = {}
        self._generations: dict[str, int] = {}
        self._blocked: set[str] = set()
        self._lock = RLock()

    def get_generation(self, connector_id: str) -> int:
        with self._lock:
            return self._generations.get(connector_id, 0)

    def store_token(
        self, connector_id: str, access_token: str, refresh_token: str, expires_in: int,
        *, expected_generation: int | None = None,
    ) -> None:
        with self._lock:
            expected = 0 if expected_generation is None else expected_generation
            if (not connector_id or not access_token or expires_in <= 0
                    or connector_id in self._blocked
                    or expected != self._generations.get(connector_id, 0)):
                raise ValueError("Credential write rejected")
            self._tokens[(self.org_id, connector_id)] = {
                "access_token": access_token, "refresh_token": refresh_token,
                "expires_at": datetime.utcnow() + timedelta(seconds=expires_in),
            }

    def invalidate_connector(self, connector_id: str) -> int:
        with self._lock:
            self._blocked.add(connector_id)
            self._generations[connector_id] = self._generations.get(connector_id, 0) + 1
            return int(self._tokens.pop((self.org_id, connector_id), None) is not None)

    async def get_valid_token(self, connector_id: str) -> str:
        with self._lock:
            key = (self.org_id, connector_id)
            if connector_id in self._blocked or key not in self._tokens:
                raise ValueError("Credentials unavailable")
            entry = self._tokens[key]
            token_data = dict(entry)
            generation = self._generations.get(connector_id, 0)
        if datetime.utcnow() + timedelta(minutes=5) >= token_data["expires_at"]:
            response = await self.oauth_handler.refresh_token(token_data["refresh_token"])
            # A late response must never resurrect the cleared entry.
            with self._lock:
                if self._tokens.get(key) is not entry:
                    raise ValueError("Credential refresh was superseded")
                self.store_token(connector_id, response["access_token"],
                                 response.get("refresh_token", token_data["refresh_token"]),
                                 response["expires_in"], expected_generation=generation)
                return str(response["access_token"])
        return str(token_data["access_token"])
