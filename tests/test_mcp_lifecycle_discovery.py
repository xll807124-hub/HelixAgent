"""SEC-007: lifecycle changes must affect discovery and execution together."""

import asyncio
import json
import threading
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from src.security.mcp_connector_governance.execution import ToolExecutor
from src.security.mcp_connector_governance.execution.tool_executor_v2 import ToolExecutionResult
from src.security.mcp_connector_governance.lifecycle import LifecycleManager
from src.security.mcp_connector_governance.models import (
    AuthConfig,
    AuthenticationMode,
    Connector,
    ConnectorConfig,
    ConnectorIdentity,
    ConnectorStatus,
    SignatureVerification,
    ToolSchema,
    TransportConfig,
    TransportType,
    TrustLevel,
)
from src.security.mcp_connector_governance.models import (
    ConnectorLifecycleState as State,
)
from src.security.mcp_connector_governance.policies import PolicyEngine, WhitelistScope
from src.security.mcp_connector_governance.protocol import MCPProtocolHandler
from src.security.mcp_connector_governance.registry import ConnectorRegistry, ToolRegistry
from tests.mcp_approval_helpers import approve_registered

ORG = "org_lifecycle"


def tool(description="Echo"):
    return ToolSchema.from_mcp_tool_definition(
        {
            "name": "echo",
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["read", "write"]},
                },
                "required": ["mode"],
            },
        }
    )


def connector(cid="conn_a", state=State.ACTIVE):
    return Connector(
        config=ConnectorConfig(
            identity=ConnectorIdentity(cid, ORG, "test", cid, "1.0.0"),
            trust_level=TrustLevel.L3_RESTRICTED_CONDITIONAL,
            transport=TransportConfig(type=TransportType.HTTP, endpoint="https://example.com/mcp"),
            auth=AuthConfig(mode=AuthenticationMode.NONE),
            signature=SignatureVerification(is_signed=False),
        ),
        status=ConnectorStatus(connector_id=cid, lifecycle_state=state),
    )


@pytest.fixture
def env():
    connectors, tools, engine = ConnectorRegistry(), ToolRegistry(), PolicyEngine()
    engine.quota_manager.initialize_org_quota(ORG, base_quota=1000)
    executor = ToolExecutor(engine)
    handler = MCPProtocolHandler(tools, engine, executor, connectors)
    return connectors, tools, engine, executor, handler


def add(env, cid="conn_a", state=State.ACTIVE, definition=None, auth=None, endpoint=None):
    conn = connector(cid, state)
    if auth is not None:
        conn.config.auth = auth
    if endpoint is not None:
        conn.config.transport.endpoint = endpoint
    env[0].register(conn)
    env[1].register_tool(definition or tool(), cid)
    approve_registered(env[1], env[0], cid)
    return conn


async def rpc(env, method="tools/list", name="conn_a:echo", arguments=None):
    params = (
        {}
        if method == "tools/list"
        else {
            "name": name,
            "arguments": arguments or {"mode": "read"},
        }
    )
    return json.loads(
        await env[4].handle_request(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 73,
                    "method": method,
                    "params": params,
                }
            ),
            ORG,
            "user_1",
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [*State, "unknown", None])
async def test_discovery_and_direct_call_share_lifecycle_gate(env, state):
    add(env, state=state)
    env[3].execute_tool = AsyncMock(return_value=ToolExecutionResult(success=True, result="ok"))
    listing = await rpc(env)
    allowed = state in (State.ACTIVE, State.RESTRICTED)
    assert bool(listing["result"]["tools"]) is allowed
    response = await rpc(env, "tools/call")
    assert response["id"] == 73
    if allowed:
        assert "result" in response
        env[3].execute_tool.assert_awaited_once()
    else:
        assert response["error"] == {"code": -32050, "message": "Tool unavailable"}
        env[3].execute_tool.assert_not_called()
        assert env[3].audit_logger.get_events()[0]["result"] == "denied"
    assert env[2].quota_manager.get_quota(ORG).current_usage == 0


@pytest.mark.asyncio
async def test_pause_repeated_calls_resume_and_revoke(env):
    add(env)
    manager = LifecycleManager(env[0], audit_logger=env[3].audit_logger)
    env[3]._execute = AsyncMock(return_value=ToolExecutionResult(success=True, result="ok"))
    assert len((await rpc(env))["result"]["tools"]) == 1
    assert "result" in await rpc(env, "tools/call")
    usage = env[2].quota_manager.get_quota(ORG).current_usage
    assert manager.pause("conn_a", "maintenance", "admin")
    for _ in range(3):
        assert (await rpc(env))["result"]["tools"] == []
        assert (await rpc(env, "tools/call"))["error"]["code"] == -32050
    assert env[3]._execute.await_count == 1
    assert env[2].quota_manager.get_quota(ORG).current_usage == usage
    assert manager.resume("conn_a", "admin")
    assert len((await rpc(env))["result"]["tools"]) == 1
    assert "result" in await rpc(env, "tools/call")
    assert manager.revoke("conn_a", "incident", "admin")
    assert (await rpc(env))["result"]["tools"] == []
    assert (await rpc(env, "tools/call"))["error"]["code"] == -32050
    assert env[3]._execute.await_count == 2
    assert env[3].audit_logger.get_events()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["registry", "connector", "association", "all"])
async def test_missing_registration_fails_closed(env, missing):
    add(env)
    if missing == "registry":
        env[4].connector_registry = None
    elif missing == "connector":
        env[0].remove("conn_a")
    elif missing == "association":
        env[1].unregister_connector("conn_a")
    else:
        env[0].remove("conn_a")
        env[1].unregister_connector("conn_a")
    listing = await rpc(env)
    call = await rpc(env, "tools/call")
    if missing == "registry":
        assert listing["error"]["code"] == call["error"]["code"] == -32603
    else:
        assert listing["result"]["tools"] == []
        assert call["error"] == {"code": -32050, "message": "Tool unavailable"}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["tools/list", "tools/call"])
async def test_registry_failure_does_not_expose_secrets_or_fallback(
    env, monkeypatch, caplog, method
):
    add(env)

    def fail(_):
        raise RuntimeError("private-credential-sentinel")

    monkeypatch.setattr(env[0], "get", fail)
    env[3].execute_tool = AsyncMock()
    response = await rpc(env, method)
    assert response["error"]["code"] == -32603
    assert "private-credential-sentinel" not in json.dumps(response) + caplog.text
    env[3].execute_tool.assert_not_called()


@pytest.mark.asyncio
async def test_paused_provider_cannot_widen_visible_parameters(env):
    add(env)
    add(env, "conn_b", State.PAUSED)
    env[2].org_whitelist.add_whitelist_entry(ORG, "conn_a", trust_level_min=3)
    env[2].org_whitelist.add_capability_trim(
        ORG,
        "conn_a",
        "echo",
        parameter_restrictions={"mode": ["read"]},
    )
    listed = (await rpc(env))["result"]["tools"]
    assert listed[0]["inputSchema"]["properties"]["mode"]["enum"] == ["read"]
    env[0].update_status("conn_b", State.ACTIVE)
    assert (await rpc(env))["result"]["tools"][0]["inputSchema"]["properties"]["mode"]["enum"] == [
        "read",
        "write",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("difference", ["description", "schema", "risk", "version"])
async def test_ambiguous_definitions_hidden_until_one_provider_disabled(env, difference, caplog):
    a = tool("visible description")
    b = deepcopy(a)
    if difference == "description":
        b.description = "hidden provider description"
    elif difference == "schema":
        b.input_schema.properties["other"] = {"type": "boolean"}
    elif difference == "risk":
        b.risk_profile.risk_level = "high"
    else:
        b.version = "2.0.0"
    add(env, definition=a)
    add(env, "conn_b", definition=b)
    assert (await rpc(env))["result"]["tools"] == []
    assert "ambiguous" in caplog.text.lower()
    env[0].update_status("conn_b", State.PAUSED)
    listed = (await rpc(env))["result"]["tools"]
    assert listed == [
        {"name": "echo", "description": a.description, "inputSchema": a.input_schema.to_dict()}
    ]


@pytest.mark.asyncio
async def test_direct_call_uses_provider_definition_not_global_latest(env):
    a, b = tool("provider A"), tool("provider B")
    b.input_schema.properties["other"] = {"type": "integer"}
    add(env, definition=a)
    add(env, "conn_b", definition=b)
    env[3].execute_tool = AsyncMock(return_value=ToolExecutionResult(success=True))
    assert "result" in await rpc(env, "tools/call")
    assert (
        env[3].execute_tool.await_args.kwargs["tool"].compute_full_hash() == a.compute_full_hash()
    )
    assert "result" in await rpc(env, "tools/call", "conn_b:echo")
    assert (
        env[3].execute_tool.await_args.kwargs["tool"].compute_full_hash() == b.compute_full_hash()
    )


def test_provider_definition_updates_and_unregister_preserves_other_provider():
    registry = ToolRegistry()
    first, changed = tool("v1 description"), tool("v2 description")
    registry.register_tool(first, "a")
    registry.register_tool(first, "b")
    registry.register_tool(changed, "a")
    assert registry.get_tool_for_connector("a", "echo").description == "v2 description"
    assert registry.get_tool_for_connector("b", "echo").description == "v1 description"
    assert registry.get_tool_for_connector("unknown", "echo") is None
    assert registry.get_tool_for_connector("a", "unknown") is None
    registry.unregister_connector("a")
    assert registry.get_tool_for_connector("a", "echo") is None
    assert registry.get_tool_for_connector("b", "echo").description == "v1 description"
    assert registry.get_tool("echo") is not None
    registry.unregister_connector("b")
    assert registry.get_tool("echo") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_state", [State.PAUSED, State.REVOKED, State.EXPIRED, "unknown"])
async def test_pause_during_credential_wait_prevents_transport_and_quota(env, stop_state):
    conn = add(env, auth=AuthConfig(mode=AuthenticationMode.OAUTH2_PKCE))
    started, release = threading.Event(), threading.Event()

    class DelayedCredentials:
        def prepare_credentials(self, *args):
            started.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test synchronization timeout")
            return {"access_token": "synthetic-test-token"}

    env[3].authorization_manager = DelayedCredentials()
    env[3]._execute = AsyncMock(return_value=ToolExecutionResult(success=True))
    pending = asyncio.create_task(
        env[3].execute_tool(ORG, "user_1", conn, tool(), {"mode": "read"})
    )
    try:
        assert await asyncio.to_thread(started.wait, 5)
        conn.status.lifecycle_state = stop_state
    finally:
        release.set()
        result = await asyncio.wait_for(pending, timeout=5)
    assert result.success is False
    assert result.metadata["blocked_by"] == "lifecycle"
    env[3]._execute.assert_not_called()
    assert env[2].quota_manager.get_quota(ORG).current_usage == 0
    assert "synthetic-test-token" not in str(env[3].audit_logger.get_events())


def test_provider_snapshot_cannot_be_mutated_by_registration_input_or_reader():
    registry = ToolRegistry()
    original = tool()
    registry.register_tool(original, "a")
    original.description = "changed after registration"
    original.input_schema.properties.clear()
    fetched = registry.get_tool_for_connector("a", "echo")
    assert fetched.description == "Echo"
    fetched.input_schema.properties.clear()
    assert "mode" in registry.get_tool_for_connector("a", "echo").input_schema.properties


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unknown", None])
async def test_direct_executor_initial_unknown_state_returns_denial(env, state):
    conn = add(env, state=state)
    env[3]._execute = AsyncMock()
    result = await env[3].execute_tool(ORG, "user_1", conn, tool(), {})
    assert result.success is False
    assert result.metadata["blocked_by"] == "lifecycle"
    env[3]._execute.assert_not_called()
    assert env[2].quota_manager.get_quota(ORG).current_usage == 0


@pytest.mark.asyncio
async def test_reregistration_changes_only_selected_provider(env):
    add(env)
    revised = tool("Updated description")
    env[1].register_tool(revised, "conn_a")
    assert (await rpc(env))["result"]["tools"] == []
    approve_registered(env[1], env[0], "conn_a")
    gov = env[1].governance
    gov.complete_review(gov.snapshot(ORG, "conn_a"), ["echo"],
                        actor="fixture-reviewer", approval_ref="fixture-reviewed")
    assert LifecycleManager(env[0]).transition_to("conn_a", State.ACTIVE, "review complete")
    listed = (await rpc(env))["result"]["tools"]
    assert listed[0]["description"] == "Updated description"


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["provider", "definition"])
async def test_orphaned_catalog_entries_are_hidden(env, monkeypatch, missing):
    add(env)
    if missing == "provider":
        monkeypatch.setattr(env[1], "list_connectors_for_tool", lambda _: [])
    else:
        monkeypatch.setattr(env[1], "get_tool_for_connector", lambda *_: None)
    assert (await rpc(env))["result"]["tools"] == []


@pytest.mark.asyncio
async def test_fully_trimmed_provider_does_not_contribute_ambiguous_definition(env):
    add(env)
    add(env, "conn_b", definition=tool("Other definition"))
    env[2].org_whitelist.add_whitelist_entry(ORG, "conn_b", trust_level_min=3)
    env[2].org_whitelist.add_capability_trim(ORG, "conn_b", "echo", allowed_methods=[])
    assert (await rpc(env))["result"]["tools"][0]["description"] == "Echo"
    assert (await rpc(env, "tools/call", "conn_b:echo"))["error"]["code"] == -32050


@pytest.mark.asyncio
async def test_rejection_audit_failure_keeps_call_closed(env, monkeypatch, caplog):
    add(env, state=State.PAUSED)

    def fail(*args):
        raise OSError("secret-audit-destination")

    monkeypatch.setattr(env[3].audit_logger, "log_policy_decision", fail)
    env[3].execute_tool = AsyncMock()
    assert (await rpc(env, "tools/call"))["error"]["code"] == -32603
    env[3].execute_tool.assert_not_called()
    assert "secret-audit-destination" not in caplog.text


@pytest.mark.asyncio
async def test_real_http_pause_and_resume_do_not_dispatch_stale_calls(env):
    """Exercise the protocol handler, lifecycle manager and real outbound HTTP together."""
    requests = []

    async def receive(request):
        payload = await request.json()
        requests.append(payload)
        return web.json_response({"jsonrpc": "2.0", "id": payload["id"], "result": "ok"})

    app = web.Application()
    app.router.add_post("/mcp/tools/call", receive)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        add(env, endpoint=f"http://127.0.0.1:{runner.addresses[0][1]}")
        env[3].http_executor.allow_private_networks = True  # Only this local test server.
        manager = LifecycleManager(env[0], audit_logger=env[3].audit_logger)
        assert "result" in await rpc(env, "tools/call")
        assert len(requests) == 1
        usage = env[2].quota_manager.get_quota(ORG).current_usage
        assert manager.pause("conn_a", "maintenance", "admin")
        assert (await rpc(env))["result"]["tools"] == []
        for _ in range(3):
            assert (await rpc(env, "tools/call"))["error"]["code"] == -32050
        assert len(requests) == 1
        assert env[2].quota_manager.get_quota(ORG).current_usage == usage
        assert manager.resume("conn_a", "admin")
        assert len((await rpc(env))["result"]["tools"]) == 1
        assert "result" in await rpc(env, "tools/call")
        assert len(requests) == 2
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_unqualified_call_name_rejected_before_dispatch(env):
    add(env)
    env[3].execute_tool = AsyncMock()
    assert (await rpc(env, "tools/call", "echo"))["error"]["code"] == -32050
    env[3].execute_tool.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("deny_by", ["namespace", "organization"])
async def test_direct_executor_keeps_platform_and_organization_denials(env, deny_by):
    conn = add(env)
    if deny_by == "namespace":
        env[2].global_blacklist.add_namespace("test", "blocked", "admin")
    else:
        env[2].org_whitelist.add_whitelist_entry(
            ORG,
            "conn_a",
            trust_level_min=3,
            scope=WhitelistScope.EXCLUDE,
        )
    env[3]._execute = AsyncMock()
    result = await env[3].execute_tool(ORG, "user_1", conn, tool(), {})
    assert not result.success
    expected = "global_blacklist" if deny_by == "namespace" else "org_policy"
    assert result.metadata["blocked_by"] == expected
    env[3]._execute.assert_not_called()


@pytest.mark.asyncio
async def test_quota_exhausted_during_preparation_never_dispatches(env):
    conn = add(env, auth=AuthConfig(mode=AuthenticationMode.OAUTH2_PKCE))

    class ExhaustQuota:
        def prepare_credentials(self, *args):
            quota = env[2].quota_manager.get_quota(ORG)
            quota.current_usage = 1000
            return {"access_token": "synthetic-test-token"}

    env[3].authorization_manager = ExhaustQuota()
    env[3]._execute = AsyncMock()
    result = await env[3].execute_tool(ORG, "user_1", conn, tool(), {})
    assert not result.success
    assert result.metadata["blocked_by"] == "quota"
    env[3]._execute.assert_not_called()


@pytest.mark.asyncio
async def test_transport_exception_refunds_quota_without_retry(env):
    conn = add(env)
    env[3]._execute = AsyncMock(side_effect=ConnectionError("transport unavailable"))
    result = await env[3].execute_tool(ORG, "user_1", conn, tool(), {})
    assert not result.success
    env[3]._execute.assert_awaited_once()
    assert env[2].quota_manager.get_quota(ORG).current_usage == 0


@pytest.mark.asyncio
async def test_real_http_timeout_refunds_and_pause_prevents_retry(env):
    started, release = asyncio.Event(), asyncio.Event()
    requests = []

    async def delayed(request):
        requests.append(await request.json())
        started.set()
        await release.wait()
        return web.json_response({"result": "late"})

    app = web.Application()
    app.router.add_post("/mcp/tools/call", delayed)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        add(env, endpoint=f"http://127.0.0.1:{runner.addresses[0][1]}")
        env[3].http_executor.allow_private_networks = True
        env[3].http_executor.timeout_seconds = 0.2
        pending = asyncio.create_task(rpc(env, "tools/call"))
        try:
            await asyncio.wait_for(started.wait(), 5)
            result = await asyncio.wait_for(pending, 5)
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        assert result["error"]["code"] == -32051
        assert "timeout" in result["error"]["message"].lower()
        assert len(requests) == 1
        assert env[2].quota_manager.get_quota(ORG).current_usage == 0
        assert LifecycleManager(env[0]).pause("conn_a", "network degraded", "admin")
        assert (await rpc(env, "tools/call"))["error"]["code"] == -32050
        assert len(requests) == 1
    finally:
        release.set()
        await runner.cleanup()
