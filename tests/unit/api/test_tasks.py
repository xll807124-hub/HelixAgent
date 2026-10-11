"""Task 端点测试。"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


class TestCreateTask:
    """POST /api/v1/tasks。"""

    def test_create_happy_path(
        self, client: TestClient, auth_headers: dict[str, str], valid_task_payload: dict[str, Any]
    ) -> None:
        """合法 payload：201。"""
        r = client.post("/api/v1/tasks", json=valid_task_payload, headers=auth_headers)
        assert r.status_code == 201
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "CREATED"
        assert "task_id" in body["data"]
        # trace_id 必返回
        assert body["trace_id"]

    def test_create_with_dynamic_base_revision_422(
        self, client: TestClient, auth_headers: dict[str, str], valid_task_payload: dict[str, Any]
    ) -> None:
        """base_revision='latest' 应被业务层拒（422）。"""
        payload = {**valid_task_payload, "base_revision": "latest"}
        r = client.post("/api/v1/tasks", json=payload, headers=auth_headers)
        assert r.status_code == 422
        assert r.json()["code"] == 42201

    def test_create_with_short_base_revision_accepted(
        self, client: TestClient, auth_headers: dict[str, str], valid_task_payload: dict[str, Any]
    ) -> None:
        """短 base_revision（如分支名）目前被允许（仅禁 latest/main/head/master）。

        业务层仅做最严的"动态引用"拦截；具体 SHA 长度由调用方保证。
        """
        payload = {**valid_task_payload, "base_revision": "abc"}
        r = client.post("/api/v1/tasks", json=payload, headers=auth_headers)
        assert r.status_code == 201

    def test_create_with_blank_title_422(
        self, client: TestClient, auth_headers: dict[str, str], valid_task_payload: dict[str, Any]
    ) -> None:
        """空 title：422。"""
        payload = {**valid_task_payload, "title": ""}
        r = client.post("/api/v1/tasks", json=payload, headers=auth_headers)
        assert r.status_code == 422

    def test_create_with_extra_field_422(
        self, client: TestClient, auth_headers: dict[str, str], valid_task_payload: dict[str, Any]
    ) -> None:
        """extra=forbid：客户端注入未知字段 → 422。"""
        payload = {**valid_task_payload, "injected": "evil"}
        r = client.post("/api/v1/tasks", json=payload, headers=auth_headers)
        assert r.status_code == 422

    def test_create_without_auth_401(  # noqa: E501
        self, client: TestClient, valid_task_payload: dict[str, Any]
    ) -> None:
        """无 token：401。"""
        r = client.post("/api/v1/tasks", json=valid_task_payload)
        assert r.status_code == 401


class TestGetTask:
    """GET /api/v1/tasks/{id}。"""

    def test_get_existing_task(
        self, client: TestClient, auth_headers: dict[str, str], valid_task_payload: dict[str, Any]
    ) -> None:
        """先创建，再查：200。"""
        create = client.post("/api/v1/tasks", json=valid_task_payload, headers=auth_headers)
        task_id = create.json()["data"]["task_id"]
        r = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["task_id"] == task_id

    def test_get_missing_task_404(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """不存在：404。"""
        r = client.get(
            "/api/v1/tasks/00000000-0000-0000-0000-000000000000", headers=auth_headers
        )
        assert r.status_code == 404
        assert r.json()["code"] == 40401


class TestListTasks:
    """GET /api/v1/tasks。"""

    def test_list_pagination(
        self, client: TestClient, auth_headers: dict[str, str], valid_task_payload: dict[str, Any]
    ) -> None:
        """分页参数生效。"""
        for _ in range(3):
            client.post("/api/v1/tasks", json=valid_task_payload, headers=auth_headers)
        r = client.get("/api/v1/tasks?limit=2&offset=0", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert body["total"] >= 3
        assert len(body["items"]) <= 2

    def test_list_limit_too_big_422(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """limit > 200：422。"""
        r = client.get("/api/v1/tasks?limit=10000", headers=auth_headers)
        assert r.status_code == 422

    def test_list_negative_offset_422(  # noqa: E501
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """offset < 0：422。"""
        r = client.get("/api/v1/tasks?offset=-1", headers=auth_headers)
        assert r.status_code == 422


class TestCancelTask:
    """DELETE /api/v1/tasks/{id}。"""

    def test_cancel_happy_path(
        self, client: TestClient, auth_headers: dict[str, str], valid_task_payload: dict[str, Any]
    ) -> None:
        """先创建，再取消：200。"""
        create = client.post("/api/v1/tasks", json=valid_task_payload, headers=auth_headers)
        task_id = create.json()["data"]["task_id"]
        r = client.delete(f"/api/v1/tasks/{task_id}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "CANCELLED"

    def test_cancel_missing_404(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """不存在：404。"""
        r = client.delete(
            "/api/v1/tasks/00000000-0000-0000-0000-000000000000", headers=auth_headers
        )
        assert r.status_code == 404

    def test_cancel_already_terminal_409(
        self, client: TestClient, auth_headers: dict[str, str], valid_task_payload: dict[str, Any]
    ) -> None:
        """已取消的 Task 再次取消：409。"""
        create = client.post("/api/v1/tasks", json=valid_task_payload, headers=auth_headers)
        task_id = create.json()["data"]["task_id"]
        client.delete(f"/api/v1/tasks/{task_id}", headers=auth_headers)
        r = client.delete(f"/api/v1/tasks/{task_id}", headers=auth_headers)
        assert r.status_code == 409
        assert r.json()["code"] == 40902
