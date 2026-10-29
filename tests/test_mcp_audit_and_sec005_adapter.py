"""SEC-007: 审计接入 + SEC-005 凭据适配器测试（fail-closed）"""

from datetime import datetime, timedelta

import httpx
import pytest

from src.security.credential import CredentialCDP, CredentialPDP
from src.security.mcp_connector_governance.audit import AuditEventType, AuditLogger
from src.security.mcp_connector_governance.authorization import (
    ApprovalDecision,
    AuthorizationManager,
    CredentialIssuanceError,
    SEC005CredentialProxyClient,
)
from src.security.mcp_connector_governance.lifecycle import LifecycleManager
from src.security.mcp_connector_governance.models import (
    AuthConfig,
    AuthenticationMode,
    Connector,
    ConnectorConfig,
    ConnectorIdentity,
    ConnectorLifecycleState,
    ConnectorStatus,
    SignatureVerification,
    TransportConfig,
    TransportType,
    TrustLevel,
)
from src.security.mcp_connector_governance.registry import ConnectorRegistry

S = ConnectorLifecycleState
KEY_REF = "vault://key-1"


def _connector(auth=None, trust=TrustLevel.L3_RESTRICTED_CONDITIONAL, state=S.PENDING_APPROVAL):
    config = ConnectorConfig(
        identity=ConnectorIdentity(
            connector_id="conn_1",
            organization_id="org_1",
            namespace="ns",
            display_name="Test",
            version="1.0.0",
        ),
        trust_level=trust,
        transport=TransportConfig(type=TransportType.HTTP, endpoint="https://c.example.com"),
        auth=auth or AuthConfig(mode=AuthenticationMode.NONE),
        signature=SignatureVerification(is_signed=False),
    )
    return Connector(
        config=config, status=ConnectorStatus(connector_id="conn_1", lifecycle_state=state)
    )


def _approve(scope=("invoke",), ref="appr-1", gateway=True, rbac=True):
    def provider(key_ref, connector_id, org_id):
        return ApprovalDecision(
            policy_gateway_approved=gateway,
            rbac_approved=rbac,
            rbac_scope=list(scope),
            policy_approval_ref=ref,
        )

    return provider


def _adapter(provider=None, **kw):
    pdp, cdp = CredentialPDP(), CredentialCDP()
    client = SEC005CredentialProxyClient(
        pdp, cdp, provider or _approve(), agent_svid="spiffe://p/mcp", worker_id="w1", **kw
    )
    return client, pdp, cdp


def _issue(client, ttl=600):
    return client.issue_short_lived_credential(
        key_ref=KEY_REF, connector_id="conn_1", org_id="org_1", ttl_seconds=ttl
    )


class TestLifecycleAudit:
    def _mgr(self, connector):
        registry = ConnectorRegistry()
        registry.register(connector)
        audit = AuditLogger()
        return LifecycleManager(registry, audit_logger=audit), audit

    def test_successful_transition_audited(self):
        mgr, audit = self._mgr(_connector())
        assert mgr.transition_to("conn_1", S.APPROVED_INACTIVE, "ok", triggered_by="admin")
        ev = audit.get_events()[0]
        assert ev["actor"] == "admin"
        assert ev["result"] == "success"
        assert ev["org_id"] == "org_1"
        assert ev["metadata"]["to_state"] == S.APPROVED_INACTIVE.value

    def test_activation_uses_activated_event(self):
        mgr, audit = self._mgr(_connector(state=S.APPROVED_INACTIVE))
        assert mgr.activate("conn_1", "admin")
        assert audit.get_events(event_type=AuditEventType.CONNECTOR_ACTIVATED)

    def test_revocation_uses_revoked_event(self):
        mgr, audit = self._mgr(_connector(state=S.ACTIVE))
        assert mgr.revoke("conn_1", "incident", "sec")
        assert audit.get_events(event_type=AuditEventType.CONNECTOR_REVOKED)

    def test_invalid_transition_audited_as_denied(self):
        mgr, audit = self._mgr(_connector(state=S.ACTIVE))
        assert mgr.transition_to("conn_1", S.PENDING_APPROVAL, "bad", triggered_by="x") is False
        ev = audit.get_events()[0]
        assert ev["result"] == "denied"
        assert ev["event_type"] == AuditEventType.CONNECTOR_STATE_CHANGED.value

    def test_signature_gate_block_audited_without_activated_event(self):
        mgr, audit = self._mgr(_connector(trust=TrustLevel.L2_ORG_VERIFIED))
        assert mgr.transition_to("conn_1", S.APPROVED_INACTIVE, "go", triggered_by="admin") is False
        ev = audit.get_events()[0]
        assert ev["result"] == "denied"
        assert "signature gate" in ev["metadata"]["reason"].lower()
        # 被拒绝的尝试不能出现在 "已激活" 事件里
        assert not audit.get_events(event_type=AuditEventType.CONNECTOR_ACTIVATED)

    def test_audit_failure_does_not_block_transition(self):
        class Broken(AuditLogger):
            def log_lifecycle_transition(self, **kw):
                raise OSError("disk full")

        registry = ConnectorRegistry()
        registry.register(_connector())
        mgr = LifecycleManager(registry, audit_logger=Broken())
        assert mgr.transition_to("conn_1", S.APPROVED_INACTIVE, "ok") is True

    def test_no_audit_logger_still_works(self):
        registry = ConnectorRegistry()
        registry.register(_connector())
        assert LifecycleManager(registry).transition_to("conn_1", S.APPROVED_INACTIVE, "ok")


class _Proxy:
    def __init__(self, result=None, exc=None):
        self.result, self.exc = result, exc

    def issue_short_lived_credential(self, **kw):
        if self.exc:
            raise self.exc
        return self.result


class TestAuthorizationAudit:
    def _api_key(self):
        return _connector(
            AuthConfig(mode=AuthenticationMode.API_KEY, api_key_ref=KEY_REF), state=S.ACTIVE,
        )

    def test_granted_audited(self):
        audit = AuditLogger()
        exp = datetime.utcnow() + timedelta(minutes=5)
        mgr = AuthorizationManager(
            _Proxy({"token": "SECRET-TOKEN", "expires_at": exp}), audit_logger=audit
        )
        assert mgr.prepare_credentials(self._api_key(), "org_1", "u1")
        ev = audit.get_events(event_type=AuditEventType.AUTH_GRANTED)[0]
        assert ev["actor"] == "u1" and ev["org_id"] == "org_1"
        assert "SECRET-TOKEN" not in str(audit.get_events())

    def test_denied_audited(self):
        audit = AuditLogger()
        mgr = AuthorizationManager(_Proxy(exc=RuntimeError("vault down")), audit_logger=audit)
        assert mgr.prepare_credentials(self._api_key(), "org_1", "u1") is None
        assert audit.get_events(event_type=AuditEventType.AUTH_DENIED)

    def test_audit_failure_does_not_change_result(self):
        class Broken(AuditLogger):
            def log_authorization(self, **kw):
                raise OSError("x")

        exp = datetime.utcnow() + timedelta(minutes=5)
        mgr = AuthorizationManager(_Proxy({"token": "t", "expires_at": exp}), audit_logger=Broken())
        assert mgr.prepare_credentials(self._api_key(), "org_1", "u1")["token"] == "t"

    def test_token_refresh_audited_without_token_values(self):
        audit = AuditLogger()

        def handler(request):
            return httpx.Response(500)

        mgr = AuthorizationManager(
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            audit_logger=audit,
        )
        conn = _connector(
            AuthConfig(
                mode=AuthenticationMode.OAUTH2_PKCE,
                oauth_client_id="c",
                oauth_token_endpoint="https://auth.example.com/token",
                oauth_audience="https://connector.example.com",
            ), state=S.ACTIVE,
        )
        mgr._token_cache[("org_1", "u1", "conn_1")] = {
            "access_token": "old",
            "refresh_token": "REFRESH-SECRET",
            "expires_at": datetime.utcnow() - timedelta(minutes=1),
        }
        mgr.prepare_credentials(conn, "org_1", "u1")
        ev = audit.get_events(event_type=AuditEventType.TOKEN_REFRESHED)
        assert ev and ev[0]["result"] == "failed"
        assert "REFRESH-SECRET" not in str(audit.get_events())


class TestSEC005Adapter:
    def test_issues_real_cdp_token(self):
        client, _, cdp = _adapter()
        result = _issue(client)
        assert result["token"].startswith("token_")
        assert result["expires_at"] > datetime.utcnow()
        assert cdp.get_rental_stats()["total_active_rentals"] == 1

    def test_ttl_capped_by_adapter_max(self):
        client, _, _ = _adapter(max_ttl_seconds=60)
        result = _issue(client, ttl=900)
        assert result["expires_at"] <= datetime.utcnow() + timedelta(seconds=61)

    def test_ttl_capped_by_service_default(self):
        client, _, _ = _adapter(target_service="aws")  # CDP 上限 900s
        result = _issue(client, ttl=100000)
        assert result["expires_at"] <= datetime.utcnow() + timedelta(seconds=901)

    @pytest.mark.parametrize("gateway,rbac", [(False, True), (True, False)])
    def test_pdp_denial_raises(self, gateway, rbac):
        client, _, _ = _adapter(_approve(gateway=gateway, rbac=rbac))
        with pytest.raises(CredentialIssuanceError, match="PDP rejected"):
            _issue(client)

    def test_scope_outside_rbac_raises(self):
        client, _, _ = _adapter(_approve(scope=("read",)), requested_scope=["admin"])
        with pytest.raises(CredentialIssuanceError, match="PDP rejected"):
            _issue(client)

    def test_missing_approval_ref_raises(self):
        client, _, _ = _adapter(_approve(ref=""))
        with pytest.raises(CredentialIssuanceError, match="approval reference"):
            _issue(client)

    def test_provider_exception_raises_without_leaking_message(self):
        def boom(*a):
            raise RuntimeError("db password=hunter2")

        client, _, _ = _adapter(boom)
        with pytest.raises(CredentialIssuanceError) as ei:
            _issue(client)
        assert "hunter2" not in str(ei.value)

    def test_provider_invalid_result_raises(self):
        client, _, _ = _adapter(lambda *a: True)
        with pytest.raises(CredentialIssuanceError, match="invalid decision"):
            _issue(client)

    def test_unhealthy_cdp_raises(self):
        client, _, cdp = _adapter()
        cdp.set_health(False)
        with pytest.raises(CredentialIssuanceError, match="CDP failed"):
            _issue(client)

    def test_no_token_content_raises_and_revokes(self):
        client, _, cdp = _adapter()
        original = cdp._mint_token
        cdp._mint_token = lambda *a, **k: None  # 模拟 Model A 代理模式
        try:
            with pytest.raises(CredentialIssuanceError, match="no token content"):
                _issue(client)
            # 不可用的租约必须被撤销，不能残留
            assert cdp.get_rental_stats()["total_active_rentals"] == 0
        finally:
            cdp._mint_token = original

    @pytest.mark.parametrize(
        "kw",
        [
            dict(key_ref="", connector_id="c", org_id="o", ttl_seconds=60),
            dict(key_ref="k", connector_id="", org_id="o", ttl_seconds=60),
            dict(key_ref="k", connector_id="c", org_id="", ttl_seconds=60),
            dict(key_ref="k", connector_id="c", org_id="o", ttl_seconds=0),
        ],
    )
    def test_invalid_arguments_raise(self, kw):
        client, _, _ = _adapter()
        with pytest.raises(CredentialIssuanceError):
            client.issue_short_lived_credential(**kw)

    def test_constructor_validation(self):
        pdp, cdp = CredentialPDP(), CredentialCDP()
        with pytest.raises(TypeError):
            SEC005CredentialProxyClient(pdp, cdp, None, agent_svid="a", worker_id="w")
        with pytest.raises(ValueError):
            SEC005CredentialProxyClient(pdp, cdp, _approve(), agent_svid="", worker_id="w")
        with pytest.raises(ValueError):
            SEC005CredentialProxyClient(
                pdp, cdp, _approve(), agent_svid="a", worker_id="w", max_ttl_seconds=0
            )


class TestAdapterWithAuthorizationManager:
    def test_end_to_end_api_key(self):
        client, _, _ = _adapter()
        audit = AuditLogger()
        mgr = AuthorizationManager(client, audit_logger=audit)
        conn = self._active_api_key()
        creds = mgr.prepare_credentials(conn, "org_1", "u1")
        assert creds["type"] == "api_key" and creds["token"]
        assert audit.get_events(event_type=AuditEventType.AUTH_GRANTED)

    def test_end_to_end_denied_returns_none(self):
        client, _, _ = _adapter(_approve(rbac=False))
        mgr = AuthorizationManager(client)
        conn = self._active_api_key()
        assert mgr.prepare_credentials(conn, "org_1", "u1") is None

    @staticmethod
    def _active_api_key():
        return _connector(
            AuthConfig(mode=AuthenticationMode.API_KEY, api_key_ref=KEY_REF), state=S.ACTIVE,
        )
