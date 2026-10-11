"""Coder Worker 测试共用夹具。"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from src.workers.coder.models import CoderTaskSpec


def make_spec(repo: Path, **overrides: object) -> CoderTaskSpec:
    data: dict[str, object] = {
        "task_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "worker_id": str(uuid.uuid4()),
        "trace_id": uuid.uuid4().hex,
        "issue_title": "修复 add 函数",
        "issue_description": "add(1, 2) 应返回 3",
        "repo_path": str(repo),
        "task_branch": "fix/issue-1",
        "test_path": str(repo / "tests"),
        "allowed_paths": [str(repo)],
    }
    data.update(overrides)
    return CoderTaskSpec(**data)  # type: ignore[arg-type]


@pytest.fixture
def spec(tmp_path: Path) -> CoderTaskSpec:
    return make_spec(tmp_path)
