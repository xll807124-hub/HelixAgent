"""ActionBuilder 单元测试。"""
from __future__ import annotations

import pytest

from src.runtime.entities.action import ActionStatus, ActionType
from src.runtime.entities.task import RiskLevel
from src.workers.coder.action_builder import (
    ActionBuilder,
    ActionBuildError,
    compute_idempotency_key,
)
from src.workers.coder.model_client import ToolCall

SHA = "a" * 40


def test_build_write_action(spec):
    call = ToolCall(name="file-write", arguments={"path": f"{spec.repo_path}/a.py", "content": "x"})
    action = ActionBuilder(spec).build(call, step_id="step-1", head_sha=SHA)
    assert action.type == ActionType.WRITE
    assert action.risk_level == RiskLevel.HIGH
    assert action.requires_approval is True
    assert action.source_revision == SHA
    assert action.status_projection == ActionStatus.PROPOSED
    assert action.trace_id == spec.trace_id


def test_build_read_action_targets_file(spec):
    call = ToolCall(name="file-read", arguments={"file_path": f"{spec.repo_path}/a.py"})
    action = ActionBuilder(spec).build(call, step_id="step-1", head_sha=SHA)
    assert action.type == ActionType.READ
    assert action.target_resources[0].resource_type.value == "file"


def test_git_tool_targets_repository(spec):
    call = ToolCall(name="git-status", arguments={"repo_path": spec.repo_path})
    action = ActionBuilder(spec).build(call, step_id="step-1", head_sha=SHA)
    assert action.target_resources[0].resource_type.value == "repository"


def test_unknown_tool_is_rejected(spec):
    with pytest.raises(ActionBuildError):
        ActionBuilder(spec).build(ToolCall(name="rm-rf", arguments={}), step_id="s", head_sha=SHA)


@pytest.mark.parametrize("bad_sha", ["main", "HEAD", "latest"])
def test_dynamic_revision_is_rejected(spec, bad_sha):
    call = ToolCall(name="file-write", arguments={"path": "a.py", "content": "x"})
    with pytest.raises(ActionBuildError):
        ActionBuilder(spec).build(call, step_id="s", head_sha=bad_sha)


def test_idempotency_key_is_stable_and_sensitive():
    k1 = compute_idempotency_key("t", "s1", "file-write", {"a": 1, "b": 2})
    k2 = compute_idempotency_key("t", "s1", "file-write", {"b": 2, "a": 1})
    k3 = compute_idempotency_key("t", "s2", "file-write", {"a": 1, "b": 2})
    assert k1 == k2
    assert k1 != k3
