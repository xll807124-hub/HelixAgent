"""健康检查端点测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient


class TestLiveness:
    """GET /health：存活探针。"""

    def test_health_no_auth_required(self, client: TestClient) -> None:
        """无需鉴权。"""
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "alive"
        assert r.headers.get("X-Trace-Id")  # 必须有 trace_id 头

    def test_health_trace_id_passthrough(self, client: TestClient) -> None:
        """客户端提供合法 trace_id 时应原样回传。"""
        valid_trace = "0123456789abcdef0123456789abcdef"
        r = client.get("/health", headers={"X-Trace-Id": valid_trace})
        assert r.status_code == 200
        assert r.headers["X-Trace-Id"] == valid_trace

    def test_health_invalid_trace_id_generated(self, client: TestClient) -> None:
        """非法 trace_id 时服务端应自动生成。"""
        r = client.get("/health", headers={"X-Trace-Id": "not-a-valid-trace-id"})
        assert r.status_code == 200
        # 服务端生成的 trace_id 必须是 32 位 hex
        trace = r.headers["X-Trace-Id"]
        assert len(trace) == 32
        int(trace, 16)  # 16 进制解析不抛错


class TestReadiness:
    """GET /ready：就绪探针。"""

    def test_ready_after_startup(self, client: TestClient) -> None:
        """启动后所有组件应 ok。"""
        r = client.get("/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["components"]["tool_registry"] == "ok"
        assert body["data"]["components"]["policy_gateway"] == "ok"
        assert body["data"]["components"]["task_repository"] == "ok"
