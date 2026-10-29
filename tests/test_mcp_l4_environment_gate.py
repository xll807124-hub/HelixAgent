"""
SEC-007 AC16: L4 connectors cannot be used in production, cannot access sensitive
data, and cannot use credentials, even inside the isolated evaluation environment.
"""

import pytest

from src.security.mcp_connector_governance.execution import ToolExecutor
from src.security.mcp_connector_governance.models import (
    AuthConfig,
    AuthenticationMode,
    Connector,
    ConnectorConfig,
    ConnectorIdentity,
    ConnectorLifecycleState,
    ConnectorStatus,
    ExecutionEnvironment,
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

ORG = "org_ac16"
PROD = ExecutionEnvironment.PRODUCTION
EVAL = ExecutionEnvironment.ISOLATED_EVALUATION


def _connector(level=TrustLevel.L4_UNVERIFIED_UNTRUSTED, auth=AuthenticationMode.NONE):
    identity = ConnectorIdentity(
        connector_id="conn_ac16", organization_id=ORG,
        namespace="test", display_name="AC16", version="1.0.0",
    )
    config = ConnectorConfig(
        identity=identity, trust_level=level,
        transport=TransportConfig(type=TransportType.HTTP, endpoint="https://c.example.com"),
        auth=AuthConfig(mode=auth, api_key_ref="vault://k"),
        signature=SignatureVerification(is_signed=False),
    )
    status = ConnectorStatus(
        connector_id="conn_ac16", lifecycle_state=ConnectorLifecycleState.ACTIVE
    )
    return Connector(config=config, status=status)


def _tool(sensitivity="L1"):
    return ToolSchema(
        tool_name="ac16_tool", description="t",
        input_schema=ToolInputSchema(properties={}, required=[]),
        risk_profile=ToolRiskProfile(
            risk_level="low", is_read_only=True, requires_human_approval=False,
            data_sensitivity=sensitivity, network_access_required=True,
            filesystem_access_required=False, credential_access_required=False,
        ),
        capability=ToolCapability(),
    )


def _engine(env=PROD):
    engine = PolicyEngine(environment=env)
    engine.quota_manager.initialize_org_quota(ORG, base_quota=1000.0)
    return engine


class TestEnvironmentGate:
    def test_default_environment_is_production(self):
        assert PolicyEngine().environment == PROD

    def test_l4_denied_in_production(self):
        d = _engine(PROD).evaluate_connector_access(ORG, _connector())
        assert not d.allowed
        assert d.blocked_by == "trust_level"

    def test_l4_tool_invocation_denied_in_production(self):
        d = _engine(PROD).evaluate_tool_invocation(ORG, _connector(), _tool("L1"))
        assert not d.allowed
        assert d.blocked_by == "trust_level"

    def test_l4_allowed_in_isolated_evaluation_with_nonsensitive_data(self):
        d = _engine(EVAL).evaluate_tool_invocation(ORG, _connector(), _tool("L1"))
        assert d.allowed, d.reason
        assert d.warnings  # still flagged as unverified

    @pytest.mark.parametrize("level", [
        TrustLevel.L1_PLATFORM_MANAGED, TrustLevel.L2_ORG_VERIFIED,
    ])
    def test_higher_levels_unaffected_in_production(self, level):
        d = _engine(PROD).evaluate_tool_invocation(ORG, _connector(level), _tool("L2"))
        assert d.allowed, d.reason

    def test_unknown_trust_level_is_treated_as_l4(self):
        conn = _connector()
        conn.config.trust_level = None
        d = _engine(PROD).evaluate_connector_access(ORG, conn)
        assert not d.allowed
        assert d.blocked_by == "trust_level"

    def test_unknown_trust_level_garbage_value_is_treated_as_l4(self):
        conn = _connector()
        conn.config.trust_level = "L1"  # string, not a TrustLevel
        d = _engine(PROD).evaluate_connector_access(ORG, conn)
        assert not d.allowed

    def test_environment_cannot_be_changed_by_a_call(self):
        # evaluate_* 不接受 environment 参数: 调用方无法按次声明评估环境
        with pytest.raises(TypeError):
            _engine(PROD).evaluate_connector_access(
                ORG, _connector(), environment=EVAL
            )


class TestSensitiveData:
    @pytest.mark.parametrize("sensitivity", ["L3", "L4", "l3", " L4 ", "unknown", "", "high"])
    def test_l4_denied_for_sensitive_or_unparseable_data(self, sensitivity):
        d = _engine(EVAL).evaluate_tool_invocation(ORG, _connector(), _tool(sensitivity))
        assert not d.allowed
        assert d.blocked_by == "trust_level"
        assert "sensitive" in d.reason

    @pytest.mark.parametrize("sensitivity", ["L1", "L2", "l2"])
    def test_l4_allowed_for_nonsensitive_data(self, sensitivity):
        d = _engine(EVAL).evaluate_tool_invocation(ORG, _connector(), _tool(sensitivity))
        assert d.allowed, d.reason

    def test_l3_sensitive_data_is_not_blocked_by_this_gate(self):
        d = _engine(PROD).evaluate_tool_invocation(
            ORG, _connector(TrustLevel.L3_RESTRICTED_CONDITIONAL), _tool("L3")
        )
        assert d.allowed, d.reason


class TestCredentials:
    @pytest.mark.parametrize("mode", [
        AuthenticationMode.API_KEY, AuthenticationMode.OAUTH2_PKCE, AuthenticationMode.MTLS,
    ])
    def test_l4_with_credentials_denied_even_in_evaluation(self, mode):
        d = _engine(EVAL).evaluate_connector_access(ORG, _connector(auth=mode))
        assert not d.allowed
        assert d.blocked_by == "trust_level"
        assert "credentials" in d.reason

    def test_l4_without_credentials_allowed_in_evaluation(self):
        d = _engine(EVAL).evaluate_connector_access(ORG, _connector())
        assert d.allowed, d.reason


class TestThroughExecutor:
    class _Mgr:
        def __init__(self):
            self.calls = 0

        def prepare_credentials(self, connector, org_id, user_id):
            self.calls += 1
            return {"type": "api_key", "token": "prod-secret-token"}

    @pytest.mark.asyncio
    async def test_production_l4_never_reaches_credentials_or_quota(self):
        mgr = self._Mgr()
        engine = _engine(PROD)
        ex = ToolExecutor(engine, authorization_manager=mgr)
        conn = _connector(auth=AuthenticationMode.API_KEY)
        result = await execute_approved_fixture(ex, ORG, "u1", conn, _tool("L1"), {})
        assert not result.success
        assert result.metadata["blocked_by"] == "trust_level"
        assert mgr.calls == 0
        assert engine.quota_manager.get_quota(ORG).current_usage == 0.0
        assert "prod-secret-token" not in repr(result.to_dict())

    @pytest.mark.asyncio
    async def test_evaluation_l4_credentialed_connector_never_reaches_credentials(self):
        mgr = self._Mgr()
        ex = ToolExecutor(_engine(EVAL), authorization_manager=mgr)
        conn = _connector(auth=AuthenticationMode.API_KEY)
        result = await execute_approved_fixture(ex, ORG, "u1", conn, _tool("L1"), {})
        assert not result.success
        assert result.metadata["blocked_by"] == "trust_level"
        assert mgr.calls == 0

    @pytest.mark.asyncio
    async def test_evaluation_l4_sensitive_tool_blocked_before_execution(self):
        engine = _engine(EVAL)
        ex = ToolExecutor(engine)
        result = await execute_approved_fixture(ex, ORG, "u1", _connector(), _tool("L3"), {})
        assert not result.success
        assert result.metadata["blocked_by"] == "trust_level"
        assert engine.quota_manager.get_quota(ORG).current_usage == 0.0
