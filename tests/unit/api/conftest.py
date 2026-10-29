"""API 层测试公共 fixtures。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.config import get_settings
from src.api.main import create_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """创建 FastAPI 应用实例（lifespan 不自动跑，依赖 FastAPI 上下文）。"""
    monkeypatch.setenv("AI_API_AUTH_REQUIRED", "true")
    monkeypatch.setenv(
        "AI_API_AUTH_TOKENS",
        '{"demo-token-abc12345": "00000000-0000-0000-0000-000000000010"}',
    )
    monkeypatch.setenv("AI_API_TOOL_ALLOWED_PATHS", json.dumps([str(tmp_path)]))
    get_settings.cache_clear()
    yield create_app()
    get_settings.cache_clear()


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
