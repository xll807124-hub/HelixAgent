"""
SEC-007 MCP handler: global blacklist enforcement on tools/list and tools/call.
"""

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
from src.security.mcp_connector_governance.policies import PolicyEngine
from src.security.mcp_connector_governance.protocol import MCPProtocolHandler
from src.security.mcp_connector_governance.registry import (
    ConnectorRegistry,
    ToolRegistry,
)
from tests.mcp_approval_helpers import approve_registered


def _connector(connector_id: str, namespace: str = "test") -> Connector:
    identity = ConnectorIdentity(
        connector_id=connector_id,
        organization_id="org_001",
        namespace=namespace,
        display_name=connector_id,
        version="1.0.0",
    )
    config = ConnectorConfig(
        identity=identity,
        trust_level=TrustLevel.L2_ORG_VERIFIED,
        transport=TransportConfig(type=ConnectorTransportType.HTTP),
        auth=AuthConfig(mode=AuthenticationMode.NONE),
        signature=SignatureVerification(is_signed=False),
    )
    status = ConnectorStatus(
        connector_id=connector_id,
        lifecycle_state=ConnectorLifecycleState.ACTIVE,
    )
    return Connector(config=config, status=status)


def _tool(name: str = "test_tool") -> ToolSchema:
    return ToolSchema(
        tool_name=name,
        description="Test tool",
        input_schema=ToolInputSchema(
            properties={"param1": {"type": "string"}},
            required=["param1"],
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
    engine.quota_manager.initialize_org_quota("org_001", base_quota=1000.0)
    handler = MCPProtocolHandler(
        tool_registry=tools,
        policy_engine=engine,
        tool_executor=ToolExecutor(engine),
        connector_registry=connectors,
    )
    handler.tool_executor.execute_tool = AsyncMock(wraps=handler.tool_executor.execute_tool)
    return {"connectors": connectors, "tools": tools, "engine": engine, "handler": handler}


def _add(env, connector_id: str, tool_name: str = "test_tool", namespace: str = "test"):
    env["connectors"].register(_connector(connector_id, namespace))
    env["tools"].register_tool(_tool(tool_name), connector_id)
    approve_registered(env["tools"], env["connectors"], connector_id)


async def _rpc(handler, method: str, params=None) -> dict:
    req = {"jsonrpc": "2.0", "method": method, "id": "1"}
    if params is not None:
        req["params"] = params
    raw = await handler.handle_request(json.dumps(req), org_id="org_001", user_id="u1")
    return json.loads(raw)


async def _list_names(handler) -> list:
    data = await _rpc(handler, "tools/list")
    return [t["name"] for t in data["result"]["tools"]]


class TestToolsListBlacklist:
    @pytest.mark.asyncio
    async def test_unblocked_tool_is_listed(self, env):
        _add(env, "conn_001")
        assert "test_tool" in await _list_names(env["handler"])

    @pytest.mark.asyncio
    async def test_blocked_tool_hidden(self, env):
        _add(env, "conn_001")
        env["engine"].global_blacklist.add_tool("test_tool", "bad", "admin")
        assert "test_tool" not in await _list_names(env["handler"])

    @pytest.mark.asyncio
    async def test_blocked_connector_hides_its_tool(self, env):
        _add(env, "conn_001")
        env["engine"].global_blacklist.add_connector("conn_001", "bad", "admin")
        assert "test_tool" not in await _list_names(env["handler"])

    @pytest.mark.asyncio
    async def test_blocked_namespace_hides_its_tool(self, env):
        _add(env, "conn_001", namespace="evil")
        env["engine"].global_blacklist.add_namespace("evil", "bad", "admin")
        assert "test_tool" not in await _list_names(env["handler"])

    @pytest.mark.asyncio
    async def test_tool_stays_listed_if_one_provider_is_clean(self, env):
        _add(env, "conn_bad")
        _add(env, "conn_ok")
        env["engine"].global_blacklist.add_connector("conn_bad", "bad", "admin")
        assert "test_tool" in await _list_names(env["handler"])


class TestToolsCallBlacklist:
    @pytest.mark.asyncio
    async def test_blocked_connector_cannot_be_called(self, env):
        _add(env, "conn_001")
        env["engine"].global_blacklist.add_connector("conn_001", "bad", "admin")
        data = await _rpc(
            env["handler"], "tools/call",
            {"name": "conn_001:test_tool", "arguments": {"param1": "x"}},
        )
        assert "error" in data
        assert data["error"] == {"code": -32050, "message": "Tool unavailable"}
        env["handler"].tool_executor.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_blocked_namespace_cannot_be_called(self, env):
        _add(env, "conn_001", namespace="evil")
        env["engine"].global_blacklist.add_namespace("evil", "bad", "admin")
        data = await _rpc(
            env["handler"], "tools/call",
            {"name": "conn_001:test_tool", "arguments": {"param1": "x"}},
        )
        assert "error" in data
        assert data["error"] == {"code": -32050, "message": "Tool unavailable"}
        env["handler"].tool_executor.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_blocked_tool_cannot_be_called(self, env):
        _add(env, "conn_001")
        env["engine"].global_blacklist.add_tool("test_tool", "bad", "admin")
        data = await _rpc(
            env["handler"], "tools/call",
            {"name": "conn_001:test_tool", "arguments": {"param1": "x"}},
        )
        assert "error" in data
        assert data["error"] == {"code": -32050, "message": "Tool unavailable"}
        env["handler"].tool_executor.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_connector(self, env):
        data = await _rpc(
            env["handler"], "tools/call", {"name": "nope:test_tool", "arguments": {}}
        )
        assert "error" in data
        assert data["error"] == {"code": -32050, "message": "Tool unavailable"}
        env["handler"].tool_executor.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_of_other_connector_rejected(self, env):
        _add(env, "conn_001", tool_name="tool_a")
        _add(env, "conn_002", tool_name="tool_b")
        data = await _rpc(
            env["handler"], "tools/call", {"name": "conn_001:tool_b", "arguments": {}}
        )
        assert "error" in data
        assert data["error"] == {"code": -32050, "message": "Tool unavailable"}
        env["handler"].tool_executor.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_without_connector_registry_errors(self, env):
        handler = MCPProtocolHandler(
            tool_registry=env["tools"],
            policy_engine=env["engine"],
            tool_executor=ToolExecutor(env["engine"]),
        )
        data = await _rpc(
            handler, "tools/call", {"name": "conn_001:test_tool", "arguments": {}}
        )
        assert "error" in data
        assert "registry" in data["error"]["message"].lower()
