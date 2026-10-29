"""GitHub HTTP contracts tested without using real credentials or the network."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from src.security.credential.github_proxy import GitHubAppConfig, GitHubCredentialProxy

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("operation, status, expected", [
    ("is_token_valid", 200, True), ("is_token_valid", 401, False),
    ("is_token_valid", 403, False), ("is_token_valid", 500, False),
    ("revoke_token", 204, True), ("revoke_token", 200, False),
    ("revoke_token", 401, False), ("revoke_token", 500, False),
])
async def test_verification_and_revocation_use_remote_result(operation, status, expected):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        proxy = GitHubCredentialProxy(GitHubAppConfig("123", "unused", "unused", "456"), client)
        assert await getattr(proxy, operation)("test-token") is expected
        request = requests[0]
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.method == ("GET" if operation == "is_token_valid" else "DELETE")
        assert request.url.path == (
            "/installation/repositories" if operation == "is_token_valid" else "/installation/token"
        )
        assert "test-token" not in str(proxy.get_audit_log())
        assert bool(proxy.get_audit_log()) == (operation == "revoke_token" and expected)


@pytest.mark.parametrize("operation", ["is_token_valid", "revoke_token"])
async def test_network_failure_cannot_report_success(operation):
    def offline(request):
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as client:
        proxy = GitHubCredentialProxy(GitHubAppConfig("123", "unused", "unused", "456"), client)
        assert await getattr(proxy, operation)("token") is False
        assert await getattr(proxy, operation)("") is False


@pytest.mark.parametrize("change", [
    {"token": ""}, {"token": 1}, {"expires_at": "bad"},
    {"expires_at": "2020-01-01T00:00:00Z"},
    {"expires_at": "2099-01-01T00:00:00"},
    {"permissions": {"contents": "write"}},
    {"permissions": {"administration": "read"}},
])
async def test_invalid_or_broader_token_response_fails_closed(change):
    data = {
        "token": "token", "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "permissions": {"contents": "read"},
    }
    data.update(change)
    proxy = GitHubCredentialProxy(GitHubAppConfig("123", "unused", "unused", "456"))
    proxy._get_jwt_token = AsyncMock(return_value="jwt")
    proxy._request_installation_token = AsyncMock(return_value=data)
    with pytest.raises(ValueError):
        await proxy.get_installation_token(["contents:read"])
    assert proxy.get_audit_log() == []


@pytest.mark.parametrize("options", [
    {"scopes": []}, {"scopes": ["contents:admin"]}, {"scopes": ["administration:write"]},
    {"ttl_seconds": 0}, {"ttl_seconds": -1}, {"ttl_seconds": 3601},
])
async def test_invalid_issuance_options_rejected_before_network(options):
    proxy = GitHubCredentialProxy(GitHubAppConfig("123", "unused", "unused", "456"))
    proxy._get_jwt_token = AsyncMock()
    with pytest.raises(ValueError):
        await proxy.get_installation_token(**options)
    proxy._get_jwt_token.assert_not_called()


async def test_server_expiry_limits_local_token_lifetime():
    expiry = datetime.now(UTC) + timedelta(seconds=50)
    proxy = GitHubCredentialProxy(GitHubAppConfig("123", "unused", "unused", "456"))
    proxy._get_jwt_token = AsyncMock(return_value="jwt")
    proxy._request_installation_token = AsyncMock(return_value={
        "token": "token", "expires_at": expiry.isoformat(), "permissions": {"contents": "read"},
    })
    credential = await proxy.get_installation_token(["contents:read"], ttl_seconds=3600)
    assert credential.expires_at == expiry
