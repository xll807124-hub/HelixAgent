"""Definition admission, invalidation, fail-closed recovery and concurrency."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web

from src.security.mcp_connector_governance.audit import AuditLogger
from src.security.mcp_connector_governance.authorization import AuthorizationManager
from src.security.mcp_connector_governance.execution import ToolExecutor
from src.security.mcp_connector_governance.execution.tool_executor_v2 import ToolExecutionResult
from src.security.mcp_connector_governance.lifecycle import LifecycleManager
from src.security.mcp_connector_governance.models import (
    AuthenticationMode,
    ToolApproval,
    ToolSchema,
)
from src.security.mcp_connector_governance.policies import PolicyEngine
from src.security.mcp_connector_governance.protocol import MCPProtocolHandler
from src.security.mcp_connector_governance.registry import ConnectorRegistry, ToolRegistry
from src.security.mcp_connector_governance.registry import tool_governance as module
from src.security.mcp_connector_governance.registry.tool_governance import GovernanceError
from tests.test_mcp_audit_and_sec005_adapter import _adapter
from tests.test_mcp_lifecycle_discovery import ORG, State, connector, tool


def accept(request):
    return request.actor == "reviewer" and request.approval_ref == "review-1"


def assembly(authorizer=accept, timeout=1):
    connectors, tools, policy = ConnectorRegistry(), ToolRegistry(), PolicyEngine()
    conn = connector()
    connectors.register(conn)
    audit = AuditLogger()
    governance = tools.bind_governance(
        connectors, authorizer=authorizer, audit_logger=audit, authorization_timeout=timeout
    )
    tools.register_tool(tool(), conn.connector_id)
    policy.quota_manager.initialize_org_quota(ORG, base_quota=1000)
    executor = ToolExecutor(policy, tool_registry=tools, allow_private_networks=True)
    handler = MCPProtocolHandler(tools, policy, executor, connectors)
    return SimpleNamespace(
        connectors=connectors,
        tools=tools,
        policy=policy,
        conn=conn,
        gov=governance,
        executor=executor,
        handler=handler,
        audit=audit,
        lifecycle=LifecycleManager(connectors),
    )


def snapshot(env):
    return env.gov.snapshot(ORG, "conn_a")


def approve(env, name="echo", **kwargs):
    definition = env.tools.get_tool_for_connector("conn_a", name)
    return env.gov.approve(
        snapshot(env),
        name,
        definition.compute_definition_digest(),
        actor="reviewer",
        approval_ref="review-1",
        **kwargs,
    )


def review(env, selected=None):
    return env.gov.complete_review(
        snapshot(env), selected or ["echo"], actor="reviewer", approval_ref="review-1"
    )


async def rpc(env, method="tools/list", name="conn_a:echo", org=ORG):
    return json.loads(
        await env.handler.handle_request(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": {"name": name, "arguments": {"mode": "read"}},
                }
            ),
            org,
            "user",
        )
    )


@pytest.mark.asyncio
async def test_end_to_end_admission_review_and_legacy_record_does_not_authorize():
    env = assembly()
    env.executor._execute = AsyncMock(return_value=ToolExecutionResult(True, "ok"))
    env.tools.approve_tool("echo", tool().compute_schema_digest(), "legacy", "security_lead")
    assert (await rpc(env))["result"]["tools"] == []
    assert (await rpc(env, "tools/call"))["error"]["code"] == -32050
    assert (await env.executor.execute_tool(ORG, "u", env.conn, tool(), {})).metadata == {
        "blocked_by": "tool_approval"
    }
    grant = approve(env)
    assert (await rpc(env))["result"]["tools"][0]["name"] == "echo"
    assert "result" in await rpc(env, "tools/call")
    env.tools.register_tool(tool("Changed description"), "conn_a")
    assert env.conn.lifecycle_state == State.PENDING_REVIEW
    assert not env.gov.revalidate(grant, env.conn, tool())
    assert not env.lifecycle.activate("conn_a", "reviewer")
    assert (await rpc(env))["result"]["tools"] == []
    approve(env)
    assert not env.lifecycle.transition_to("conn_a", State.ACTIVE, "premature")
    review(env)
    assert env.lifecycle.transition_to("conn_a", State.ACTIVE, "review complete")
    assert "result" in await rpc(env, "tools/call")


@pytest.mark.parametrize(
    "field,value",
    [
        ("minProperties", 2),
        ("maxProperties", 4),
        ("$defs", {"x": {"type": "string"}}),
        ("oneOf", [{"required": ["x"]}, {"required": ["y"]}]),
        ("additionalProperties", {"type": "string"}),
    ],
)
def test_raw_schema_keywords_preserved_and_fingerprinted(field, value):
    raw = {
        "name": "x",
        "inputSchema": {"type": "object", field: value},
        "outputSchema": {"type": "string"},
        "annotations": {"readOnlyHint": True},
    }
    parsed = ToolSchema.from_mcp_tool_definition(raw)
    assert parsed.input_schema.to_dict() == raw["inputSchema"]
    digest = parsed.compute_definition_digest()
    changed = deepcopy(raw)
    changed["inputSchema"][field] = {} if field == "additionalProperties" else None
    assert digest != ToolSchema.from_mcp_tool_definition(changed).compute_definition_digest()
    assert raw["inputSchema"][field] == value


def test_full_fingerprint_order_timestamps_extensions_and_platform_configuration():
    original = tool()
    reordered = ToolSchema.from_mcp_tool_definition(
        {
            "inputSchema": {
                "required": ["mode"],
                "properties": {"mode": {"enum": ["read", "write"], "type": "string"}},
                "type": "object",
            },
            "description": "Echo",
            "name": "echo",
        }
    )
    assert original.compute_definition_digest() == reordered.compute_definition_digest()
    original.updated_at = datetime(2000, 1, 1)
    assert original.compute_definition_digest() == reordered.compute_definition_digest()
    for change in (
        lambda t: setattr(t, "description", "New"),
        lambda t: setattr(t, "version", "2"),
        lambda t: setattr(t.risk_profile, "risk_level", "high"),
        lambda t: t.capability.required_scopes.append("write"),
        lambda t: t.extra_definition.update({"annotations": {"readOnlyHint": True}}),
    ):
        new = deepcopy(original)
        change(new)
        assert original.compute_definition_digest() != new.compute_definition_digest()


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), object(), (1, 2), {1: "x"}])
def test_invalid_json_definitions_rejected(invalid):
    with pytest.raises(ValueError):
        ToolSchema.from_mcp_tool_definition({"name": "x", "extra": invalid})


@pytest.mark.parametrize(
    "raw",
    [
        {"name": ""},
        {"name": 3},
        {"name": "x", "description": []},
        {"name": "x", "inputSchema": []},
        {"name": "x", "inputSchema": {"type": "string"}},
        {"name": "x", "inputSchema": {"properties": []}},
        {"name": "x", "inputSchema": {"required": "x"}},
        {"name": "x", "inputSchema": {"required": [3]}},
        {"name": "x", "inputSchema": {"additionalProperties": 3}},
    ],
)
def test_malformed_definitions_rejected(raw):
    with pytest.raises(ValueError):
        ToolSchema.from_mcp_tool_definition(raw)


def test_scoped_grants_immutable_snapshots_exact_expiry_and_timezone(monkeypatch):
    env = assembly()
    now = datetime(2030, 1, 1, tzinfo=UTC)

    class Clock:
        @staticmethod
        def now(_tz):
            return now

    grant = approve(env, valid_until=now)
    with pytest.raises(FrozenInstanceError):
        grant.actor = "tampered"
    monkeypatch.setattr(module, "datetime", Clock)
    assert env.gov.get_grant(ORG, "conn_a", "echo") is None
    legacy = ToolApproval("x", "old", "a", now, "x", now.replace(tzinfo=None))
    assert not legacy.is_valid(now.astimezone(timezone(timedelta(hours=8))))
    assert legacy.is_valid(now - timedelta(microseconds=1))
    with pytest.raises(GovernanceError, match="unavailable"):
        env.gov.get_grant("another-org", "conn_a", "echo")
    second = connector("conn_b")
    env.connectors.register(second)
    env.tools.register_tool(tool(), "conn_b")
    assert env.gov.check_call(ORG, second, tool()) is None


@pytest.mark.parametrize(
    "authorizer",
    [None, lambda r: False, lambda r: 1, lambda r: (_ for _ in ()).throw(ValueError("sensitive"))],
)
def test_missing_denied_wrong_type_or_failed_authority_never_publishes(authorizer):
    env = assembly(authorizer)
    with pytest.raises(GovernanceError, match="authorization_denied"):
        approve(env)
    assert env.gov.get_grant(ORG, "conn_a", "echo") is None


def test_timeout_late_callback_and_saturation_fail_closed():
    release, entered = Event(), Event()

    def delayed(_):
        entered.set()
        release.wait(5)
        return True

    env = assembly(delayed, timeout=0.01)
    try:
        for _ in range(8):
            with pytest.raises(GovernanceError, match="authorization_denied"):
                approve(env)
        assert entered.is_set()
        with pytest.raises(GovernanceError, match="authorization_denied"):
            approve(env)
    finally:
        release.set()
    assert env.gov.get_grant(ORG, "conn_a", "echo") is None


@pytest.mark.parametrize("event", ["change", "revoke", "pause"])
def test_delayed_approval_is_fenced_without_holding_lifecycle_lock(event):
    entered, release = Event(), Event()

    def delayed(_):
        entered.set()
        assert release.wait(5)
        return True

    env = assembly(delayed, timeout=5)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(approve, env)
        assert entered.wait(2)
        try:
            if event == "change":
                env.tools.register_tool(tool("changed"), "conn_a")
            elif event == "revoke":
                env.gov.revoke(ORG, "conn_a", "echo", actor="admin")
            else:
                assert env.lifecycle.transition_to("conn_a", State.PAUSED, "pause")
        finally:
            release.set()
        with pytest.raises(GovernanceError, match="stale_snapshot"):
            pending.result()
    assert env.gov.get_grant(ORG, "conn_a", "echo") is None


@pytest.mark.parametrize("state", [State.ACTIVE, State.RESTRICTED, State.PAUSED, State.REVOKED])
def test_change_preserves_stopped_states_and_invalidates_entire_connector(state):
    env = assembly()
    env.conn.status.lifecycle_state = state
    second = tool()
    second.tool_name = "second"
    env.tools.register_tools_batch([tool(), second], "conn_a")
    approve(env)
    approve(env, "second")
    env.tools.register_tool(tool("new description"), "conn_a")
    assert env.gov.get_grant(ORG, "conn_a", "echo") is None
    assert env.gov.get_grant(ORG, "conn_a", "second") is None
    assert snapshot(env).review_required
    assert env.conn.lifecycle_state == (
        State.PENDING_REVIEW if state in (State.ACTIVE, State.RESTRICTED) else state
    )


def test_idempotent_sync_full_replace_removal_partial_stale_and_retry():
    env = assembly()
    first = snapshot(env)
    grant = approve(env)
    assert (
        env.gov.synchronize(
            ORG, "conn_a", [tool()], expected_generation=first.generation, actor="sync"
        )
        == first
    )
    assert env.gov.check_call(ORG, env.conn, tool()) == grant
    dirty = env.gov.mark_dirty(ORG, "conn_a", expected_generation=first.generation, actor="refresh")
    assert not dirty.complete and dirty.review_required
    assert (
        env.gov.mark_dirty(ORG, "conn_a", expected_generation=dirty.generation, actor="retry")
        == dirty
    )
    with pytest.raises(GovernanceError, match="stale_snapshot"):
        env.gov.synchronize(
            ORG, "conn_a", [tool()], expected_generation=first.generation, actor="late"
        )
    with pytest.raises(GovernanceError, match="invalid_approval"):
        approve(env)
    recovered = env.gov.synchronize(
        ORG, "conn_a", [tool()], expected_generation=dirty.generation, actor="retry"
    )
    assert recovered.complete and recovered.review_required
    approve(env)
    review(env)
    assert env.lifecycle.transition_to("conn_a", State.ACTIVE, "reviewed")
    env.tools.unregister_connector("conn_a")
    assert env.tools.list_tools_for_connector("conn_a") == []
    assert snapshot(env).review_required


@pytest.mark.parametrize("definitions", [[tool(), tool()], [object()], None])
def test_malformed_manifest_stops_old_approved_tools(definitions):
    env = assembly()
    approve(env)
    with pytest.raises(GovernanceError, match="invalid_manifest"):
        env.gov.synchronize(
            ORG, "conn_a", definitions, expected_generation=snapshot(env).generation, actor="sync"
        )
    assert not snapshot(env).complete
    assert env.conn.lifecycle_state == State.PENDING_REVIEW


@pytest.mark.parametrize("action", ["approve", "revoke", "change", "review"])
def test_audit_failure_does_not_publish_or_undo_stop_and_can_retry(action):
    env = assembly()
    if action != "approve":
        approve(env)
    if action == "review":
        env.tools.register_tool(tool("changed"), "conn_a")
        approve(env)
    original = env.audit.log_event
    env.audit.log_event = Mock(side_effect=OSError("sensitive path"))
    if action == "change":
        env.tools.register_tool(tool("changed"), "conn_a")
    else:
        with pytest.raises(GovernanceError, match="audit_unavailable"):
            if action == "approve":
                approve(env)
            elif action == "revoke":
                env.gov.revoke(ORG, "conn_a", "echo", actor="admin")
            else:
                review(env)
    assert snapshot(env).error_code == "audit_unavailable"
    assert env.gov.check_call(ORG, env.conn, tool()) is None
    env.audit.log_event = original
    env.gov.synchronize(
        ORG,
        "conn_a",
        [env.tools.get_tool_for_connector("conn_a", "echo")],
        expected_generation=snapshot(env).generation,
        actor="retry",
    )
    assert snapshot(env).error_code is None
    approve(env)
    if snapshot(env).review_required:
        review(env)
        assert env.lifecycle.transition_to("conn_a", State.ACTIVE, "review complete")


def test_config_revision_owner_and_replacement_cannot_bypass_review():
    env = assembly()
    approve(env)
    env.conn.config.transport.endpoint = "https://changed.example/mcp"
    assert env.gov.check_call(ORG, env.conn, tool()) is None
    assert env.conn.lifecycle_state == State.PENDING_REVIEW
    assert snapshot(env).review_required
    replacement = connector()
    replacement.config.identity.organization_id = "other"
    with pytest.raises(GovernanceError, match="unavailable"):
        env.connectors.register(replacement)
    replacement.config.identity.organization_id = ORG
    env.connectors.register(replacement)
    assert replacement.lifecycle_state == State.PENDING_REVIEW
    assert not env.lifecycle.transition_to("conn_a", State.ACTIVE, "bypass")
    env.connectors.remove("conn_a")
    assert env.connectors.get("conn_a") is None
    env.connectors.register(connector())
    assert not env.gov.can_activate(env.connectors.get("conn_a"))


@pytest.mark.asyncio
async def test_direct_executor_missing_authority_wrong_scope_and_supplied_snapshot():
    env = assembly()
    approve(env)
    env.executor._execute = AsyncMock(return_value=ToolExecutionResult(True))
    env.executor.tool_registry = None
    result = await env.executor.execute_tool(ORG, "u", env.conn, tool(), {})
    assert result.metadata["blocked_by"] == "tool_approval"
    env.executor.tool_registry = env.tools
    assert env.gov.check_call("other", env.conn, tool()) is None
    assert env.gov.check_call(ORG, deepcopy(env.conn), tool()) is None
    assert env.gov.check_call(ORG, env.conn, tool("tampered")) is None
    assert (await rpc(env, org="other"))["result"]["tools"] == []
    result = await env.executor.execute_tool(ORG, "u", env.conn, tool("tampered"), {})
    assert result.metadata["blocked_by"] == "tool_approval"
    env.executor._execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["reapprove", "schema"])
async def test_waiting_credentials_do_not_revive_old_approval_or_consume_quota(change):
    env = assembly()
    grant = approve(env)
    started, release = asyncio.Event(), asyncio.Event()

    async def credentials(*_):
        started.set()
        await release.wait()
        return None, None

    env.executor._prepare_injection = credentials
    env.executor._execute = AsyncMock(return_value=ToolExecutionResult(True))
    pending = asyncio.create_task(env.executor.execute_tool(ORG, "u", env.conn, tool(), {}))
    await started.wait()
    if change == "reapprove":
        env.gov.revoke(ORG, "conn_a", "echo", actor="admin")
        assert approve(env).approval_id != grant.approval_id
    else:
        env.tools.register_tool(tool("changed"), "conn_a")
    release.set()
    assert not (await pending).success
    env.executor._execute.assert_not_called()
    assert env.policy.quota_manager.get_quota(ORG).current_usage == 0


@pytest.mark.asyncio
async def test_local_http_review_round_trip_without_stale_requests():
    calls = []

    async def handle(request):
        calls.append(await request.json())
        return web.json_response({"jsonrpc": "2.0", "id": "1", "result": {"ok": True}})

    app = web.Application()
    app.router.add_post("/mcp/tools/call", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        env = assembly()
        # Configuration becomes the baseline before any tool is explicitly approved.
        env.conn.config.transport.endpoint = (
            f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        )
        snapshot(env)
        approve(env)
        review(env)
        assert env.lifecycle.transition_to("conn_a", State.ACTIVE, "ready")
        assert "result" in await rpc(env, "tools/call")
        assert len(calls) == 1
        env.tools.register_tool(tool("changed"), "conn_a")
        assert "error" in await rpc(env, "tools/call")
        assert len(calls) == 1
        approve(env)
        review(env)
        assert env.lifecycle.transition_to("conn_a", State.ACTIVE, "reviewed")
        assert "result" in await rpc(env, "tools/call")
        assert len(calls) == 2
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_configuration_rejected(timeout):
    with pytest.raises(ValueError, match="finite and positive"):
        assembly(timeout=timeout)


def test_binding_conflicts_and_missing_target_are_rejected():
    env = assembly()
    assert env.tools.bind_governance(env.connectors) is env.gov
    with pytest.raises(ValueError, match="already bound"):
        env.tools.bind_governance(ConnectorRegistry())
    with pytest.raises(ValueError, match="already bound"):
        env.tools.bind_governance(env.connectors, authorizer=lambda r: True)
    with pytest.raises(ValueError, match="already bound"):
        ToolRegistry().bind_governance(env.connectors)
    with pytest.raises(ValueError, match="share tool registry"):
        MCPProtocolHandler(ToolRegistry(), env.policy, env.executor)
    with pytest.raises(GovernanceError, match="unavailable"):
        env.tools.register_tool(tool(), "missing")
    env.tools.unregister_connector("missing")
    env.connectors.remove("missing")


@pytest.mark.parametrize("batch", [[tool(), tool()], [object()]])
def test_legacy_batch_write_entry_cannot_bypass_malformed_manifest_quarantine(batch):
    env = assembly()
    approve(env)
    with pytest.raises(GovernanceError, match="invalid_manifest"):
        env.tools.register_tools_batch(batch, "conn_a")
    assert not snapshot(env).complete
    assert env.gov.get_grant(ORG, "conn_a", "echo") is None


def test_invalid_actors_scope_snapshots_and_expiry_rejected():
    env = assembly()
    current = snapshot(env)
    with pytest.raises(GovernanceError, match="invalid_manifest"):
        env.gov.synchronize(
            ORG, "conn_a", [tool()], expected_generation=current.generation, actor=""
        )
    with pytest.raises(GovernanceError, match="stale_snapshot"):
        env.gov.mark_dirty(ORG, "conn_a", expected_generation=current.generation + 1, actor="sync")
    for expiry in ("2030", datetime(2000, 1, 1)):
        with pytest.raises(GovernanceError, match="invalid_approval"):
            approve(env, valid_until=expiry)
    for name, digest in (("missing", tool().compute_definition_digest()), ("echo", "old")):
        with pytest.raises(GovernanceError, match="invalid_approval"):
            env.gov.approve(current, name, digest, actor="reviewer", approval_ref="review-1")
    for actor, ref in ((None, "x"), ("reviewer", None), ("reviewer", "")):
        with pytest.raises(GovernanceError, match="authorization_denied"):
            env.gov.approve(
                current, "echo", tool().compute_definition_digest(), actor=actor, approval_ref=ref
            )
    with pytest.raises(GovernanceError, match="stale_snapshot"):
        env.gov.approve(
            replace(current, connector_revision="stale"),
            "echo",
            tool().compute_definition_digest(),
            actor="reviewer",
            approval_ref="review-1",
        )
    with pytest.raises(GovernanceError, match="invalid_approval"):
        review(env)


def test_cannot_start_authority_worker_fails_closed(monkeypatch):
    env = assembly()
    monkeypatch.setattr(
        module.Thread, "start", Mock(side_effect=RuntimeError("resource exhausted"))
    )
    with pytest.raises(GovernanceError, match="authorization_denied"):
        approve(env)
    assert env.gov.get_grant(ORG, "conn_a", "echo") is None


def test_revocation_while_review_authority_waits_keeps_review_required():
    env = assembly()
    env.tools.register_tool(tool("changed"), "conn_a")
    approve(env)
    entered, release = Event(), Event()

    def delayed(_):
        entered.set()
        assert release.wait(5)
        return True

    env.gov.authorizer = delayed
    env.gov.authorization_timeout = 5
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(review, env)
        assert entered.wait(2)
        try:
            env.gov.revoke(ORG, "conn_a", "echo", actor="admin")
        finally:
            release.set()
        with pytest.raises(GovernanceError, match="stale_snapshot"):
            pending.result()
    assert snapshot(env).review_required


@pytest.mark.parametrize("mode", [AuthenticationMode.OAUTH2_PKCE, AuthenticationMode.API_KEY])
def test_review_cannot_restore_unsupported_or_unconfigured_credentials(mode):
    env = assembly()
    env.conn.config.auth.mode = mode
    # Configuration change itself must also fence the existing approved definition.
    auth = AuthorizationManager() if mode == AuthenticationMode.OAUTH2_PKCE else None
    lifecycle = LifecycleManager(env.connectors, authorization_manager=auth)
    if auth:
        auth.store_oauth_token("conn_a", ORG, "u", "synthetic-access")
    snapshot(env)
    approve(env)
    review(env)
    assert not lifecycle.transition_to("conn_a", State.ACTIVE, "reviewed")
    status = lifecycle.get_credential_invalidation_status("conn_a", org_id=ORG)
    assert status["credential_revocation_status"] == ("unsupported" if auth else "unconfigured")
    assert env.gov.check_call(ORG, env.conn, tool()) is None


def test_schema_change_revokes_sec005_leases_without_holding_registry_lock():
    env = assembly()
    client, _, cdp = _adapter(retry_delay_seconds=0)
    auth = AuthorizationManager(client)
    env.conn.config.auth.mode = AuthenticationMode.API_KEY
    env.conn.config.auth.api_key_ref = "vault://key-1"
    LifecycleManager(env.connectors, authorization_manager=auth)
    snapshot(env)
    approve(env)
    review(env)
    assert env.lifecycle.transition_to("conn_a", State.ACTIVE, "configured")
    auth.prepare_credentials(env.conn, ORG, "u")
    assert cdp.get_rental_stats()["total_active_rentals"] == 1
    original = client.revoke_connector_credentials

    def checked(*args):
        # A second thread must acquire the lock while external revocation is executing.
        with ThreadPoolExecutor() as pool:
            assert pool.submit(lambda: env.gov.snapshot(ORG, "conn_a")).result(timeout=2)
        return original(*args)

    client.revoke_connector_credentials = checked
    env.tools.register_tool(tool("changed"), "conn_a")
    assert cdp.get_rental_stats()["total_active_rentals"] == 0
    assert env.conn.status.credential_invalidation["credential_revocation_status"] == "complete"
    approve(env)
    review(env)
    assert env.lifecycle.transition_to("conn_a", State.ACTIVE, "reviewed")
    auth.prepare_credentials(env.conn, ORG, "u")
    assert cdp.get_rental_stats()["total_active_rentals"] == 1


def test_local_cleanup_failure_cannot_be_overridden_by_review(monkeypatch):
    env = assembly()
    auth = AuthorizationManager()
    LifecycleManager(env.connectors, authorization_manager=auth)
    monkeypatch.setattr(
        auth, "begin_invalidation", Mock(side_effect=RuntimeError("storage failed"))
    )
    env.tools.register_tool(tool("changed"), "conn_a")
    assert not env.conn.status.credential_invalidation["local_invalidated"]
    approve(env)
    review(env)
    assert not env.lifecycle.transition_to("conn_a", State.ACTIVE, "reviewed")


@pytest.mark.asyncio
async def test_unapproved_provider_cannot_contribute_definition_or_expand_visibility():
    env = assembly()
    approve(env)
    second = connector("conn_b")
    env.connectors.register(second)
    env.tools.register_tool(tool("unapproved description"), "conn_b")
    assert (await rpc(env))["result"]["tools"][0]["description"] == "Echo"
    env.gov.approve(
        env.gov.snapshot(ORG, "conn_b"),
        "echo",
        tool("unapproved description").compute_definition_digest(),
        actor="reviewer",
        approval_ref="review-1",
    )
    assert (await rpc(env))["result"]["tools"] == []  # Both approved, but ambiguous.


def test_review_explicit_selection_and_audit_are_scoped_to_definition():
    env = assembly()
    second = tool()
    second.tool_name = "second"
    env.tools.register_tools_batch([tool(), second], "conn_a")
    first = approve(env)
    approve(env, "second")
    review(env, ["echo"])
    assert env.gov.get_grant(ORG, "conn_a", "echo") == first
    assert env.gov.get_grant(ORG, "conn_a", "second") is None
    events = env.audit.get_events()
    approved = next(
        event for event in events if event["metadata"].get("approval_id") == first.approval_id
    )
    assert approved["metadata"]["definition_digest"] == first.definition_digest
    assert "inputSchema" not in str(events)


def test_management_validation_and_legacy_storage_remain_safe():
    env = assembly()
    assert env.gov.get_grant(ORG, "conn_a", []) is None
    with pytest.raises(GovernanceError, match="unavailable"):
        env.gov.snapshot([], "conn_a")
    with pytest.raises(GovernanceError, match="invalid_approval"):
        env.gov.approve(None, "echo", "digest", actor="reviewer", approval_ref="review-1")
    with pytest.raises(GovernanceError, match="invalid_approval"):
        env.gov.approve(snapshot(env), [], "digest", actor="reviewer", approval_ref="review-1")
    with pytest.raises(GovernanceError, match="invalid_manifest"):
        env.gov.mark_dirty(ORG, "conn_a", expected_generation=0, actor="")
    with pytest.raises(GovernanceError, match="invalid_approval"):
        env.gov.revoke(ORG, "conn_a", "echo", actor="")
    with pytest.raises(GovernanceError, match="invalid_approval"):
        env.gov.complete_review(snapshot(env), [None], actor="reviewer", approval_ref="review-1")
    with pytest.raises(GovernanceError, match="unavailable"):
        env.gov.replace_connector(connector("missing"))
    legacy_tools = ToolRegistry()
    legacy_tools.register_tools_batch([tool()], "old")
    old = legacy_tools.approve_tool("echo", tool().compute_schema_digest(), "a", "old")
    assert old.is_valid()
    assert legacy_tools.get_tool("echo") is not None
    legacy_connectors = ConnectorRegistry()
    legacy_connectors.register(connector())
    legacy_connectors.remove("conn_a")
    assert legacy_connectors.get("conn_a") is None


@pytest.mark.asyncio
async def test_completed_execution_audit_failure_is_sanitized(caplog):
    env = assembly()
    approve(env)
    env.executor._execute = AsyncMock(return_value=ToolExecutionResult(True))
    env.executor.audit_logger.log_tool_invocation = Mock(side_effect=OSError("sensitive-path"))
    result = await env.executor.execute_tool(ORG, "u", env.conn, tool(), {})
    assert result.success  # Remote side effect already happened; an audit error cannot undo it.
    assert "OSError" in caplog.text and "sensitive-path" not in caplog.text
