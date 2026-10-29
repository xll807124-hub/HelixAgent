"""
SEC-007 HTTPExecutor: real HTTP transport with mock MCP server.
"""

import asyncio
import threading
from collections.abc import Callable

import pytest
from aiohttp import web

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
    TransportType,
    TrustLevel,
)
from src.security.mcp_connector_governance.policies import PolicyEngine
from tests.mcp_approval_helpers import execute_approved_fixture

ORG = "org_http_test"


async def mcp_handler(request):
    """Mock MCP server: echo the arguments back."""
    body = await request.json()
    method = body.get("method")
    if method != "tools/call":
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32601, "message": "Method not found"},
            },
            status=404,
        )
    params = body.get("params", {})
    return web.json_response(
        {"jsonrpc": "2.0", "id": body.get("id"), "result": {"echo": params.get("arguments", {})}},
    )


async def error_handler(request):
    """Mock MCP server that always returns an error."""
    body = await request.json()
    return web.json_response(
        {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {"code": -1, "message": "Simulated error"},
        },
    )


async def timeout_handler(request):
    """Mock MCP server that times out."""
    await asyncio.sleep(60)
    return web.Response(text="too late")


def start_server(handler: Callable, port_holder: list):
    """Start an aiohttp server in a background thread."""

    async def run():
        app = web.Application()
        app.router.add_post("/mcp/tools/call", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        port_holder.append(port)
        # Keep running until the test finishes
        await asyncio.Event().wait()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())


@pytest.fixture
def mock_server():
    """Start a mock MCP HTTP server in a background thread."""
    port_holder = []
    thread = threading.Thread(target=start_server, args=(mcp_handler, port_holder), daemon=True)
    thread.start()
    # Wait for the server to start
    while not port_holder:
        pass
    yield f"http://127.0.0.1:{port_holder[0]}"


@pytest.fixture
def error_server():
    """Start a mock MCP server that returns errors."""
    port_holder = []
    thread = threading.Thread(target=start_server, args=(error_handler, port_holder), daemon=True)
    thread.start()
    while not port_holder:
        pass
    yield f"http://127.0.0.1:{port_holder[0]}"


@pytest.fixture
def timeout_server():
    """Start a mock MCP server that times out."""
    port_holder = []
    thread = threading.Thread(target=start_server, args=(timeout_handler, port_holder), daemon=True)
    thread.start()
    while not port_holder:
        pass
    yield f"http://127.0.0.1:{port_holder[0]}"


@pytest.fixture
def executor():
    engine = PolicyEngine()
    engine.quota_manager.initialize_org_quota(ORG, base_quota=1000.0)
    # 测试服务器在 127.0.0.1 上, 需要显式放宽出口限制
    return ToolExecutor(engine, timeout_seconds=2, allow_private_networks=True)


def _connector(url: str) -> Connector:
    identity = ConnectorIdentity(
        connector_id="conn_http",
        organization_id=ORG,
        namespace="test",
        display_name="HTTP Connector",
        version="1.0.0",
    )
    transport = TransportConfig(type=TransportType.HTTP, endpoint=url)
    config = ConnectorConfig(
        identity=identity,
        trust_level=TrustLevel.L3_RESTRICTED_CONDITIONAL,
        transport=transport,
        auth=AuthConfig(mode=AuthenticationMode.NONE),
        signature=SignatureVerification(is_signed=False),
    )
    status = ConnectorStatus(
        connector_id="conn_http", lifecycle_state=ConnectorLifecycleState.ACTIVE
    )
    return Connector(config=config, status=status)


def _tool() -> ToolSchema:
    return ToolSchema(
        tool_name="http_echo",
        description="HTTP echo tool",
        input_schema=ToolInputSchema(properties={"msg": {"type": "string"}}, required=[]),
        risk_profile=ToolRiskProfile(
            risk_level="low",
            is_read_only=True,
            requires_human_approval=False,
            data_sensitivity="L2",
            network_access_required=True,
            filesystem_access_required=False,
            credential_access_required=False,
        ),
        capability=ToolCapability(),
    )


@pytest.mark.asyncio
async def test_successful_http_call(executor, mock_server):
    conn = _connector(mock_server)
    result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {"msg": "hello"})
    assert result.success, result.error
    assert result.result == {"echo": {"msg": "hello"}}


@pytest.mark.asyncio
async def test_http_error_response(executor, error_server):
    conn = _connector(error_server)
    result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
    assert not result.success
    assert "simulated error" in result.error.lower()


@pytest.mark.asyncio
async def test_http_timeout(executor, timeout_server):
    conn = _connector(timeout_server)
    result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
    assert not result.success
    assert "timeout" in result.error.lower()


@pytest.mark.asyncio
async def test_http_connection_refused(executor):
    conn = _connector("http://127.0.0.1:1")
    result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
    assert not result.success


@pytest.mark.asyncio
async def test_http_invalid_url(executor):
    conn = _connector("not-a-url")
    result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
    assert not result.success
