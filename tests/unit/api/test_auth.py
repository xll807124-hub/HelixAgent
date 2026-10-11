"""鉴权中间件测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient


class TestAuth:
    """Bearer Token 鉴权。"""

    def test_missing_token_returns_401(self, client: TestClient) -> None:
        """无 token：401 UNAUTHENTICATED。"""
        r = client.get("/api/v1/tasks")
        assert r.status_code == 401
        body = r.json()
        assert body["code"] == 40301  # APIErrorCode.UNAUTHENTICATED
        assert "Bearer" in r.headers.get("WWW-Authenticate", "")

    def test_malformed_token_returns_401(self, client: TestClient) -> None:
        """非 Bearer 头：401。"""
        r = client.get(
            "/api/v1/tasks",
            headers={"Authorization": "Token abc"},  # noqa: S106
        )
        assert r.status_code == 401

    def test_empty_bearer_returns_401(self, client: TestClient) -> None:
        """Bearer 但空 token：401。"""
        r = client.get(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer "},
        )
        assert r.status_code == 401

    def test_valid_token_passes(self, client: TestClient) -> None:
        """合法 token：通过鉴权。"""
        r = client.get(
            "/api/v1/tasks?limit=1",
            headers={"Authorization": "Bearer valid-token-abc"},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 0

    def test_health_exempt_from_auth(self, client: TestClient) -> None:
        """/health 走白名单，无需鉴权。"""
        r = client.get("/health")
        assert r.status_code == 200
