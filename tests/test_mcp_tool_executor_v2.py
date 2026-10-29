"""
SEC-007 ToolExecutor (v2): signature gate, quota refund, audit, real STDIO.
"""

import hashlib
import sys

import pytest

from src.security.mcp_connector_governance.execution import ToolExecutor
from src.security.mcp_connector_governance.execution.tool_executor_v2 import (
    ToolExecutionResult,
)
from src.security.mcp_connector_governance.models import (
    AuthConfig,
    AuthenticationMode,
    Connector,
    ConnectorConfig,
    ConnectorIdentity,
    ConnectorLifecycleState,
    ConnectorStatus,
    SignatureVerification,
    ToolCapability,
    ToolInputSchema,
    ToolRiskProfile,
    ToolSchema,
    TransportConfig,
    TransportType,
    TrustLevel,
)
from src.security.mcp_connector_governance.policies import PolicyEngine
from tests.mcp_approval_helpers import execute_approved_fixture

ORG = "org_001"


def _connector(trust=TrustLevel.L3_RESTRICTED_CONDITIONAL, transport=None):
    identity = ConnectorIdentity(
        connector_id="conn_001",
        organization_id=ORG,
        namespace="test",
        display_name="c",
        version="1.0.0",
    )
    config = ConnectorConfig(
        identity=identity,
        trust_level=trust,
        transport=transport or TransportConfig(type=TransportType.HTTP),
        auth=AuthConfig(mode=AuthenticationMode.NONE),
        signature=SignatureVerification(is_signed=False),
    )
    status = ConnectorStatus(
        connector_id="conn_001", lifecycle_state=ConnectorLifecycleState.ACTIVE
    )
    return Connector(config=config, status=status)


def _tool():
    return ToolSchema(
        tool_name="echo",
        description="echo",
        input_schema=ToolInputSchema(properties={"x": {"type": "string"}}, required=[]),
        risk_profile=ToolRiskProfile(
            risk_level="low",
            is_read_only=True,
            requires_human_approval=False,
            data_sensitivity="L2",
            network_access_required=False,
            filesystem_access_required=False,
            credential_access_required=False,
        ),
        capability=ToolCapability(),
    )


@pytest.fixture
def executor():
    engine = PolicyEngine()
    engine.quota_manager.initialize_org_quota(ORG, base_quota=1000.0)
    return ToolExecutor(engine)


def _usage(executor) -> float:
    return executor.policy_engine.quota_manager.get_quota(ORG).current_usage


def _mark_signed(executor, connector):
    """Record a 'valid' signature bound to the current config digest."""
    payload = executor.signing_payload(connector)
    connector.config.signature = SignatureVerification(
        is_signed=True,
        signature_format="test",
        verification_status="valid",
        signature_digest=hashlib.sha256(payload).hexdigest(),
    )


ECHO_SERVER = (
    "import sys, json\n"
    "req = json.loads(sys.stdin.readline())\n"
    "print(json.dumps({'jsonrpc': '2.0', 'id': req['id'],"
    " 'result': {'echo': req['params']['arguments']}}))\n"
)


def _stdio(command=None, args=None):
    return TransportConfig(
        type=TransportType.STDIO,
        command=command or sys.executable,
        args=args or ["-c", ECHO_SERVER],
    )


class TestSignatureGate:
    @pytest.mark.asyncio
    async def test_unsigned_l2_is_denied_without_touching_quota(self, executor):
        conn = _connector(TrustLevel.L2_ORG_VERIFIED, _stdio())
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {"x": "1"})
        assert not result.success
        assert "signature" in result.error.lower()
        assert result.metadata["blocked_by"] == "signature"
        assert _usage(executor) == 0.0

    @pytest.mark.asyncio
    async def test_signed_l2_executes(self, executor):
        conn = _connector(TrustLevel.L2_ORG_VERIFIED, _stdio())
        _mark_signed(executor, conn)
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {"x": "1"})
        assert result.success, result.error
        assert result.result == {"echo": {"x": "1"}}

    @pytest.mark.asyncio
    async def test_config_change_after_signing_is_denied(self, executor):
        conn = _connector(TrustLevel.L2_ORG_VERIFIED, _stdio())
        _mark_signed(executor, conn)
        conn.config.description = "tampered after signing"
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert "changed" in result.error.lower()
        assert _usage(executor) == 0.0

    @pytest.mark.asyncio
    async def test_invalid_signature_status_is_denied(self, executor):
        conn = _connector(TrustLevel.L1_PLATFORM_MANAGED, _stdio())
        _mark_signed(executor, conn)
        conn.config.signature.verification_status = "invalid"
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert result.metadata["blocked_by"] == "signature"

    @pytest.mark.asyncio
    async def test_l3_does_not_require_signature(self, executor):
        conn = _connector(TrustLevel.L3_RESTRICTED_CONDITIONAL, _stdio())
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {"x": "2"})
        assert result.success, result.error


class TestPolicyAndQuota:
    @pytest.mark.asyncio
    async def test_blacklisted_tool_is_denied_without_quota_use(self, executor):
        executor.policy_engine.global_blacklist.add_tool("echo", "bad", "admin")
        conn = _connector(transport=_stdio())
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert "blocked" in result.error.lower()
        assert _usage(executor) == 0.0

    @pytest.mark.asyncio
    async def test_unknown_org_has_no_quota(self, executor):
        conn = _connector(transport=_stdio())
        result = await execute_approved_fixture(executor, "org_unknown", "u1", conn, _tool(), {})
        assert not result.success

    @pytest.mark.asyncio
    async def test_successful_call_consumes_quota(self, executor):
        conn = _connector(transport=_stdio())
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        assert result.success, result.error
        assert _usage(executor) > 0.0

    @pytest.mark.asyncio
    async def test_failed_execution_refunds_quota(self, executor):
        conn = _connector(transport=_stdio(args=["-c", "import sys; sys.exit(3)"]))
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert _usage(executor) == 0.0

    @pytest.mark.asyncio
    async def test_missing_command_fails_and_refunds(self, executor):
        transport = TransportConfig(type=TransportType.STDIO)
        conn = _connector(transport=transport)
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert "no command" in result.error.lower()
        assert _usage(executor) == 0.0

    @pytest.mark.asyncio
    async def test_missing_endpoint_fails_and_refunds(self, executor):
        conn = _connector(transport=TransportConfig(type=TransportType.HTTP))
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert "no endpoint" in result.error.lower()
        assert _usage(executor) == 0.0


class TestLifecycleGate:
    """Only ACTIVE / RESTRICTED connectors may execute tools (fail-closed)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state",
        [
            ConnectorLifecycleState.DRAFT,
            ConnectorLifecycleState.PENDING_VERIFICATION,
            ConnectorLifecycleState.PENDING_APPROVAL,
            ConnectorLifecycleState.APPROVED_INACTIVE,
            ConnectorLifecycleState.PENDING_REVIEW,
            ConnectorLifecycleState.HEALTH_ANOMALY,
            ConnectorLifecycleState.PAUSED,
            ConnectorLifecycleState.REVOKED,
            ConnectorLifecycleState.EXPIRED,
        ],
    )
    async def test_non_callable_states_are_denied_without_quota_use(self, executor, state):
        conn = _connector(transport=_stdio())
        conn.status.lifecycle_state = state
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {"x": "1"})
        assert not result.success
        assert result.metadata["blocked_by"] == "lifecycle"
        assert state.value in result.error
        assert _usage(executor) == 0.0

    @pytest.mark.asyncio
    async def test_restricted_state_is_still_callable(self, executor):
        conn = _connector(transport=_stdio())
        conn.status.lifecycle_state = ConnectorLifecycleState.RESTRICTED
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {"x": "1"})
        assert result.success, result.error

    @pytest.mark.asyncio
    async def test_revoked_after_active_is_denied(self, executor):
        conn = _connector(transport=_stdio())
        assert (await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})).success
        conn.status.lifecycle_state = ConnectorLifecycleState.REVOKED
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert result.metadata["blocked_by"] == "lifecycle"

    def test_connector_blacklist_takes_precedence_over_lifecycle(self, executor):
        executor.policy_engine.global_blacklist.add_connector("conn_001", "bad", "admin")
        conn = _connector(transport=_stdio())
        conn.status.lifecycle_state = ConnectorLifecycleState.REVOKED
        decision = executor.policy_engine.evaluate_tool_invocation(ORG, conn, _tool(), {})
        assert not decision.allowed
        assert decision.blocked_by == "global_blacklist"

    def test_policy_engine_denies_paused_connector_access(self, executor):
        conn = _connector(transport=_stdio())
        conn.status.lifecycle_state = ConnectorLifecycleState.PAUSED
        decision = executor.policy_engine.evaluate_connector_access(ORG, conn)
        assert not decision.allowed
        assert decision.blocked_by == "lifecycle"


TOKEN = "short-lived-token-abc123"


class _FakeAuthManager:
    def __init__(self, credentials=None, raises=False):
        self.credentials = credentials
        self.raises = raises
        self.calls = []

    def prepare_credentials(self, connector, org_id, user_id):
        self.calls.append((connector.connector_id, org_id, user_id))
        if self.raises:
            raise RuntimeError(f"vault down, secret={TOKEN}")
        return self.credentials


# Reports whether the injected env token matches, without echoing it back.
ENV_SERVER = (
    "import sys, json, os\n"
    "req = json.loads(sys.stdin.readline())\n"
    "ok = os.environ.get('MCP_CONNECTOR_TOKEN') == " + repr(TOKEN) + "\n"
    "print(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': {'token_ok': ok}}))\n"
)


def _authed(mode, transport):
    conn = _connector(transport=transport)
    conn.config.auth = AuthConfig(mode=mode, api_key_ref="vault://k")
    return conn


class TestCredentialInjection:
    def _executor(self, auth_manager):
        engine = PolicyEngine()
        engine.quota_manager.initialize_org_quota(ORG, base_quota=1000.0)
        return ToolExecutor(engine, authorization_manager=auth_manager)

    @pytest.mark.asyncio
    async def test_auth_none_does_not_call_manager(self):
        mgr = _FakeAuthManager({})
        ex = self._executor(mgr)
        result = await execute_approved_fixture(
            ex, ORG, "u1", _connector(transport=_stdio()), _tool(), {},
        )
        assert result.success, result.error
        assert mgr.calls == []

    @pytest.mark.asyncio
    async def test_stdio_receives_token_via_env_only(self):
        mgr = _FakeAuthManager({"type": "api_key", "token": TOKEN})
        ex = self._executor(mgr)
        conn = _authed(AuthenticationMode.API_KEY, _stdio(args=["-c", ENV_SERVER]))
        result = await execute_approved_fixture(ex, ORG, "u1", conn, _tool(), {"x": "1"})
        assert result.success, result.error
        assert result.result == {"token_ok": True}
        assert mgr.calls == [("conn_001", ORG, "u1")]
        assert TOKEN not in repr(result.to_dict())

    @pytest.mark.asyncio
    async def test_http_receives_bearer_header(self, monkeypatch):
        mgr = _FakeAuthManager({"type": "oauth2", "access_token": TOKEN, "token_type": "Bearer"})
        ex = self._executor(mgr)
        seen = {}

        async def fake_execute(**kwargs):
            seen.update(kwargs)
            return ToolExecutionResult(success=True, result={})

        monkeypatch.setattr(ex.http_executor, "execute", fake_execute)
        conn = _authed(
            AuthenticationMode.OAUTH2_PKCE,
            TransportConfig(type=TransportType.HTTP, endpoint="https://c.example.com/"),
        )
        result = await execute_approved_fixture(ex, ORG, "u1", conn, _tool(), {})
        assert result.success, result.error
        assert seen["headers"] == {"Authorization": f"Bearer {TOKEN}"}

    @pytest.mark.asyncio
    async def test_no_manager_configured_is_denied_without_quota_use(self):
        ex = self._executor(None)
        conn = _authed(AuthenticationMode.API_KEY, _stdio())
        result = await execute_approved_fixture(ex, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert result.metadata["blocked_by"] == "credentials"
        assert _usage(ex) == 0.0

    @pytest.mark.asyncio
    async def test_credentials_unavailable_is_denied_without_quota_use(self):
        ex = self._executor(_FakeAuthManager(None))
        conn = _authed(AuthenticationMode.OAUTH2_PKCE, _stdio())
        result = await execute_approved_fixture(ex, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert result.metadata["blocked_by"] == "credentials"
        assert _usage(ex) == 0.0

    @pytest.mark.asyncio
    async def test_manager_exception_is_denied_and_does_not_leak_message(self):
        ex = self._executor(_FakeAuthManager(raises=True))
        conn = _authed(AuthenticationMode.API_KEY, _stdio())
        result = await execute_approved_fixture(ex, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert result.metadata["blocked_by"] == "credentials"
        assert TOKEN not in repr(result.to_dict())
        assert _usage(ex) == 0.0

    @pytest.mark.asyncio
    async def test_mtls_without_injectable_token_is_denied(self):
        mgr = _FakeAuthManager({"type": "mtls", "certificate_fingerprint": "ab:cd"})
        ex = self._executor(mgr)
        conn = _authed(AuthenticationMode.MTLS, _stdio())
        result = await execute_approved_fixture(ex, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert "cannot be injected" in result.error
        assert result.metadata["blocked_by"] == "credentials"

    @pytest.mark.asyncio
    async def test_policy_denial_happens_before_credential_preparation(self):
        mgr = _FakeAuthManager({"type": "api_key", "token": TOKEN})
        ex = self._executor(mgr)
        conn = _authed(AuthenticationMode.API_KEY, _stdio())
        conn.status.lifecycle_state = ConnectorLifecycleState.REVOKED
        result = await execute_approved_fixture(ex, ORG, "u1", conn, _tool(), {})
        assert result.metadata["blocked_by"] == "lifecycle"
        assert mgr.calls == []

    @pytest.mark.asyncio
    async def test_failed_execution_after_injection_refunds_quota(self):
        mgr = _FakeAuthManager({"type": "api_key", "token": TOKEN})
        ex = self._executor(mgr)
        conn = _authed(AuthenticationMode.API_KEY, _stdio(args=["-c", "import sys; sys.exit(3)"]))
        result = await execute_approved_fixture(ex, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert _usage(ex) == 0.0


class TestAudit:
    @pytest.mark.asyncio
    async def test_success_is_audited(self, executor):
        conn = _connector(transport=_stdio())
        await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        events = executor.audit_logger.get_events(org_id=ORG)
        assert any(e["event_type"] == "tool_invoked" and e["result"] == "success" for e in events)

    @pytest.mark.asyncio
    async def test_failure_is_audited(self, executor):
        conn = _connector(transport=_stdio(args=["-c", "import sys; sys.exit(1)"]))
        await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        events = executor.audit_logger.get_events(org_id=ORG)
        assert any(e["event_type"] == "tool_invoked" and e["result"] == "failed" for e in events)

    @pytest.mark.asyncio
    async def test_denial_is_audited(self, executor):
        conn = _connector(TrustLevel.L2_ORG_VERIFIED, _stdio())
        await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        events = executor.audit_logger.get_events(org_id=ORG)
        assert any(e["event_type"] == "policy_decision" and e["result"] == "denied" for e in events)


class TestVerifyConnectorSignature:
    @pytest.mark.asyncio
    async def test_bad_signature_marks_connector_invalid(self, executor):
        conn = _connector(TrustLevel.L2_ORG_VERIFIED, _stdio())
        ok = await executor.verify_connector_signature(
            conn, {"algorithm": "internal-pki", "signature": "AAAA", "certificate_id": "none"}
        )
        assert ok is False
        assert conn.config.signature.verification_status == "invalid"
        result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
        assert not result.success
        assert result.metadata["blocked_by"] == "signature"
