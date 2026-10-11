"""Kill Switch Admin API 单元测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def admin_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个用例前注入 admin token。"""
    monkeypatch.setenv("AI_API_ADMIN_TOKEN", "test-admin-secret-token")


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "test-admin-secret-token"}


def _user_headers() -> dict[str, str]:
    return {"Authorization": "Bearer user-token"}


@pytest.fixture
def client() -> TestClient:
    from src.api.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


class TestStatus:
    def test_status_initial_idle(self, client: TestClient) -> None:
        r = client.get("/admin/kill-switch/status", headers=_admin_headers())
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["state"] == "IDLE"
        assert body["data"]["total_triggers"] == 0

    def test_status_without_admin_token_403(self, client: TestClient) -> None:
        """无 admin token 头：403 PERMISSION_DENIED。"""
        r = client.get("/admin/kill-switch/status")
        assert r.status_code == 403

    def test_status_with_wrong_token_403(self, client: TestClient) -> None:
        r = client.get(
            "/admin/kill-switch/status",
            headers={"X-Admin-Token": "wrong"},
        )
        assert r.status_code == 403


class TestTriggerAndRecover:
    def test_full_lifecycle(self, client: TestClient) -> None:
        """trigger → status → recover → confirm → status (IDLE)."""
        # 1. trigger
        r = client.post(
            "/admin/kill-switch/trigger",
            json={
                "scope": "GLOBAL",
                "reason": "smoke test",
                "trigger_source": "manual",
            },
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        assert r.json()["data"]["scope"] == "GLOBAL"

        # 2. status 应该是 TRIGGERED
        r = client.get("/admin/kill-switch/status", headers=_admin_headers())
        assert r.json()["data"]["state"] == "TRIGGERED"

        # 3. recover
        r = client.post(
            "/admin/kill-switch/recover",
            json={"reason": "fixed"},
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        confirm_token = r.json()["data"]["confirm_token"]
        assert confirm_token

        # 4. confirm
        r = client.post(
            "/admin/kill-switch/recover/confirm",
            json={"confirm_token": confirm_token},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

        # 5. status 回到 IDLE
        r = client.get("/admin/kill-switch/status", headers=_admin_headers())
        assert r.json()["data"]["state"] == "IDLE"

    def test_trigger_invalid_body_422(self, client: TestClient) -> None:
        r = client.post(
            "/admin/kill-switch/trigger",
            json={"scope": "INVALID", "reason": "x"},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_recover_from_idle_409(self, client: TestClient) -> None:
        r = client.post(
            "/admin/kill-switch/recover",
            json={"reason": "x"},
            headers=_admin_headers(),
        )
        assert r.status_code == 409


class TestTriggerManagement:
    def test_enable_disable_trigger(self, client: TestClient) -> None:
        # 启用
        r = client.post(
            "/admin/kill-switch/triggers/credential_leak/enable",
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        assert r.json()["data"]["enabled"] is True

        # 禁用
        r = client.post(
            "/admin/kill-switch/triggers/credential_leak/disable",
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        assert r.json()["data"]["enabled"] is False

    def test_unknown_trigger_404(self, client: TestClient) -> None:
        r = client.post(
            "/admin/kill-switch/triggers/nonexistent/enable",
            headers=_admin_headers(),
        )
        assert r.status_code == 404


class TestAdminAuthRequired:
    def test_no_token_returns_503_or_403(self, client: TestClient) -> None:
        """无 admin token：503（未配置时）或 403。"""
        # 已设 env，token 不对 → 403
        r = client.get(
            "/admin/kill-switch/status",
            headers={"X-Admin-Token": "wrong"},
        )
        assert r.status_code == 403

    def test_user_bearer_insufficient(self, client: TestClient) -> None:
        """普通 bearer token 不够（必须 admin token）。"""
        r = client.get(
            "/admin/kill-switch/status",
            headers=_user_headers(),
        )
        assert r.status_code == 403
