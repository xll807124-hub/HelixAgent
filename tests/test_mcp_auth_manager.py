"""SEC-007 AC2/AC3: AuthorizationManager 凭据代理与令牌刷新测试（fail-closed）"""

import time
from datetime import datetime, timedelta

import httpx
import jwt
import pytest

from src.security.mcp_connector_governance.authorization.auth_manager import (
    AuthorizationManager,
)
from src.security.mcp_connector_governance.models import (
    AuthenticationMode,
)
from src.security.mcp_connector_governance.models.connector import (
    AuthConfig,
    Connector,
    ConnectorConfig,
    ConnectorIdentity,
    ConnectorLifecycleState,
    ConnectorStatus,
    SignatureVerification,
    TransportConfig,
    TransportType,
)
from src.security.mcp_connector_governance.models.trust_level import TrustLevel

SECRET = "unit-test-secret-key-at-least-32-bytes-long!"
AUDIENCE = "https://connector.example.com"
TOKEN_ENDPOINT = "https://auth.example.com/token"


def _connector(auth: AuthConfig) -> Connector:
    config = ConnectorConfig(
        identity=ConnectorIdentity(
            connector_id="conn_1",
            organization_id="org_1",
            namespace="test",
            display_name="Test",
            version="1.0.0",
        ),
        trust_level=TrustLevel.L2_ORG_VERIFIED,
        transport=TransportConfig(type=TransportType.HTTP, endpoint="https://c.example.com"),
        auth=auth,
        signature=SignatureVerification(is_signed=False),
    )
    return Connector(
        config=config,
        status=ConnectorStatus(
            connector_id="conn_1", lifecycle_state=ConnectorLifecycleState.ACTIVE
        ),
    )


def _api_key_connector(ref="vault://key-1") -> Connector:
    return _connector(AuthConfig(mode=AuthenticationMode.API_KEY, api_key_ref=ref))


def _oauth_connector(**kw) -> Connector:
    params = dict(
        mode=AuthenticationMode.OAUTH2_PKCE,
        oauth_client_id="client-1",
        oauth_token_endpoint=TOKEN_ENDPOINT,
        oauth_audience=AUDIENCE,
        oauth_scopes=["read"],
    )
    params.update(kw)
    return _connector(AuthConfig(**params))


def _jwt(**overrides) -> str:
    claims = {"aud": AUDIENCE, "exp": int(time.time()) + 3600}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, SECRET, algorithm="HS256")


class _FakeProxy:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = []

    def issue_short_lived_credential(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.result


def _http_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestApiKeyViaCredentialProxy:
    def test_issues_short_lived_credential(self):
        exp = datetime.utcnow() + timedelta(minutes=10)
        proxy = _FakeProxy({"token": "tok-abc", "expires_at": exp})
        mgr = AuthorizationManager(credential_proxy_client=proxy)

        creds = mgr.prepare_credentials(_api_key_connector(), "org_1", "u1")

        assert creds == {"type": "api_key", "token": "tok-abc", "expires_at": exp}
        assert proxy.calls[0]["key_ref"] == "vault://key-1"
        assert proxy.calls[0]["ttl_seconds"] <= 900

    def test_never_returns_key_ref_placeholder(self):
        exp = datetime.utcnow() + timedelta(minutes=10)
        mgr = AuthorizationManager(_FakeProxy({"token": "t", "expires_at": exp}))
        creds = mgr.prepare_credentials(_api_key_connector(), "org_1", "u1")
        assert "key_ref" not in creds

    def test_no_proxy_fail_closed(self):
        assert (
            AuthorizationManager().prepare_credentials(_api_key_connector(), "org_1", "u1") is None
        )

    def test_missing_key_ref(self):
        proxy = _FakeProxy({"token": "t", "expires_at": datetime.utcnow() + timedelta(minutes=1)})
        mgr = AuthorizationManager(proxy)
        assert mgr.prepare_credentials(_api_key_connector(ref=None), "org_1", "u1") is None
        assert proxy.calls == []

    def test_proxy_exception_fail_closed(self):
        mgr = AuthorizationManager(_FakeProxy(exc=RuntimeError("vault down")))
        assert mgr.prepare_credentials(_api_key_connector(), "org_1", "u1") is None

    @pytest.mark.parametrize(
        "bad",
        [
            None,
            {},
            {"token": "", "expires_at": datetime.utcnow() + timedelta(minutes=1)},
            {"token": "t"},
            {"token": "t", "expires_at": "tomorrow"},
            {"token": "t", "expires_at": datetime.utcnow() - timedelta(seconds=1)},
        ],
    )
    def test_invalid_proxy_response_rejected(self, bad):
        assert (
            AuthorizationManager(_FakeProxy(bad)).prepare_credentials(
                _api_key_connector(), "org_1", "u1"
            )
            is None
        )


class TestOAuthRefresh:
    def _expired_cache(self, mgr, refresh="rt-old"):
        mgr.store_oauth_token("conn_1", "org_1", "u1", "old-at", refresh, expires_in=1)

    def test_refresh_success(self):
        new_at = _jwt()

        def handler(request: httpx.Request) -> httpx.Response:
            body = dict(x.split("=") for x in request.content.decode().split("&"))
            assert body["grant_type"] == "refresh_token"
            assert body["refresh_token"] == "rt-old"
            return httpx.Response(
                200, json={"access_token": new_at, "refresh_token": "rt-new", "expires_in": 3600}
            )

        mgr = AuthorizationManager(http_client=_http_client(handler))
        self._expired_cache(mgr)
        creds = mgr.prepare_credentials(_oauth_connector(), "org_1", "u1")

        assert creds == {"type": "oauth2", "access_token": new_at, "token_type": "Bearer"}
        assert mgr._token_cache[("org_1", "u1", "conn_1")]["refresh_token"] == "rt-new"

    def test_refresh_token_kept_when_not_rotated(self):
        new_at = _jwt()
        mgr = AuthorizationManager(
            http_client=_http_client(
                lambda r: httpx.Response(200, json={"access_token": new_at, "expires_in": 3600})
            )
        )
        self._expired_cache(mgr)
        assert mgr.prepare_credentials(_oauth_connector(), "org_1", "u1") is not None
        assert mgr._token_cache[("org_1", "u1", "conn_1")]["refresh_token"] == "rt-old"

    def test_wrong_audience_rejected(self):
        bad = _jwt(aud="https://evil.example.com")
        mgr = AuthorizationManager(
            http_client=_http_client(
                lambda r: httpx.Response(200, json={"access_token": bad, "expires_in": 3600})
            )
        )
        self._expired_cache(mgr)
        assert mgr.prepare_credentials(_oauth_connector(), "org_1", "u1") is None

    def test_no_audience_configured_rejected(self):
        mgr = AuthorizationManager(
            http_client=_http_client(
                lambda r: httpx.Response(200, json={"access_token": _jwt(), "expires_in": 3600})
            )
        )
        self._expired_cache(mgr)
        assert mgr.prepare_credentials(_oauth_connector(oauth_audience=None), "org_1", "u1") is None

    @pytest.mark.parametrize("status", [400, 401, 500])
    def test_http_error_status(self, status):
        mgr = AuthorizationManager(
            http_client=_http_client(lambda r: httpx.Response(status, json={"error": "x"}))
        )
        self._expired_cache(mgr)
        assert mgr.prepare_credentials(_oauth_connector(), "org_1", "u1") is None

    def test_network_error(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        mgr = AuthorizationManager(http_client=_http_client(handler))
        self._expired_cache(mgr)
        assert mgr.prepare_credentials(_oauth_connector(), "org_1", "u1") is None

    def test_non_json_body(self):
        mgr = AuthorizationManager(
            http_client=_http_client(lambda r: httpx.Response(200, content=b"<html>"))
        )
        self._expired_cache(mgr)
        assert mgr.prepare_credentials(_oauth_connector(), "org_1", "u1") is None

    @pytest.mark.parametrize("body", [{}, {"access_token": ""}, {"access_token": 5}, ["x"]])
    def test_missing_access_token(self, body):
        mgr = AuthorizationManager(
            http_client=_http_client(lambda r: httpx.Response(200, json=body))
        )
        self._expired_cache(mgr)
        assert mgr.prepare_credentials(_oauth_connector(), "org_1", "u1") is None

    def test_non_positive_expires_in(self):
        mgr = AuthorizationManager(
            http_client=_http_client(
                lambda r: httpx.Response(200, json={"access_token": _jwt(), "expires_in": 0})
            )
        )
        self._expired_cache(mgr)
        assert mgr.prepare_credentials(_oauth_connector(), "org_1", "u1") is None

    def test_non_https_endpoint_refused_without_request(self):
        called = []

        def handler(request):
            called.append(1)
            return httpx.Response(200, json={})

        mgr = AuthorizationManager(http_client=_http_client(handler))
        self._expired_cache(mgr)
        conn = _oauth_connector(oauth_token_endpoint="http://auth.example.com/token")
        assert mgr.prepare_credentials(conn, "org_1", "u1") is None
        assert called == []

    def test_missing_client_id(self):
        mgr = AuthorizationManager(http_client=_http_client(lambda r: httpx.Response(200, json={})))
        self._expired_cache(mgr)
        assert (
            mgr.prepare_credentials(_oauth_connector(oauth_client_id=None), "org_1", "u1") is None
        )

    def test_no_cached_token_requires_authorization(self):
        assert AuthorizationManager().prepare_credentials(_oauth_connector(), "org_1", "u1") is None
