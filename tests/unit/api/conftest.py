"""API 层测试公共 fixtures。"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app


@pytest.fixture
def app() -> Any:
    """创建 FastAPI 应用实例（lifespan 不自动跑，依赖 FastAPI 上下文）。"""
    return create_app()


@pytest.fixture
def client(app: Any) -> TestClient:
    """FastAPI TestClient（带 lifespan 初始化）。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Bearer token 鉴权头。"""
    return {"Authorization": "Bearer demo-token-abc12345"}


@pytest.fixture
def valid_task_payload() -> dict[str, Any]:
    """创建 Task 的合法 payload。"""
    return {
        "title": "Test task",
        "description": "Task created by unit test",
        "risk_level": "LOW",
        "source_type": "NATURAL_LANGUAGE",
        "workflow_template_id": "wf-template-1",
        "workflow_template_version": "v1.0.0",
        "base_revision": "0123456789abcdef0123456789abcdef01234567",
    }
