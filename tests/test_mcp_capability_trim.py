"""SEC-007 AC4: 组织白名单能力裁剪（tools/list + tools/call + PolicyEngine，fail-closed）"""

import json
from unittest.mock import AsyncMock

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
    SignatureVerification,
    ToolCapability,
    ToolInputSchema,
    ToolRiskProfile,
    ToolSchema,
    TransportConfig,
    TrustLevel,
)
from src.security.mcp_connector_governance.models import (
    TransportType as ConnectorTransportType,
)
from src.security.mcp_connector_governance.policies import (
    OrgCapabilityTrim,
    PolicyEngine,
    WhitelistScope,
)
from src.security.mcp_connector_governance.policies.capability_trimmer import (
    EffectiveTrim,
    resolve_trims,
    trim_tool_schema,
    validate_call,
)
from src.security.mcp_connector_governance.protocol import MCPProtocolHandler
from src.security.mcp_connector_governance.registry import (
    ConnectorRegistry,
    ToolRegistry,
)
from tests.mcp_approval_helpers import approve_registered

ORG = "org_001"


def _connector(connector_id: str) -> Connector:
    config = ConnectorConfig(
        identity=ConnectorIdentity(
            connector_id=connector_id,
            organization_id="org_001",
            namespace="test",
            display_name=connector_id,
            version="1.0.0",
        ),
        trust_level=TrustLevel.L2_ORG_VERIFIED,
        transport=TransportConfig(type=ConnectorTransportType.HTTP),
        auth=AuthConfig(mode=AuthenticationMode.NONE),
        signature=SignatureVerification(is_signed=False),
    )
    status = ConnectorStatus(
        connector_id=connector_id, lifecycle_state=ConnectorLifecycleState.ACTIVE
    )
    return Connector(config=config, status=status)


def _tool(name="test_tool", properties=None, required=None) -> ToolSchema:
    return ToolSchema(
        tool_name=name,
        description="Test tool",
        input_schema=ToolInputSchema(
            properties=properties
            if properties is not None
            else {"mode": {"type": "string", "enum": ["a", "b", "c"]}, "n": {"type": "integer"}},
            required=required if required is not None else [],
        ),
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
def env():
    connectors = ConnectorRegistry()
    tools = ToolRegistry()
    engine = PolicyEngine()
    engine.quota_manager.initialize_org_quota(ORG, base_quota=1000.0)
    handler = MCPProtocolHandler(
        tool_registry=tools,
        policy_engine=engine,
        tool_executor=ToolExecutor(engine),
        connector_registry=connectors,
    )
    return {"connectors": connectors, "tools": tools, "engine": engine, "handler": handler}


def _add(env, connector_id="conn_001", tool=None, whitelist=True):
    tool = tool or _tool()
    env["connectors"].register(_connector(connector_id))
    env["tools"].register_tool(tool, connector_id)
    approve_registered(env["tools"], env["connectors"], connector_id)
    if whitelist:
        env["engine"].org_whitelist.add_whitelist_entry(ORG, connector_id, trust_level_min=2)


def _trim(env, connector_id="conn_001", tool_id="test_tool", **kw):
    assert env["engine"].org_whitelist.add_capability_trim(ORG, connector_id, tool_id, **kw)


async def _rpc(handler, method, params=None):
    req = {"jsonrpc": "2.0", "method": method, "id": "1"}
    if params is not None:
        req["params"] = params
    raw = await handler.handle_request(json.dumps(req), org_id=ORG, user_id="u1")
    return json.loads(raw)


async def _listed(handler):
    data = await _rpc(handler, "tools/list")
    return {t["name"]: t for t in data["result"]["tools"]}


# ---------------------------------------------------------------- pure functions
class TestResolveAndValidate:
    def _t(self, **kw):
        return OrgCapabilityTrim(tool_id="t", **kw)

    def test_no_trims_allows_everything(self):
        eff = resolve_trims([], "t")
        assert validate_call(eff, {"x": 1}) is None

    def test_trim_for_other_tool_ignored(self):
        eff = resolve_trims([OrgCapabilityTrim(tool_id="other", allowed_methods=[])], "t")
        assert validate_call(eff, {}) is None

    def test_empty_allowed_methods_blocks_call(self):
        eff = resolve_trims([self._t(allowed_methods=[])], "t")
        assert validate_call(eff, {}) is not None

    def test_methods_without_tools_call_block(self):
        eff = resolve_trims([self._t(allowed_methods=["tools/list"])], "t")
        assert validate_call(eff, {}) is not None

    def test_methods_with_tools_call_allow(self):
        eff = resolve_trims([self._t(allowed_methods=["tools/call"])], "t")
        assert validate_call(eff, {}) is None

    def test_multiple_trims_intersect_methods(self):
        eff = resolve_trims(
            [
                self._t(allowed_methods=["tools/call", "tools/list"]),
                self._t(allowed_methods=["tools/list"]),
            ],
            "t",
        )
        assert validate_call(eff, {}) is not None

    def test_parameter_value_allowed_and_denied(self):
        eff = resolve_trims([self._t(parameter_restrictions={"mode": ["a"]})], "t")
        assert validate_call(eff, {"mode": "a"}) is None
        assert validate_call(eff, {"mode": "b"}) is not None

    def test_absent_restricted_param_is_not_rejected(self):
        eff = resolve_trims([self._t(parameter_restrictions={"mode": ["a"]})], "t")
        assert validate_call(eff, {}) is None
        assert validate_call(eff, None) is None

    def test_multiple_parameter_trims_intersect(self):
        eff = resolve_trims(
            [
                self._t(parameter_restrictions={"mode": ["a", "b"]}),
                self._t(parameter_restrictions={"mode": ["b", "c"]}),
            ],
            "t",
        )
        assert validate_call(eff, {"mode": "b"}) is None
        assert validate_call(eff, {"mode": "a"}) is not None

    def test_empty_allowed_values_forbids_param(self):
        eff = resolve_trims([self._t(parameter_restrictions={"mode": []})], "t")
        assert validate_call(eff, {"mode": "a"}) is not None

    def test_list_value_all_items_must_be_allowed(self):
        eff = resolve_trims([self._t(parameter_restrictions={"tags": ["x", "y"]})], "t")
        assert validate_call(eff, {"tags": ["x", "y"]}) is None
        assert validate_call(eff, {"tags": ["x", "z"]}) is not None

    def test_strict_type_comparison(self):
        eff = resolve_trims([self._t(parameter_restrictions={"n": [1]})], "t")
        assert validate_call(eff, {"n": 1}) is None
        assert validate_call(eff, {"n": True}) is not None
        assert validate_call(eff, {"n": "1"}) is not None

    def test_non_dict_arguments_rejected_when_restricted(self):
        eff = resolve_trims([self._t(parameter_restrictions={"mode": ["a"]})], "t")
        assert validate_call(eff, ["a"]) is not None

    def test_reason_does_not_echo_value(self):
        eff = resolve_trims([self._t(parameter_restrictions={"mode": ["a"]})], "t")
        assert "SECRET-VALUE" not in validate_call(eff, {"mode": "SECRET-VALUE"})


class TestTrimToolSchema:
    def test_no_restrictions_returns_same_tool(self):
        tool = _tool()
        assert trim_tool_schema(tool, [EffectiveTrim()]) is tool

    def test_narrows_enum_and_keeps_original_intact(self):
        tool = _tool()
        eff = resolve_trims(
            [OrgCapabilityTrim("test_tool", parameter_restrictions={"mode": ["a", "z"]})],
            "test_tool",
        )
        out = trim_tool_schema(tool, [eff])
        assert out.input_schema.properties["mode"]["enum"] == ["a"]
        assert tool.input_schema.properties["mode"]["enum"] == ["a", "b", "c"]

    def test_adds_enum_where_schema_had_none(self):
        tool = _tool()
        eff = resolve_trims(
            [OrgCapabilityTrim("test_tool", parameter_restrictions={"n": [1, 2]})], "test_tool"
        )
        out = trim_tool_schema(tool, [eff])
        assert out.input_schema.properties["n"]["enum"] == [1, 2]

    def test_required_param_without_values_makes_tool_unavailable(self):
        tool = _tool(required=["mode"])
        eff = resolve_trims(
            [OrgCapabilityTrim("test_tool", parameter_restrictions={"mode": ["z"]})], "test_tool"
        )
        assert trim_tool_schema(tool, [eff]) is None

    def test_optional_param_without_values_is_removed(self):
        tool = _tool()
        eff = resolve_trims(
            [OrgCapabilityTrim("test_tool", parameter_restrictions={"mode": ["z"]})], "test_tool"
        )
        out = trim_tool_schema(tool, [eff])
        assert "mode" not in out.input_schema.properties

    def test_all_providers_blocked_returns_none(self):
        eff = resolve_trims([OrgCapabilityTrim("test_tool", allowed_methods=[])], "test_tool")
        assert trim_tool_schema(_tool(), [eff, eff]) is None

    def test_unrestricted_provider_keeps_full_schema(self):
        restricted = resolve_trims(
            [OrgCapabilityTrim("test_tool", parameter_restrictions={"mode": ["a"]})], "test_tool"
        )
        tool = _tool()
        out = trim_tool_schema(tool, [restricted, EffectiveTrim()])
        assert out.input_schema.properties["mode"]["enum"] == ["a", "b", "c"]

    def test_union_across_providers(self):
        a = resolve_trims(
            [OrgCapabilityTrim("test_tool", parameter_restrictions={"mode": ["a"]})], "test_tool"
        )
        b = resolve_trims(
            [OrgCapabilityTrim("test_tool", parameter_restrictions={"mode": ["b"]})], "test_tool"
        )
        out = trim_tool_schema(_tool(), [a, b])
        assert out.input_schema.properties["mode"]["enum"] == ["a", "b"]


# ---------------------------------------------------------------- tools/list
class TestToolsListTrim:
    @pytest.mark.asyncio
    async def test_no_trim_lists_full_schema(self, env):
        _add(env)
        listed = await _listed(env["handler"])
        assert listed["test_tool"]["inputSchema"]["properties"]["mode"]["enum"] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_fully_restricted_tool_hidden(self, env):
        _add(env)
        _trim(env, allowed_methods=[])
        assert "test_tool" not in await _listed(env["handler"])

    @pytest.mark.asyncio
    async def test_parameter_restriction_narrows_schema(self, env):
        _add(env)
        _trim(env, parameter_restrictions={"mode": ["a", "b"]})
        listed = await _listed(env["handler"])
        assert listed["test_tool"]["inputSchema"]["properties"]["mode"]["enum"] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_trim_is_per_org(self, env):
        _add(env)
        _trim(env, allowed_methods=[])
        # An organization's trim cannot expose another organization's connector.
        raw = await env["handler"].handle_request(
            json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": "1"}),
            org_id="org_other",
            user_id="u1",
        )
        names = [t["name"] for t in json.loads(raw)["result"]["tools"]]
        assert names == []
        other = _connector("other_provider")
        other.config.identity.organization_id = "org_other"
        env["connectors"].register(other)
        env["tools"].register_tool(_tool(), "other_provider")
        approve_registered(env["tools"], env["connectors"], "other_provider")
        raw = await env["handler"].handle_request(
            json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": "2"}),
            org_id="org_other", user_id="u1",
        )
        assert json.loads(raw)["result"]["tools"][0]["name"] == "test_tool"

    @pytest.mark.asyncio
    async def test_other_provider_keeps_tool_visible(self, env):
        _add(env, "conn_001")
        _add(env, "conn_002")
        _trim(env, "conn_001", allowed_methods=[])
        assert "test_tool" in await _listed(env["handler"])

    @pytest.mark.asyncio
    async def test_excluded_provider_does_not_count(self, env):
        _add(env, "conn_001", whitelist=False)
        env["engine"].org_whitelist.add_whitelist_entry(
            ORG, "conn_001", trust_level_min=2, scope=WhitelistScope.EXCLUDE
        )
        assert "test_tool" not in await _listed(env["handler"])

    @pytest.mark.asyncio
    async def test_registry_stays_untouched(self, env):
        _add(env)
        _trim(env, parameter_restrictions={"mode": ["a"]})
        await _listed(env["handler"])
        stored = env["tools"].get_tool("test_tool")
        assert stored.input_schema.properties["mode"]["enum"] == ["a", "b", "c"]


# ---------------------------------------------------------------- tools/call
class TestToolsCallTrim:
    @pytest.mark.asyncio
    async def test_disallowed_method_rejected_before_execution(self, env):
        _add(env)
        env["handler"].tool_executor.execute_tool = AsyncMock()
        _trim(env, allowed_methods=["tools/list"])
        data = await _rpc(
            env["handler"], "tools/call", {"name": "conn_001:test_tool", "arguments": {}}
        )
        assert "error" in data
        assert data["error"] == {"code": -32050, "message": "Tool unavailable"}
        env["handler"].tool_executor.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_disallowed_parameter_rejected(self, env):
        _add(env)
        env["handler"].tool_executor.execute_tool = AsyncMock()
        _trim(env, parameter_restrictions={"mode": ["a"]})
        data = await _rpc(
            env["handler"],
            "tools/call",
            {"name": "conn_001:test_tool", "arguments": {"mode": "c"}},
        )
        assert "error" in data
        assert data["error"] == {"code": -32050, "message": "Tool unavailable"}
        env["handler"].tool_executor.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_parameter_passes_trim(self, env):
        _add(env)
        _trim(env, parameter_restrictions={"mode": ["a"]})
        data = await _rpc(
            env["handler"],
            "tools/call",
            {"name": "conn_001:test_tool", "arguments": {"mode": "a"}},
        )
        # 通过裁剪后才会进入执行器；此处连接器没有真实传输，失败原因不能是组织策略
        message = data.get("error", {}).get("message", "")
        assert data["error"]["code"] == -32051
        assert "organization policy" not in message

    @pytest.mark.asyncio
    async def test_trim_on_other_connector_does_not_affect_call(self, env):
        _add(env, "conn_001")
        _add(env, "conn_002")
        _trim(env, "conn_002", allowed_methods=[])
        data = await _rpc(
            env["handler"], "tools/call", {"name": "conn_001:test_tool", "arguments": {}}
        )
        assert data["error"]["code"] == -32051
        assert "organization policy" not in data["error"]["message"]


# ---------------------------------------------------------------- PolicyEngine (executor path)
class TestPolicyEngineTrim:
    def test_denied_by_method(self, env):
        _add(env)
        _trim(env, allowed_methods=[])
        decision = env["engine"].evaluate_tool_invocation(
            ORG, env["connectors"].get("conn_001"), _tool()
        )
        assert decision.allowed is False
        assert decision.blocked_by == "org_policy"

    def test_denied_by_parameter(self, env):
        _add(env)
        _trim(env, parameter_restrictions={"mode": ["a"]})
        connector = env["connectors"].get("conn_001")
        denied = env["engine"].evaluate_tool_invocation(ORG, connector, _tool(), {"mode": "b"})
        allowed = env["engine"].evaluate_tool_invocation(ORG, connector, _tool(), {"mode": "a"})
        assert denied.allowed is False and denied.blocked_by == "org_policy"
        assert allowed.allowed is True

    def test_parameters_omitted_keeps_backward_compatibility(self, env):
        _add(env)
        decision = env["engine"].evaluate_tool_invocation(
            ORG, env["connectors"].get("conn_001"), _tool()
        )
        assert decision.allowed is True
