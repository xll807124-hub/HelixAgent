"""
SEC-007 egress guard (SSRF): address classification, endpoint validation,
DNS-rebinding resolver, redirects, and end-to-end through ToolExecutor.
"""

import asyncio
import socket
import threading

import pytest
from aiohttp import web

from src.security.mcp_connector_governance.execution import ToolExecutor
from src.security.mcp_connector_governance.execution.egress_guard import (
    EgressViolation,
    build_guarded_resolver,
    is_blocked_address,
    validate_endpoint,
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

ORG = "org_egress"


# ---------------------------------------------------------------- addresses

@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "127.1.2.3", "10.0.0.1", "172.16.0.1", "172.31.255.255",
        "192.168.1.1", "169.254.169.254", "169.254.0.1", "100.64.0.1",
        "0.0.0.0", "224.0.0.1", "255.255.255.255", "192.0.2.1", "198.18.0.1",
        "::1", "::", "fe80::1", "fc00::1", "fd00::1", "ff02::1",
        "::ffff:127.0.0.1", "::ffff:169.254.169.254", "::ffff:10.0.0.1",
        "2002:7f00:0001::", "2002:a9fe:a9fe::",  # 6to4 of 127.0.0.1 / 169.254.169.254
        "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe",  # NAT64 of 127.0.0.1 / 169.254.169.254
        "fe80::1%eth0",
        "not-an-ip", "", "999.1.1.1",
    ],
)
def test_non_public_addresses_are_blocked(address):
    assert is_blocked_address(address) is True


@pytest.mark.parametrize(
    "address", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"]
)
def test_public_addresses_are_allowed(address):
    assert is_blocked_address(address) is False


# --------------------------------------------------------------- endpoints

@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",                       # plain http
        "ftp://example.com",
        "file:///etc/passwd",
        "gopher://example.com",
        "https://",                                 # no host
        "https://user:pw@example.com",              # embedded credentials
        "https://user@example.com",
        "https://127.0.0.1",
        "https://[::1]:8443/",
        "https://169.254.169.254/latest/meta-data",
        "https://10.1.2.3",
        "https://[::ffff:169.254.169.254]",
        # 非规范数字写法: aiohttp 会把它们当 IP 直连而绕过解析器
        "https://2130706433",                       # 127.0.0.1 十进制
        "https://3232235777",                       # 192.168.1.1 十进制
        "https://2852039166",                       # 169.254.169.254 十进制
        "https://127.1",
        "https://0177.0.0.1",                       # 八进制
        "https://0x7f.0.0.1",                       # 十六进制
        "https://0x7f000001",
        "https://127.0.0.1.",                       # 末尾点
        "https://8.8.8",                            # 不完整的点分写法同样拒绝
        "https://example.com:99999",                # invalid port
        "not-a-url",
        "",
    ],
)
def test_strict_mode_rejects_endpoint(url):
    with pytest.raises(EgressViolation):
        validate_endpoint(url)


@pytest.mark.parametrize(
    "url", ["https://example.com", "https://example.com:8443/base", "https://8.8.8.8"]
)
def test_strict_mode_accepts_public_https(url):
    validate_endpoint(url)


def test_error_message_does_not_echo_url_secrets():
    with pytest.raises(EgressViolation) as exc:
        validate_endpoint("https://admin:hunter2@example.com")
    assert "hunter2" not in str(exc.value)


def test_private_mode_allows_http_loopback_but_not_other_schemes():
    validate_endpoint("http://127.0.0.1:8080", allow_private_networks=True)
    with pytest.raises(EgressViolation):
        validate_endpoint("file:///etc/passwd", allow_private_networks=True)
    with pytest.raises(EgressViolation):
        validate_endpoint("http://user:pw@127.0.0.1", allow_private_networks=True)


# ------------------------------------------------------- guarded resolver

class _FakeResolver:
    def __init__(self, hosts):
        self.hosts = hosts
        self.closed = False

    async def resolve(self, host, port=0, family=socket.AF_INET):
        return [
            {"hostname": host, "host": h, "port": port, "family": family,
             "proto": 0, "flags": 0}
            for h in self.hosts
        ]

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_resolver_blocks_hostname_resolving_to_private_address():
    resolver = build_guarded_resolver(inner=_FakeResolver(["10.0.0.5"]))
    with pytest.raises(EgressViolation):
        await resolver.resolve("evil.example.com", 443)


@pytest.mark.asyncio
async def test_resolver_blocks_when_any_record_is_non_public():
    # DNS rebinding / multi-record trick: one public + one metadata address
    resolver = build_guarded_resolver(inner=_FakeResolver(["8.8.8.8", "169.254.169.254"]))
    with pytest.raises(EgressViolation):
        await resolver.resolve("rebind.example.com", 443)


@pytest.mark.asyncio
async def test_resolver_allows_public_addresses():
    resolver = build_guarded_resolver(inner=_FakeResolver(["8.8.8.8"]))
    infos = await resolver.resolve("ok.example.com", 443)
    assert infos[0]["host"] == "8.8.8.8"


@pytest.mark.asyncio
async def test_resolver_private_mode_allows_loopback_and_close_delegates():
    inner = _FakeResolver(["127.0.0.1"])
    resolver = build_guarded_resolver(allow_private_networks=True, inner=inner)
    assert (await resolver.resolve("localhost", 80))[0]["host"] == "127.0.0.1"
    await resolver.close()
    assert inner.closed


# ------------------------------------------------------------ end-to-end

def _connector(url: str, auth_mode=AuthenticationMode.NONE) -> Connector:
    identity = ConnectorIdentity(
        connector_id="conn_egress", organization_id=ORG,
        namespace="test", display_name="Egress", version="1.0.0",
    )
    config = ConnectorConfig(
        identity=identity, trust_level=TrustLevel.L3_RESTRICTED_CONDITIONAL,
        transport=TransportConfig(type=TransportType.HTTP, endpoint=url),
        auth=AuthConfig(mode=auth_mode, api_key_ref="vault://k"),
        signature=SignatureVerification(is_signed=False),
    )
    status = ConnectorStatus(
        connector_id="conn_egress", lifecycle_state=ConnectorLifecycleState.ACTIVE
    )
    return Connector(config=config, status=status)


def _tool() -> ToolSchema:
    return ToolSchema(
        tool_name="egress_echo", description="echo",
        input_schema=ToolInputSchema(properties={}, required=[]),
        risk_profile=ToolRiskProfile(
            risk_level="low", is_read_only=True, requires_human_approval=False,
            data_sensitivity="L2", network_access_required=True,
            filesystem_access_required=False, credential_access_required=False,
        ),
        capability=ToolCapability(),
    )


def _executor(**kwargs) -> ToolExecutor:
    engine = PolicyEngine()
    engine.quota_manager.initialize_org_quota(ORG, base_quota=1000.0)
    return ToolExecutor(engine, timeout_seconds=3, **kwargs)


def _usage(executor) -> float:
    return executor.policy_engine.quota_manager.get_quota(ORG).current_usage


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254",
        "https://127.0.0.1",
        "https://[::1]",
        "http://example.com",
        "file:///etc/passwd",
    ],
)
async def test_executor_blocks_unsafe_endpoints_and_refunds(url):
    executor = _executor()
    result = await execute_approved_fixture(executor, ORG, "u1", _connector(url), _tool(), {})
    assert not result.success
    assert result.error.startswith("Egress blocked")
    assert result.metadata["blocked_by"] == "egress"
    assert _usage(executor) == 0.0


@pytest.mark.asyncio
async def test_credentials_are_not_sent_when_egress_is_blocked():
    class Mgr:
        def prepare_credentials(self, connector, org_id, user_id):
            return {"type": "api_key", "token": "secret-token-xyz"}

    executor = _executor(authorization_manager=Mgr())
    conn = _connector("https://169.254.169.254", AuthenticationMode.API_KEY)
    result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
    assert not result.success
    assert result.metadata["blocked_by"] == "egress"
    assert "secret-token-xyz" not in repr(result.to_dict())


@pytest.mark.asyncio
async def test_default_executor_is_strict():
    executor = _executor()
    assert executor.http_executor.allow_private_networks is False


# --- redirect handling (local server, so private mode is required) ---

def _start_redirect_server(port_holder, hits):
    async def redirect(request):
        raise web.HTTPFound("http://127.0.0.1:1/internal")

    async def run():
        app = web.Application()
        app.router.add_post("/mcp/tools/call", redirect)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port_holder.append(site._server.sockets[0].getsockname()[1])
        await asyncio.Event().wait()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())


@pytest.mark.asyncio
async def test_redirects_are_not_followed():
    port_holder, hits = [], []
    threading.Thread(
        target=_start_redirect_server, args=(port_holder, hits), daemon=True
    ).start()
    while not port_holder:
        await asyncio.sleep(0.01)

    executor = _executor(allow_private_networks=True)
    conn = _connector(f"http://127.0.0.1:{port_holder[0]}")
    result = await execute_approved_fixture(executor, ORG, "u1", conn, _tool(), {})
    assert not result.success
    assert "redirect" in result.error.lower()
    assert result.metadata["blocked_by"] == "egress"
    assert _usage(executor) == 0.0
