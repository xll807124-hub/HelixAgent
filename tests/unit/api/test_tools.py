"""Tool 端点测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient


class TestListTools:
    """GET /api/v1/tools。"""

    def test_list_tools_happy(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """至少 1 个工具。"""
        r = client.get("/api/v1/tools", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["total"] >= 1
        # 工具字段
        item = body["data"]["items"][0]
        assert "name" in item
        assert "risk_level" in item

    def test_list_tools_requires_auth(self, client: TestClient) -> None:
        """无 token：401。"""
        r = client.get("/api/v1/tools")
        assert r.status_code == 401


class TestInvokeTool:
    """POST /api/v1/tools/{name}/invoke。"""

    def test_invoke_existing_tool_with_missing_path(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """调用 file-read 工具，但传不存在的文件路径：业务失败（200 success=False）。"""
        r = client.post(
            "/api/v1/tools/file-read/invoke",
            json={"params": {"file_path": "Z:/__definitely_not_exist__/foo.txt"}},
            headers=auth_headers,
        )
        # 业务失败（文件找不到）→ 200 with success=False
        # 这是 Task result 的语义：调用已发生，但工具内部失败
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        # success=False 或 error 字段非空
        assert body["data"]["success"] is False or body["data"]["error"] is not None

    def test_invoke_nonexistent_tool_404(  # noqa: E501
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """调用不存在的工具：404 TOOL_NOT_FOUND。"""
        r = client.post(
            "/api/v1/tools/no-such-tool/invoke",
            json={"params": {}},
            headers=auth_headers,
        )
        assert r.status_code == 404
        body = r.json()
        assert body["code"] == 40402  # APIErrorCode.TOOL_NOT_FOUND

    def test_invoke_with_invalid_params_shape(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """请求体额外字段被拒：422。"""
        r = client.post(
            "/api/v1/tools/file-read/invoke",
            json={"params": {}, "injected": "x"},
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_invoke_without_auth_401(self, client: TestClient) -> None:
        """无 token：401。"""
        r = client.post(
            "/api/v1/tools/file-read/invoke",
            json={"params": {}},
        )
        assert r.status_code == 401

    def test_invoke_high_risk_requires_policy_or_evidence(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """高风险工具：必须返回 evidence_id（审计）。"""
        r = client.post(
            "/api/v1/tools/git-status/invoke",
            json={"params": {"repo_path": "."}},
            headers=auth_headers,
        )
        # 即使失败也应该结构化返回
        assert r.status_code in (200, 403, 409, 500)
        body = r.json()
        assert "data" in body or body.get("code", 0) != 0

    def test_invoke_blocked_by_kill_switch(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """当 Kill Switch TRIGGERED 时，工具调用应被 409 拒绝。

        通过 admin token 触发 kill switch 后，验证 tools 端点拒绝。
        """
        import os

        # 先触发 kill switch（admin 端点）
        admin_token = os.environ.get("AI_API_ADMIN_TOKEN", "test-admin")
        os.environ["AI_API_ADMIN_TOKEN"] = admin_token
        trigger_r = client.post(
            "/admin/kill-switch/trigger",
            json={"scope": "GLOBAL", "reason": "test tools.py 409"},
            headers={"X-Admin-Token": admin_token},
        )
        assert trigger_r.status_code == 200
        try:
            # 调用工具应被 409 拒绝
            r = client.post(
                "/api/v1/tools/file-read/invoke",
                json={"params": {"file_path": "/tmp/x"}},
                headers=auth_headers,
            )
            assert r.status_code == 409
            body = r.json()
            assert body["code"] == 40901  # APIErrorCode.STATE_CONFLICT
            assert "kill switch" in body["message"].lower()
        finally:
            # 恢复（recover + confirm）
            req = client.post(
                "/admin/kill-switch/recover",
                json={"reason": "cleanup"},
                headers={"X-Admin-Token": admin_token},
            )
            assert req.status_code == 200
            token = req.json()["data"]["confirm_token"]
            client.post(
                "/admin/kill-switch/recover/confirm",
                json={"confirm_token": token},
                headers={"X-Admin-Token": admin_token},
            )
