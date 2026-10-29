"""SEC-007 invalidation: scope, races, bounded retries and real transport evidence."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web

from src.security.mcp_connector_governance.audit import AuditLogger
from src.security.mcp_connector_governance.authorization import (
    AuthorizationManager,
    CredentialIssuanceError,
)
from src.security.mcp_connector_governance.authorization.oauth_handler import TokenManager
from src.security.mcp_connector_governance.lifecycle import LifecycleManager
from src.security.mcp_connector_governance.models import (
    AuthConfig,
    AuthenticationMode,
    ConnectorStatus,
    TrustLevel,
)
from src.security.mcp_connector_governance.registry import ConnectorRegistry
from tests.test_mcp_audit_and_sec005_adapter import S, _adapter, _connector, _issue
from tests.test_mcp_lifecycle_discovery import ORG, add, rpc, tool

pytest_plugins = ["tests.test_mcp_lifecycle_discovery"]


def assembly(mode=AuthenticationMode.API_KEY, **adapter_options):
    client, pdp, cdp = _adapter(retry_delay_seconds=0, **adapter_options)
    auth = AuthorizationManager(client)
    conn = _connector(AuthConfig(mode=mode, api_key_ref="vault://key-1"), state=S.ACTIVE)
    registry = ConnectorRegistry()
    registry.register(conn)
    lifecycle = LifecycleManager(registry, authorization_manager=auth)
    return conn, auth, lifecycle, client, pdp, cdp


def status(lifecycle):
    return lifecycle.get_credential_invalidation_status("conn_1", org_id="org_1")


def store(auth, cid="conn_1", org="org_1", user="u1", **kw):
    auth.store_oauth_token(cid, org, user, "synthetic-access", **kw)


def test_managed_pause_resume_requires_fresh_issuance_and_scoped_revoke():
    conn, auth, lifecycle, client, pdp, cdp = assembly()
    first = auth.prepare_credentials(conn, "org_1", "u1")
    auth.prepare_credentials(conn, "org_1", "u2")
    client.issue_short_lived_credential(
        key_ref="vault://other", connector_id="conn_2", org_id="org_1", ttl_seconds=600,
    )
    assert not auth._token_cache  # Zero cache is not zero issued leases.
    assert cdp.get_rental_stats()["total_active_rentals"] == 3
    assert lifecycle.pause("conn_1", "maintenance", "admin")
    result = status(lifecycle)
    assert result["credential_revocation_status"] == "complete"
    assert result["local_invalidated"] and result["audit_recorded"]
    assert result["pending_count"] == 0
    assert cdp.get_rental_stats()["total_active_rentals"] == 1
    assert auth.prepare_credentials(conn, "org_1", "u1") is None
    assert not auth.check_authorization_status(conn, "org_1", "u1")["authorized"]
    with pytest.raises(CredentialIssuanceError):
        _issue(client)
    assert lifecycle.pause("conn_1", "retry", "admin")
    assert status(lifecycle)["generation"] == 2
    assert lifecycle.resume("conn_1", "admin")
    fresh = auth.prepare_credentials(conn, "org_1", "u1")
    assert fresh["token"] != first["token"]
    assert lifecycle.revoke("conn_1", "incident", "admin")
    assert not lifecycle.resume("conn_1", "admin")
    assert cdp.get_rental_stats()["total_active_rentals"] == 1
    assert pdp._revoked_tokens


def test_structured_cache_keys_clear_all_users_without_separator_collision():
    auth = AuthorizationManager()
    for cid, org, user in [
        ("c", "o:a", "u"), ("c", "o:a", "u2"),
        ("c", "o", "a:u"), ("other", "o:a", "u"),
    ]:
        store(auth, cid, org, user)
    result = auth.invalidate_connector_credentials("c", "o:a", "pause", "admin")
    assert result["cleared_count"] == 2
    assert result["credential_revocation_status"] == "unsupported"
    assert set(auth._token_cache) == {("o", "a:u", "c"), ("o:a", "u", "other")}
    assert not auth.resume_credentials("c", "o:a")
    assert auth.invalidate_connector_credentials("c", "o:a", "retry", "admin")[
        "credential_revocation_status"
    ] == "unsupported"
    with pytest.raises(ValueError):
        store(auth, "c", "o:a", expected_generation=2)


@pytest.mark.parametrize("mode", [AuthenticationMode.OAUTH2_PKCE, AuthenticationMode.BEARER_TOKEN])
def test_external_without_revoker_stays_stopped_after_direct_transition(mode):
    conn, auth, lifecycle, _, _, _ = assembly(mode)
    store(auth)
    assert lifecycle.transition_to("conn_1", S.PAUSED, "pause", "admin")
    assert status(lifecycle)["credential_revocation_status"] == "unsupported"
    assert not lifecycle.transition_to("conn_1", S.ACTIVE, "resume", "admin")
    conn.config.auth.mode = AuthenticationMode.NONE
    assert lifecycle.pause("conn_1", "retry", "admin")
    assert status(lifecycle)["credential_revocation_status"] == "unsupported"


def test_no_manager_and_one_registry_binding_fail_closed():
    conn, auth, _, _, _, _ = assembly()
    registry = ConnectorRegistry()
    registry.register(conn)
    lifecycle = LifecycleManager(registry)
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert status(lifecycle)["credential_revocation_status"] == "unconfigured"
    assert not lifecycle.resume("conn_1", "admin")
    LifecycleManager(registry, authorization_manager=auth)
    with pytest.raises(ValueError, match="already"):
        LifecycleManager(registry, authorization_manager=AuthorizationManager())
    assert not LifecycleManager(registry).resume("conn_1", "admin")
    assert status(lifecycle)["local_invalidated"] is False
    assert lifecycle.pause("conn_1", "retry after binding", "admin")
    assert status(lifecycle)["credential_revocation_status"] == "unconfigured"
    assert not lifecycle.resume("conn_1", "admin")


def test_missing_adapter_and_no_auth_modes():
    conn, auth, lifecycle, _, _, _ = assembly()
    auth.credential_proxy = None
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert status(lifecycle)["credential_revocation_status"] == "unconfigured"
    assert not lifecycle.resume("conn_1", "admin")
    assert lifecycle.pause("conn_1", "retry", "admin")
    conn, auth, lifecycle, _, _, _ = assembly(AuthenticationMode.NONE)
    assert auth.prepare_credentials(conn, "org_1", "u") == {}
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert status(lifecycle)["credential_revocation_status"] == "not_required"
    assert lifecycle.resume("conn_1", "admin")


def test_scope_validation_and_status_copy():
    conn, auth, lifecycle, _, _, _ = assembly()
    health_check = datetime.utcnow()
    legacy = ConnectorStatus("legacy", S.ACTIVE, health_check)
    assert legacy.last_health_check == health_check
    assert legacy.to_dict()["credential_generation"] == 0
    assert status(lifecycle) is None
    assert lifecycle.get_credential_invalidation_status("missing", org_id="org_1") is None
    assert not lifecycle.pause("missing", "pause", "admin")
    with pytest.raises(ValueError, match="not found"):
        lifecycle.registry.update_status("missing", S.PAUSED)
    assert not lifecycle.transition_to("conn_1", "paused", "pause")
    assert not lifecycle.pause("conn_1", "", "admin")
    assert auth.prepare_credentials(conn, "other", "u") is None
    assert auth.prepare_credentials(conn, "org_1", "") is None
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert lifecycle.get_credential_invalidation_status("conn_1", org_id="other") is None
    result = status(lifecycle)
    result["credential_revocation_status"] = "tampered"
    assert status(lifecycle)["credential_revocation_status"] == "complete"
    for cid, org in [("", "org"), ("c", ""), ("c", 1)]:
        with pytest.raises(ValueError):
            auth.get_credential_generation(cid, org)
    with pytest.raises(ValueError):
        auth.invalidate_connector_credentials("c", "org", "", "actor")


def test_old_oauth_callback_rejected_after_managed_resume():
    _, auth, lifecycle, _, _, _ = assembly()
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert lifecycle.resume("conn_1", "admin")
    with pytest.raises(ValueError):
        store(auth)
    with pytest.raises(ValueError):
        store(auth, expected_generation=0)
    store(auth, expected_generation=auth.get_credential_generation("conn_1", "org_1"))
    assert auth._token_cache


@pytest.mark.parametrize("action", ["pause", "single_user_revoke", "replacement"])
def test_late_oauth_refresh_cannot_restore_invalidated_entry(monkeypatch, action):
    conn, auth, lifecycle, _, _, _ = assembly(AuthenticationMode.OAUTH2_PKCE)
    store(auth, refresh_token="synthetic-refresh", expires_in=1)
    entered, release = Event(), Event()

    def refresh(**kw):
        entered.set()
        assert release.wait(5)
        return {"access_token": "late", "expires_at": datetime.utcnow() + timedelta(hours=1)}

    monkeypatch.setattr(auth, "_refresh_oauth_token", refresh)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(auth.prepare_credentials, conn, "org_1", "u1")
        try:
            assert entered.wait(5)
            if action == "pause":
                assert lifecycle.pause("conn_1", "pause", "admin")
                assert status(lifecycle)["pending_count"] == 1
                assert status(lifecycle)["pending_count"] == 1  # Polling cannot accumulate counts.
            elif action == "single_user_revoke":
                assert auth.revoke_credentials("conn_1", "org_1", "u1")
            else:
                store(auth)
        finally:
            release.set()
        assert pending.result(5) is None
    assert all(v["access_token"] != "late" for v in auth._token_cache.values())


def test_late_managed_issuance_is_revoked_and_cannot_resume_early(monkeypatch):
    conn, auth, lifecycle, client, _, cdp = assembly()
    entered, release = Event(), Event()
    original = cdp.issue_token

    def delayed(*args, **kw):
        entered.set()
        assert release.wait(5)
        return original(*args, **kw)

    monkeypatch.setattr(cdp, "issue_token", delayed)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(auth.prepare_credentials, conn, "org_1", "u1")
        try:
            assert entered.wait(5)
            assert lifecycle.pause("conn_1", "pause", "admin")
            assert status(lifecycle)["credential_revocation_status"] == "partial"
            assert not client.resume_connector_credentials("conn_1", "org_1")
            assert not lifecycle.resume("conn_1", "admin")
        finally:
            release.set()
        assert pending.result(5) is None
    assert cdp.get_rental_stats()["total_active_rentals"] == 0
    assert status(lifecycle)["credential_revocation_status"] == "complete"
    assert lifecycle.resume("conn_1", "admin")


@pytest.mark.parametrize("failures", [1, 4])
def test_bounded_revocation_retry_retains_failed_handle(monkeypatch, failures):
    conn, auth, lifecycle, _, _, cdp = assembly()
    auth.prepare_credentials(conn, "org_1", "u1")
    original = cdp.revoke_token
    attempts = []

    def unreliable(*args, **kw):
        attempts.append(1)
        if len(attempts) <= failures:
            raise ConnectionError("synthetic unavailable")
        return original(*args, **kw)

    monkeypatch.setattr(cdp, "revoke_token", unreliable)
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert len(attempts) == min(failures + 1, 4)
    if failures == 4:
        assert status(lifecycle)["credential_revocation_status"] == "partial"
        assert not lifecycle.resume("conn_1", "admin")
        assert lifecycle.pause("conn_1", "retry", "admin")
    assert status(lifecycle)["credential_revocation_status"] == "complete"
    assert cdp.get_rental_stats()["total_active_rentals"] == 0


def test_timeout_keeps_single_worker_until_late_ack(monkeypatch):
    conn, auth, lifecycle, client, _, cdp = assembly(revoke_timeout_seconds=0.01)
    auth.prepare_credentials(conn, "org_1", "u1")
    entered, release = Event(), Event()
    original = cdp.revoke_token
    calls = []

    def delayed(*args, **kw):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        original(*args, **kw)

    monkeypatch.setattr(cdp, "revoke_token", delayed)
    try:
        assert lifecycle.pause("conn_1", "pause", "admin")
        assert entered.is_set()
        assert status(lifecycle)["pending_count"] == 1
        assert not lifecycle.resume("conn_1", "admin")
        assert lifecycle.pause("conn_1", "retry", "admin")
        assert calls == [1]
        events = list(client._jobs.values())
    finally:
        release.set()
    assert all(event.wait(5) for event in events)
    assert status(lifecycle)["credential_revocation_status"] == "complete"
    assert lifecycle.resume("conn_1", "admin")


def test_revocation_io_does_not_hold_lifecycle_or_cache_lock(monkeypatch):
    conn, auth, lifecycle, client, _, _ = assembly()
    auth.prepare_credentials(conn, "org_1", "u1")
    entered, release = Event(), Event()
    original = client.revoke_connector_credentials

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(client, "revoke_connector_credentials", delayed)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(lifecycle.pause, "conn_1", "pause", "admin")
        try:
            assert entered.wait(5)
            assert lifecycle.registry.lifecycle_lock.acquire(timeout=0.5)
            lifecycle.registry.lifecycle_lock.release()
            assert auth._lock.acquire(timeout=0.5)
            auth._lock.release()
            assert not conn.status.is_callable()
            assert status(lifecycle)["credential_revocation_status"] == "partial"
            assert not lifecycle.resume("conn_1", "admin")
        finally:
            release.set()
        assert pending.result(5)


def test_audit_failure_and_signature_failure_keep_credentials_blocked(monkeypatch, caplog):
    conn, auth, lifecycle, _, _, _ = assembly()
    sentinel = "synthetic-private-error"
    broken = Mock(side_effect=OSError(sentinel))
    monkeypatch.setattr(auth.audit_logger, "log_event", broken)
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert status(lifecycle)["error_code"] == "invalidation_audit_unavailable"
    assert not lifecycle.resume("conn_1", "admin")
    auth.audit_logger = AuditLogger()
    conn.config.trust_level = TrustLevel.L2_ORG_VERIFIED
    assert not lifecycle.resume("conn_1", "admin")
    assert ("org_1", "conn_1") in auth._blocked
    conn.config.trust_level = TrustLevel.L3_RESTRICTED_CONDITIONAL
    assert lifecycle.resume("conn_1", "admin")
    assert sentinel not in caplog.text + json.dumps(status(lifecycle))


@pytest.mark.parametrize("response", [None, {}, {"credential_revocation_status": "complete",
                                               "pending_count": 1}])
def test_invalid_provider_ack_cannot_resume(monkeypatch, response):
    _, auth, lifecycle, client, _, _ = assembly()
    monkeypatch.setattr(client, "revoke_connector_credentials", lambda *a: response)
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert not lifecycle.resume("conn_1", "admin")
    assert status(lifecycle)["credential_revocation_status"] == "partial"
    assert not auth.resume_credentials("conn_1", "org_1")


def test_local_cleanup_failure_never_undoes_stop(monkeypatch):
    conn, auth, lifecycle, _, _, _ = assembly()
    monkeypatch.setattr(auth, "begin_invalidation", Mock(side_effect=OSError("synthetic")))
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert not conn.status.is_callable()
    assert status(lifecycle)["error_code"] == "local_invalidation_failed"
    assert not lifecycle.resume("conn_1", "admin")


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["invalidate", "replace"])
async def test_token_manager_late_refresh_is_rejected(action):
    entered, release = asyncio.Event(), asyncio.Event()

    async def refresh(token):
        entered.set()
        await release.wait()
        return {"access_token": "late", "expires_in": 3600}

    manager = TokenManager(Mock(refresh_token=refresh), org_id="org_1")
    manager.store_token("conn_1", "old", "refresh", 1)
    pending = asyncio.create_task(manager.get_valid_token("conn_1"))
    await asyncio.wait_for(entered.wait(), 5)
    if action == "invalidate":
        assert manager.invalidate_connector("conn_1") == 1
        assert manager.get_generation("conn_1") == 1
    else:
        manager.store_token("conn_1", "replacement", "refresh", 3600)
    release.set()
    with pytest.raises(ValueError):
        await pending
    if action == "invalidate":
        with pytest.raises(ValueError):
            await manager.get_valid_token("conn_1")
        with pytest.raises(ValueError):
            manager.store_token("conn_1", "late", "refresh", 3600, expected_generation=0)
    else:
        assert await manager.get_valid_token("conn_1") == "replacement"


@pytest.mark.asyncio
async def test_token_manager_refresh_and_scoped_integration():
    handler = Mock(refresh_token=AsyncMock(return_value={
        "access_token": "fresh", "expires_in": 3600,
    }))
    first = TokenManager(handler, org_id="org_1")
    second = TokenManager(handler, org_id="other")
    for manager in (first, second):
        manager.store_token("conn_1", "old", "refresh", 1)
    assert await first.get_valid_token("conn_1") == "fresh"
    assert await first.get_valid_token("conn_1") == "fresh"
    with pytest.raises(ValueError):
        AuthorizationManager(token_managers=[TokenManager(handler)])
    auth = AuthorizationManager(token_managers=[first, second])
    assert auth.invalidate_connector_credentials("conn_1", "org_1", "pause", "admin")[
        "cleared_count"
    ] == 1
    assert second.get_generation("conn_1") == 0
    assert await second.get_valid_token("conn_1") == "fresh"


@pytest.mark.asyncio
async def test_real_http_managed_credentials_are_fresh_after_resume(env):
    observed = []

    async def receive(request):
        observed.append(request.headers.get("Authorization"))
        return web.json_response({"result": "ok"})

    app = web.Application()
    app.router.add_post("/mcp/tools/call", receive)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        add(env, auth=AuthConfig(mode=AuthenticationMode.API_KEY,
                                        api_key_ref="vault://key-1"),
                   endpoint=f"http://127.0.0.1:{runner.addresses[0][1]}")
        client, _, cdp = _adapter(retry_delay_seconds=0)
        auth = AuthorizationManager(client)
        env[3].authorization_manager = auth
        env[3].http_executor.allow_private_networks = True
        lifecycle = LifecycleManager(env[0], authorization_manager=auth)
        assert "result" in await rpc(env, "tools/call")
        assert observed[0]
        assert lifecycle.pause("conn_a", "pause", "admin")
        assert (await rpc(env, "tools/call"))["error"]["code"] == -32050
        assert len(observed) == 1
        assert cdp.get_rental_stats()["total_active_rentals"] == 0
        assert lifecycle.resume("conn_a", "admin")
        assert "result" in await rpc(env, "tools/call")
        assert len(observed) == 2 and observed[0] != observed[1]
        started, release = asyncio.Event(), asyncio.Event()
        original_prepare = env[3]._prepare_injection

        async def held_preparation(*args):
            prepared = await original_prepare(*args)
            started.set()
            await release.wait()
            return prepared

        env[3]._prepare_injection = held_preparation
        pending = asyncio.create_task(rpc(env, "tools/call"))
        await asyncio.wait_for(started.wait(), 5)
        try:
            assert lifecycle.pause("conn_a", "second pause", "admin")
            assert lifecycle.resume("conn_a", "admin")
        finally:
            release.set()
        rejected = (await pending)["error"]
        assert rejected["code"] == -32051  # Executor failure after protocol preflight passed.
        assert "no longer callable" in rejected["message"]
        assert len(observed) == 2  # Old prepared credentials never reached the actual socket.
        env[3]._prepare_injection = original_prepare
        assert "result" in await rpc(env, "tools/call")
        assert len(observed) == 3 and observed[2] != observed[1]
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["pause_resume", "credentials_only"])
async def test_executor_generation_fence_blocks_old_preparation(env, monkeypatch, operation):
    conn = add(env)
    auth = AuthorizationManager()
    env[3].authorization_manager = auth
    lifecycle = LifecycleManager(env[0], authorization_manager=auth)
    started, release = asyncio.Event(), asyncio.Event()

    async def prepare(*args):
        started.set()
        await release.wait()
        return None, None  # No auth required, but the old invocation still must be rejected.

    monkeypatch.setattr(env[3], "_prepare_injection", prepare)
    env[3]._execute = AsyncMock()
    pending = asyncio.create_task(env[3].execute_tool(ORG, "u", conn, tool(), {}))
    await asyncio.wait_for(started.wait(), 5)
    if operation == "pause_resume":
        assert lifecycle.pause("conn_a", "pause", "admin")
        assert lifecycle.resume("conn_a", "admin")
    else:
        auth.begin_invalidation("conn_a", ORG, AuthenticationMode.NONE)
        auth.finish_invalidation("conn_a", ORG, "admin")
    release.set()
    result = await pending
    assert not result.success
    assert result.metadata["blocked_by"] == (
        "lifecycle" if operation == "pause_resume" else "credentials"
    )
    env[3]._execute.assert_not_called()
    assert env[2].quota_manager.get_quota(ORG).current_usage == 0


def test_initial_approval_is_not_credential_invalidation():
    conn, auth, lifecycle, _, _, _ = assembly(AuthenticationMode.OAUTH2_PKCE)
    conn.status.lifecycle_state = S.DRAFT
    for state in (S.PENDING_VERIFICATION, S.PENDING_APPROVAL, S.APPROVED_INACTIVE, S.ACTIVE):
        assert lifecycle.transition_to("conn_1", state, "initial approval", "admin")
    assert status(lifecycle) is None
    assert auth.get_credential_generation("conn_1", "org_1") == 0
    store(auth)
    assert auth.prepare_credentials(conn, "org_1", "u1")["access_token"] == "synthetic-access"


@pytest.mark.parametrize("result", [False, "missing", "raise"])
def test_provider_resume_refusal_or_exception_is_fail_closed(monkeypatch, result):
    _, auth, lifecycle, client, _, _ = assembly()
    assert lifecycle.pause("conn_1", "pause", "admin")
    resume = None if result == "missing" else Mock(return_value=False)
    if result == "raise":
        resume = Mock(side_effect=ConnectionError("synthetic unavailable"))
    monkeypatch.setattr(client, "resume_connector_credentials", resume)
    assert not lifecycle.resume("conn_1", "admin")
    assert ("org_1", "conn_1") in auth._blocked


def test_concurrent_stop_cannot_overwrite_newer_generation(monkeypatch):
    _, auth, lifecycle, client, _, _ = assembly()
    entered, release = Event(), Event()
    original = client.revoke_connector_credentials

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(client, "revoke_connector_credentials", delayed)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(lifecycle.pause, "conn_1", "pause", "admin")
        try:
            assert entered.wait(5)
            monkeypatch.setattr(client, "revoke_connector_credentials", original)
            assert lifecycle.pause("conn_1", "retry", "admin")
            assert status(lifecycle)["generation"] == 2
            assert status(lifecycle)["credential_revocation_status"] == "partial"
            assert not lifecycle.resume("conn_1", "admin")
        finally:
            release.set()
        assert pending.result(5)
    assert status(lifecycle)["generation"] == 2
    assert status(lifecycle)["credential_revocation_status"] == "complete"
    assert lifecycle.resume("conn_1", "admin")


def test_adapter_worker_capacity_retains_unprocessed_handles(monkeypatch):
    client, _, cdp = _adapter(revoke_timeout_seconds=0.001, retry_delay_seconds=0)
    for _ in range(9):
        _issue(client)
    release = Event()
    original = cdp.revoke_token

    def delayed(*args, **kw):
        assert release.wait(5)
        original(*args, **kw)

    monkeypatch.setattr(cdp, "revoke_token", delayed)
    try:
        outcome = client.revoke_connector_credentials("conn_1", "org_1", "pause")
        assert outcome["pending_count"] == 9
        assert len(client._jobs) == 8
        jobs = list(client._jobs.values())
    finally:
        release.set()
    assert all(job.wait(5) for job in jobs)
    assert client.revoke_connector_credentials("conn_1", "org_1", "retry")[
        "credential_revocation_status"
    ] == "complete"
    assert cdp.get_rental_stats()["total_active_rentals"] == 0


@pytest.mark.parametrize("options", [
    {"revoke_timeout_seconds": 0}, {"revoke_timeout_seconds": float("nan")},
    {"retry_delay_seconds": -1}, {"retry_delay_seconds": float("inf")},
])
def test_revocation_timeout_configuration_validated(options):
    with pytest.raises(ValueError):
        _adapter(**options)


def test_invalid_issued_expiry_is_revoked(monkeypatch):
    client, _, cdp = _adapter(retry_delay_seconds=0)
    original = cdp.issue_token

    def issue(*args, **kw):
        result = original(*args, **kw)
        result.expires_at = None
        return result

    monkeypatch.setattr(cdp, "issue_token", issue)
    with pytest.raises(CredentialIssuanceError, match="expiry"):
        _issue(client)
    assert cdp.get_rental_stats()["total_active_rentals"] == 0


def test_direct_authorization_status_and_all_modes(monkeypatch):
    conn, auth, lifecycle, _, _, _ = assembly(AuthenticationMode.BEARER_TOKEN)
    assert not auth.check_authorization_status(conn, "org_1", "u1")["authorized"]
    assert auth.prepare_credentials(conn, "org_1", "u1") is None
    auth._token_cache[("org_1", "u1", "conn_1")] = {"token": "synthetic"}
    assert auth.prepare_credentials(conn, "org_1", "u1") is None
    assert not auth.check_authorization_status(conn, "org_1", "u1")["authorized"]
    auth._token_cache[("org_1", "u1", "conn_1")]["expires_at"] = (
        datetime.utcnow() + timedelta(hours=1)
    )
    assert auth.prepare_credentials(conn, "org_1", "u1")["token"] == "synthetic"
    assert auth.check_authorization_status(conn, "org_1", "u1")["authorized"]
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert not auth.prepare_credentials(conn, "org_1", "u1")
    conn, auth, _, _, _, _ = assembly(AuthenticationMode.MTLS)
    assert auth.prepare_credentials(conn, "org_1", "u1") is None
    conn.config.auth.certificate_fingerprint = "synthetic-fingerprint"
    assert auth.prepare_credentials(conn, "org_1", "u1")["type"] == "mtls"
    conn.config.auth.mode = "unknown"
    auth.audit_logger = None
    assert auth.prepare_credentials(conn, "org_1", "u1") is None


def test_managed_leases_also_revoked_when_cache_has_unsupported_credentials():
    conn, auth, lifecycle, _, _, cdp = assembly()
    assert auth.prepare_credentials(conn, "org_1", "u1")
    store(auth)
    assert lifecycle.pause("conn_1", "pause", "admin")
    assert cdp.get_rental_stats()["total_active_rentals"] == 0
    assert status(lifecycle)["credential_revocation_status"] == "unsupported"


def test_refresh_audit_failure_does_not_store_late_response(monkeypatch):
    conn, auth, lifecycle, _, _, _ = assembly(AuthenticationMode.OAUTH2_PKCE)
    store(auth, expires_in=1)
    monkeypatch.setattr(auth.audit_logger, "log_token_refresh", Mock(side_effect=OSError("test")))
    monkeypatch.setattr(auth, "_refresh_oauth_token", lambda **kw: None)
    assert auth.prepare_credentials(conn, "org_1", "u1") is None
    assert lifecycle.pause("conn_1", "pause", "admin")


def test_refresh_default_client_and_bad_ttl_keep_existing_contract(monkeypatch):
    import httpx

    from tests.test_mcp_auth_manager import _jwt, _oauth_connector

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "access_token": _jwt(), "expires_in": "invalid",
    }))
    client = httpx.Client(transport=transport)
    monkeypatch.setattr(httpx, "Client", lambda: client)
    auth = AuthorizationManager()
    conn = _oauth_connector()
    store(auth, expires_in=1, refresh_token="synthetic-refresh")
    assert auth.prepare_credentials(conn, "org_1", "u1")["access_token"]


def test_internal_transition_unknown_connector_returns_false():
    lifecycle = LifecycleManager(ConnectorRegistry())
    assert not lifecycle._transition_state("missing", S.ACTIVE, "missing")
