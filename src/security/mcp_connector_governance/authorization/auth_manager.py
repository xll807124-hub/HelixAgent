"""
Authorization Manager

Manages connector authorization and credential preparation.
Integrates with SEC-005 (Credential Proxy) for credential management.
"""

import logging
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Protocol

import httpx

from ..audit.audit_logger import AuditEventType, AuditLogger
from ..models import (
    AuthenticationMode,
    Connector,
)
from .oauth_handler import OAuth21Handler, TokenManager

logger = logging.getLogger(__name__)

# OAuth 令牌端点请求超时（秒）
_TOKEN_REFRESH_TIMEOUT = 10.0
# 令牌端点未返回 expires_in 时的保守默认值（秒）
_DEFAULT_TOKEN_TTL = 3600


class CredentialProxyClient(Protocol):
    """
    SEC-005 凭据代理客户端接口。

    实现方负责从 Vault 取出 key_ref 对应的根凭据，并签发短期派生凭据。
    调用方（本模块）永远拿不到根凭据本身。
    """

    def issue_short_lived_credential(
        self,
        *,
        key_ref: str,
        connector_id: str,
        org_id: str,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        """返回 {"token": str, "expires_at": datetime}；失败时抛出异常。"""
        ...


class AuthorizationManager:
    """
    Manages authorization for MCP connectors.
    
    Responsibilities:
    - Prepare credentials for connector invocations
    - Manage OAuth 2.1 PKCE flows
    - Handle token refresh and revocation
    - Integrate with SEC-005 Credential Proxy
    """
    
    def __init__(
        self,
        credential_proxy_client: CredentialProxyClient | None = None,
        http_client: httpx.Client | None = None,
        audit_logger: AuditLogger | None = None,
        token_managers: list[TokenManager] | None = None,
    ) -> None:
        """
        Initialize authorization manager.
        
        Args:
            credential_proxy_client: Client for SEC-005 Credential Proxy.
                未提供时，API Key 类连接器一律拒绝（fail-closed，不使用备用密钥）。
            http_client: 用于 OAuth 令牌刷新的 HTTP 客户端（便于测试注入）。
            audit_logger: 提供时，凭据准备结果与令牌刷新都会写入审计（不记录令牌内容）。
        """
        self.credential_proxy = credential_proxy_client
        self._http_client = http_client
        self.audit_logger = audit_logger or AuditLogger()
        self._token_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._lock = RLock()
        self._generations: dict[tuple[str, str], int] = {}
        self._invalidations: dict[tuple[str, str], dict[str, Any]] = {}
        self._blocked: set[tuple[str, str]] = set()
        self._inflight: dict[tuple[str, str], int] = {}
        self._revoking: dict[tuple[str, str], int] = {}
        self._revocation_ready: dict[tuple[str, str], int] = {}
        self._managed_scopes: set[tuple[str, str]] = set()
        self._modes: dict[tuple[str, str], AuthenticationMode] = {}
        self._token_managers = list(token_managers or [])
        if any(not manager.org_id for manager in self._token_managers):
            raise ValueError("Integrated token managers require an organization")
    
    def prepare_credentials(
        self,
        connector: Connector,
        org_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """
        Prepare credentials for connector invocation.
        
        Args:
            connector: Connector requiring credentials
            org_id: Organization ID
            user_id: User ID
            
        Returns:
            Credentials dictionary or None if not available
        """
        scope = self._scope(connector.connector_id, org_id)
        with self._lock:
            if (not user_id or connector.config.identity.organization_id != org_id
                    or not connector.status.is_callable() or scope in self._blocked):
                return None
            generation = self._generations.get(scope, 0)
            self._modes[scope] = connector.config.auth.mode
            if connector.config.auth.mode == AuthenticationMode.API_KEY:
                self._managed_scopes.add(scope)
            self._inflight[scope] = self._inflight.get(scope, 0) + 1
        try:
            credentials = self._dispatch_credentials(connector, org_id, user_id)
        finally:
            with self._lock:
                self._inflight[scope] -= 1
        with self._lock:
            if (generation != self._generations.get(scope, 0) or scope in self._blocked
                    or not connector.status.is_callable()):
                return None
        if self.audit_logger is not None:
            granted = credentials is not None
            try:
                self.audit_logger.log_authorization(
                    connector_id=connector.connector_id,
                    user_id=user_id,
                    org_id=org_id,
                    auth_mode=connector.config.auth.mode.value,
                    granted=granted,
                    reason="" if granted else "credentials unavailable",
                )
            except Exception as exc:
                logger.error(f"Audit logging failed: {type(exc).__name__}")
        return credentials

    def _dispatch_credentials(
        self,
        connector: Connector,
        org_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """Select the credential preparation path for the connector's auth mode."""
        auth_config = connector.config.auth
        auth_mode = auth_config.mode
        
        if auth_mode == AuthenticationMode.OAUTH2_PKCE:
            return self._prepare_oauth_credentials(
                connector=connector,
                org_id=org_id,
                user_id=user_id,
            )
        elif auth_mode == AuthenticationMode.API_KEY:
            logger.warning(
                f"API Key auth is deprecated for connector {connector.connector_id}"
            )
            return self._prepare_api_key_credentials(
                connector=connector,
                org_id=org_id,
            )
        elif auth_mode == AuthenticationMode.BEARER_TOKEN:
            return self._prepare_bearer_token_credentials(
                connector=connector,
                org_id=org_id,
                user_id=user_id,
            )
        elif auth_mode == AuthenticationMode.MTLS:
            return self._prepare_mtls_credentials(
                connector=connector,
                org_id=org_id,
            )
        elif auth_mode == AuthenticationMode.NONE:
            return {}
        else:
            logger.error(f"Unsupported auth mode: {auth_mode}")
            return None
    
    def _prepare_oauth_credentials(
        self,
        connector: Connector,
        org_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """
        Prepare OAuth 2.1 PKCE credentials.
        
        Flow:
        1. Check token cache for valid access token
        2. If expired, refresh using refresh token
        3. If no refresh token, initiate new OAuth flow
        """
        cache_key = (org_id, user_id, connector.connector_id)
        
        # Snapshot under the same lock used by invalidation; network work stays outside.
        with self._lock:
            cached = self._token_cache.get(cache_key)
            generation = self._generations.get((org_id, connector.connector_id), 0)
        if cached and self._is_token_valid(cached):
            return {
                "type": "oauth2",
                "access_token": cached["access_token"],
                "token_type": "Bearer",
            }
        
        # Token expired or not in cache
        if cached and "refresh_token" in cached:
            # Try to refresh
            refreshed = self._refresh_oauth_token(
                connector=connector,
                refresh_token=cached["refresh_token"],
            )
            if self.audit_logger is not None:
                try:
                    self.audit_logger.log_token_refresh(
                        connector_id=connector.connector_id,
                        user_id=user_id,
                        org_id=org_id,
                        success=bool(refreshed),
                    )
                except Exception as exc:
                    logger.error(f"Audit logging failed: {type(exc).__name__}")
            if refreshed:
                with self._lock:
                    scope = (org_id, connector.connector_id)
                    if (generation != self._generations.get(scope, 0)
                            or scope in self._blocked
                            or self._token_cache.get(cache_key) is not cached):
                        return None
                    self._token_cache[cache_key] = refreshed
                return {
                    "type": "oauth2",
                    "access_token": refreshed["access_token"],
                    "token_type": "Bearer",
                }
        
        # Need new authorization
        logger.info(
            f"OAuth authorization required for connector {connector.connector_id} "
            f"(user={user_id})"
        )
        return None
    
    def _prepare_api_key_credentials(
        self,
        connector: Connector,
        org_id: str,
    ) -> dict[str, Any] | None:
        """
        Prepare API Key credentials (@deprecated).
        
        Retrieves from credential vault via SEC-005.
        """
        auth_config = connector.config.auth
        api_key_ref = auth_config.api_key_ref
        
        if not api_key_ref:
            logger.error(f"No API key reference for connector {connector.connector_id}")
            return None
        
        logger.warning(
            f"API Key auth used for connector {connector.connector_id} "
            f"(deprecated, sunset: {auth_config.api_key_deprecation_date})"
        )
        
        # AC3：根凭据只存在于 SEC-005 Vault，这里只拿短期派生凭据。
        # 代理不可用时拒绝，绝不回退到本地密钥或返回 key_ref 占位值。
        if self.credential_proxy is None:
            logger.error(
                f"Credential proxy unavailable; refusing API key auth for "
                f"connector {connector.connector_id}"
            )
            return None
        
        # 与 SEC-005 CDP 的最长租期保持一致，调用方不能要求更长
        try:
            issued = self.credential_proxy.issue_short_lived_credential(
                key_ref=api_key_ref,
                connector_id=connector.connector_id,
                org_id=org_id,
                ttl_seconds=900,
            )
        except Exception as exc:
            # 只记录异常类型，避免异常信息里带出凭据内容
            logger.error(
                f"Credential proxy failed for connector {connector.connector_id}: "
                f"{type(exc).__name__}"
            )
            return None
        
        token = issued.get("token") if isinstance(issued, dict) else None
        expires_at = issued.get("expires_at") if isinstance(issued, dict) else None
        if not token or not isinstance(expires_at, datetime) or expires_at <= datetime.utcnow():
            logger.error(
                f"Credential proxy returned invalid credential for "
                f"connector {connector.connector_id}"
            )
            return None
        
        return {
            "type": "api_key",
            "token": token,
            "expires_at": expires_at,
        }
    
    def _prepare_bearer_token_credentials(
        self,
        connector: Connector,
        org_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """Prepare Bearer token credentials."""
        # Similar to OAuth but simpler
        cache_key = (org_id, user_id, connector.connector_id)
        cached = self._token_cache.get(cache_key)
        
        if cached and self._is_token_valid(cached):
            return {
                "type": "bearer",
                "token": cached["token"],
            }
        
        logger.info(
            f"Bearer token authorization required for connector {connector.connector_id}"
        )
        return None
    
    def _prepare_mtls_credentials(
        self,
        connector: Connector,
        org_id: str,
    ) -> dict[str, Any] | None:
        """Prepare mTLS credentials."""
        auth_config = connector.config.auth
        cert_fingerprint = auth_config.certificate_fingerprint
        
        if not cert_fingerprint:
            logger.error(
                f"No certificate fingerprint for connector {connector.connector_id}"
            )
            return None
        
        return {
            "type": "mtls",
            "certificate_fingerprint": cert_fingerprint,
        }
    
    def _refresh_oauth_token(
        self,
        connector: Connector,
        refresh_token: str,
    ) -> dict[str, Any] | None:
        """
        Refresh OAuth access token.
        
        Args:
            connector: Connector
            refresh_token: Refresh token
            
        Returns:
            New token data or None if refresh failed
        """
        auth_config = connector.config.auth
        token_endpoint = auth_config.oauth_token_endpoint
        client_id = auth_config.oauth_client_id
        
        if not token_endpoint or not client_id:
            logger.error("OAuth token endpoint or client_id not configured")
            return None
        
        # OAuth 2.1 要求令牌端点使用 TLS
        if not token_endpoint.lower().startswith("https://"):
            logger.error(
                f"Refusing token refresh over non-HTTPS endpoint for "
                f"connector {connector.connector_id}"
            )
            return None
        
        logger.info(f"Refreshing OAuth token for connector {connector.connector_id}")
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
        try:
            if self._http_client is not None:
                response = self._http_client.post(
                    token_endpoint, data=data, timeout=_TOKEN_REFRESH_TIMEOUT
                )
            else:
                with httpx.Client() as client:
                    response = client.post(
                        token_endpoint, data=data, timeout=_TOKEN_REFRESH_TIMEOUT
                    )
            if response.status_code != 200:
                logger.error(
                    f"Token refresh failed for connector {connector.connector_id}: "
                    f"HTTP {response.status_code}"
                )
                return None
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error(
                f"Token refresh error for connector {connector.connector_id}: "
                f"{type(exc).__name__}"
            )
            return None
        
        access_token = body.get("access_token") if isinstance(body, dict) else None
        if not access_token or not isinstance(access_token, str):
            logger.error("Token refresh response missing access_token")
            return None
        
        # AC2：刷新得到的令牌同样必须绑定到该连接器的 audience，防止 token passthrough
        validator = OAuth21Handler(
            client_id=client_id,
            authorization_endpoint=auth_config.oauth_authorization_endpoint or "",
            token_endpoint=token_endpoint,
            redirect_uri="",
            scopes=list(auth_config.oauth_scopes),
            audience=auth_config.oauth_audience,
        )
        if not validator.validate_token_audience(access_token):
            logger.error(
                f"Refreshed token failed audience validation for "
                f"connector {connector.connector_id}"
            )
            return None
        
        try:
            expires_in = int(body.get("expires_in", _DEFAULT_TOKEN_TTL))
        except (TypeError, ValueError):
            expires_in = _DEFAULT_TOKEN_TTL
        if expires_in <= 0:
            return None
        
        now = datetime.utcnow()
        return {
            "access_token": access_token,
            # 刷新令牌轮转：服务端返回新的就用新的，否则沿用旧的
            "refresh_token": body.get("refresh_token") or refresh_token,
            "expires_at": now + timedelta(seconds=expires_in),
            "created_at": now,
        }
    
    def _is_token_valid(self, token_data: dict[str, Any]) -> bool:
        """
        Check if cached token is still valid.
        
        Args:
            token_data: Cached token data
            
        Returns:
            True if token is valid
        """
        expires_at = token_data.get("expires_at")
        if not expires_at:
            return False
        
        # Add 5 minute buffer
        return datetime.utcnow() < expires_at - timedelta(minutes=5)
    
    def store_oauth_token(
        self,
        connector_id: str,
        org_id: str,
        user_id: str,
        access_token: str,
        refresh_token: str | None = None,
        expires_in: int = 3600,
        *,
        expected_generation: int | None = None,
    ) -> None:
        """
        Store OAuth token in cache.
        
        Args:
            connector_id: Connector ID
            org_id: Organization ID
            user_id: User ID
            access_token: Access token
            refresh_token: Optional refresh token
            expires_in: Token lifetime in seconds
        """
        cache_key = (org_id, user_id, connector_id)
        
        token_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": datetime.utcnow() + timedelta(seconds=expires_in),
            "created_at": datetime.utcnow(),
        }
        
        scope = self._scope(connector_id, org_id)
        with self._lock:
            generation = self._generations.get(scope, 0)
            expected = 0 if expected_generation is None else expected_generation
            if (not user_id or not isinstance(access_token, str) or not access_token
                    or expires_in <= 0 or scope in self._blocked or expected != generation):
                raise ValueError("Credential write rejected")
            self._modes[scope] = AuthenticationMode.OAUTH2_PKCE
            self._token_cache[cache_key] = token_data

        logger.info(
            f"Stored OAuth token for connector {connector_id} "
            f"(user={user_id}, expires_in={expires_in}s)"
        )
    
    def revoke_credentials(
        self,
        connector_id: str,
        org_id: str,
        user_id: str,
    ) -> bool:
        """
        Revoke credentials for a connector.
        
        Args:
            connector_id: Connector ID
            org_id: Organization ID
            user_id: User ID
            
        Returns:
            True if revocation succeeded
        """
        cache_key = (org_id, user_id, connector_id)
        
        with self._lock:
            return self._token_cache.pop(cache_key, None) is not None
    
    def check_authorization_status(
        self,
        connector: Connector,
        org_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """
        Check authorization status for a connector.
        
        Args:
            connector: Connector
            org_id: Organization ID
            user_id: User ID
            
        Returns:
            Status dictionary
        """
        scope = self._scope(connector.connector_id, org_id)
        with self._lock:
            if (connector.config.identity.organization_id != org_id
                    or not connector.status.is_callable() or scope in self._blocked):
                return {"authorized": False, "reason": "Credentials unavailable"}
            cache_key = (org_id, user_id, connector.connector_id)
            cached = self._token_cache.get(cache_key)

        if not cached:
            return {
                "authorized": False,
                "reason": "No credentials found",
            }
        
        if not self._is_token_valid(cached):
            return {
                "authorized": False,
                "reason": "Credentials expired",
                "expires_at": cached.get("expires_at"),
            }
        
        return {
            "authorized": True,
            "expires_at": cached.get("expires_at"),
            "created_at": cached.get("created_at"),
        }


    @staticmethod
    def _scope(connector_id: str, org_id: str) -> tuple[str, str]:
        if (not isinstance(connector_id, str) or not connector_id
                or not isinstance(org_id, str) or not org_id):
            raise ValueError("Connector and organization are required")
        return org_id, connector_id

    def get_credential_generation(self, connector_id: str, org_id: str) -> int:
        with self._lock:
            return self._generations.get(self._scope(connector_id, org_id), 0)

    def begin_invalidation(
        self, connector_id: str, org_id: str, auth_mode: AuthenticationMode | None = None,
        *, prior_unconfigured: bool = False,
    ) -> dict[str, Any]:
        """Local stop/clear only. The lifecycle caller holds this lock during state change."""
        scope = self._scope(connector_id, org_id)
        with self._lock:
            self._blocked.add(scope)
            generation = self._generations.get(scope, 0) + 1
            self._generations[scope] = generation
            mode = self._modes.get(scope, auth_mode or AuthenticationMode.API_KEY)
            self._modes[scope] = mode
            if mode == AuthenticationMode.API_KEY:
                self._managed_scopes.add(scope)
            keys = [k for k in self._token_cache if (k[0], k[2]) == scope]
            for key in keys:
                del self._token_cache[key]
            cleared = len(keys)
            for manager in self._token_managers:
                if manager.org_id == org_id:
                    cleared += manager.invalidate_connector(connector_id)
            previous = self._invalidations.get(scope, {})
            if cleared:
                status = "unsupported"  # Cached OAuth/Bearer credentials have no remote revoker.
            elif mode == AuthenticationMode.NONE:
                status = "not_required"
            elif mode == AuthenticationMode.API_KEY:
                revoker = getattr(self.credential_proxy, "revoke_connector_credentials", None)
                status = "partial" if callable(revoker) else "unconfigured"
            else:
                status = "unsupported"
            # An unsupported/unconfigured earlier credential cannot be made safe by changing mode.
            if previous.get("credential_revocation_status") in ("unsupported", "unconfigured"):
                status = previous["credential_revocation_status"]
            if prior_unconfigured:
                # Late assembly cannot prove historical leases were revoked.
                status = "unconfigured"
            result = {"connector_id": connector_id, "org_id": org_id,
                      "generation": generation, "local_invalidated": True,
                      "cleared_count": previous.get("cleared_count", 0) + cleared,
                      "credential_revocation_status": status, "pending_count": 0,
                      "retryable": status == "partial", "audit_recorded": False,
                      "error_code": None}
            self._invalidations[scope] = result
            return dict(result)

    def invalidate_connector_credentials(
        self, connector_id: str, org_id: str, reason: str, actor: str,
    ) -> dict[str, Any]:
        if not reason or not actor:
            raise ValueError("Invalidation reason and actor are required")
        self.begin_invalidation(connector_id, org_id)
        return self.finish_invalidation(connector_id, org_id, actor, retry=True)

    def finish_invalidation(
        self, connector_id: str, org_id: str, actor: str, *, retry: bool = False,
    ) -> dict[str, Any]:
        scope = self._scope(connector_id, org_id)
        with self._lock:
            result = dict(self._invalidations[scope])
            managed = scope in self._managed_scopes
            if managed and retry:
                self._revoking[scope] = self._revoking.get(scope, 0) + 1
            ready = self._revocation_ready.get(scope) == result["generation"]
        status = result["credential_revocation_status"]
        result["pending_count"] = 0
        acknowledged = False
        if managed and (retry or ready):
            method = "revoke_connector_credentials" if retry else "get_revocation_status"
            try:
                callback = getattr(self.credential_proxy, method)
                outcome = (callback(connector_id, org_id, "MCP credential invalidation")
                           if retry else callback(connector_id, org_id))
                if (not isinstance(outcome, dict)
                        or outcome.get("credential_revocation_status") not in (
                            "complete", "partial")
                        or type(outcome.get("pending_count")) is not int
                        or outcome["pending_count"] < 0
                        or (outcome["credential_revocation_status"] == "complete"
                            and outcome["pending_count"] != 0)):
                    raise ValueError("Invalid revocation acknowledgement")
                result.update({k: outcome[k] for k in
                               ("credential_revocation_status", "pending_count")})
                result["error_code"] = None
                acknowledged = True
            except Exception:
                result.update(credential_revocation_status="partial", pending_count=1,
                              error_code="revocation_unconfirmed")
            # Local caches with no external revoker remain unsupported even if managed leases clear.
            if status in ("unsupported", "unconfigured"):
                result["credential_revocation_status"] = status
        elif managed:
            result["pending_count"] = 1  # No revocation attempt has finished for this generation.
        with self._lock:
            if managed and retry:
                self._revoking[scope] -= 1
            if result["generation"] != self._generations[scope]:
                return dict(self._invalidations[scope])
            if managed and retry and acknowledged:
                self._revocation_ready[scope] = result["generation"]
            result["pending_count"] += self._inflight.get(scope, 0) + self._revoking.get(scope, 0)
            if result["pending_count"] and result["credential_revocation_status"] == "complete":
                result["credential_revocation_status"] = "partial"
            result["retryable"] = result["credential_revocation_status"] == "partial"
            result["audit_recorded"] = False
            try:
                self.audit_logger.log_event(
                    AuditEventType.AUTH_DENIED, actor, "connector", connector_id,
                    "credential_invalidation", result["credential_revocation_status"],
                    metadata={k: result[k] for k in ("generation", "cleared_count", "pending_count",
                                                   "credential_revocation_status")}, org_id=org_id,
                )
                result["audit_recorded"] = True
            except Exception:
                result["error_code"] = "invalidation_audit_unavailable"
            self._invalidations[scope] = result
            return dict(result)

    def resume_credentials(self, connector_id: str, org_id: str) -> bool:
        scope = self._scope(connector_id, org_id)
        with self._lock:
            result = self._invalidations.get(scope)
            if result is None:
                return True
            if (result["credential_revocation_status"] not in ("not_required", "complete")
                    or not result["local_invalidated"] or not result["audit_recorded"]
                    or self._inflight.get(scope, 0) or self._revoking.get(scope, 0)):
                return False
            if result["credential_revocation_status"] == "complete":
                try:
                    resume = getattr(self.credential_proxy, "resume_connector_credentials", None)
                    if not callable(resume):
                        return False
                    if resume(connector_id, org_id) is not True:
                        return False
                except Exception:
                    return False
            self._blocked.discard(scope)
            return True
