"""TaskBranchApprovalPolicy 与 ApprovalAwarePolicyGateway 单元测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.security.policy_gateway import PolicyDecision, SimplifiedPolicyGateway
from src.tools import ToolRegistry
from src.tools.file.write import FileWriteTool
from src.tools.test.pytest_runner import PytestRunnerTool
from src.workers.coder.approval import (
    ApprovalAwarePolicyGateway,
    TaskBranchApprovalPolicy,
)

TASK_BRANCH = "fix/issue-1"


def _branch(name: str):
    async def provider() -> str:
        return name

    return provider


def _policy(
    repo: Path,
    *,
    current: str = TASK_BRANCH,
    task_branch: str = TASK_BRANCH,
    allowed: list[str] | None = None,
) -> TaskBranchApprovalPolicy:
    return TaskBranchApprovalPolicy(
        repo_path=str(repo),
        task_branch=task_branch,
        base_branch="main",
        allowed_paths=[str(repo)] if allowed is None else allowed,
        branch_provider=_branch(current),
    )


def _gateway(policy: TaskBranchApprovalPolicy) -> ApprovalAwarePolicyGateway:
    registry = ToolRegistry()
    registry.register(FileWriteTool())
    registry.register(PytestRunnerTool())
    return ApprovalAwarePolicyGateway(SimplifiedPolicyGateway(registry), policy)


def _ctx(allowed: list[str]) -> dict:
    return {
        "user_id": "u",
        "organization_id": "o",
        "project_id": "p",
        "task_id": "t",
        "trace_id": "0" * 32,
        "allowed_paths": allowed,
    }


@pytest.mark.asyncio
async def test_policy_approves_write_in_task_branch(tmp_path: Path):
    decision = await _policy(tmp_path).evaluate(
        "file-write", {"path": str(tmp_path / "a.py"), "content": "x"}
    )
    assert decision.approved
    assert decision.branch == TASK_BRANCH


@pytest.mark.asyncio
async def test_policy_rejects_wrong_branch(tmp_path: Path):
    decision = await _policy(tmp_path, current="main").evaluate(
        "file-write", {"path": str(tmp_path / "a.py"), "content": "x"}
    )
    assert not decision.approved


@pytest.mark.asyncio
async def test_policy_rejects_path_outside_allowed(tmp_path: Path):
    allowed = tmp_path / "src"
    allowed.mkdir()
    decision = await _policy(tmp_path, allowed=[str(allowed)]).evaluate(
        "file-write", {"path": str(tmp_path / "other.py"), "content": "x"}
    )
    assert not decision.approved


@pytest.mark.asyncio
async def test_policy_rejects_non_whitelisted_tool(tmp_path: Path):
    decision = await _policy(tmp_path).evaluate("pytest-run", {"test_path": str(tmp_path)})
    assert not decision.approved


@pytest.mark.asyncio
async def test_policy_rejects_empty_allowed_paths(tmp_path: Path):
    decision = await _policy(tmp_path, allowed=[]).evaluate(
        "file-write", {"path": str(tmp_path / "a.py"), "content": "x"}
    )
    assert not decision.approved


@pytest.mark.asyncio
async def test_policy_rejects_commit_to_other_repo(tmp_path: Path):
    other = tmp_path / "other"
    other.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    decision = await _policy(repo).evaluate(
        "git-commit", {"repo_path": str(other), "message": "m"}
    )
    assert not decision.approved


@pytest.mark.asyncio
async def test_gateway_upgrades_to_allow_and_records(tmp_path: Path):
    gateway = _gateway(_policy(tmp_path))
    result = await gateway.check_pre_execution(
        "a1",
        "file-write",
        {"path": str(tmp_path / "a.py"), "content": "x = 1\n"},
        _ctx([str(tmp_path)]),
    )
    assert result.decision == PolicyDecision.ALLOW
    assert result.metadata.get("auto_approved") is True
    assert [r.action_id for r in gateway.records] == ["a1"]
    assert gateway.records[0].branch == TASK_BRANCH


@pytest.mark.asyncio
async def test_gateway_keeps_inner_deny(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    gateway = _gateway(_policy(tmp_path, allowed=[str(allowed)]))
    result = await gateway.check_pre_execution(
        "a2",
        "file-write",
        {"path": str(tmp_path / "outside.py"), "content": "x"},
        _ctx([str(allowed)]),
    )
    assert result.decision == PolicyDecision.DENY
    assert gateway.records == []


@pytest.mark.asyncio
async def test_gateway_denies_when_context_allowed_paths_empty(tmp_path: Path):
    gateway = _gateway(_policy(tmp_path))
    result = await gateway.check_pre_execution(
        "a3",
        "file-write",
        {"path": str(tmp_path / "a.py"), "content": "x"},
        _ctx([]),
    )
    assert result.decision == PolicyDecision.DENY
    assert gateway.records == []


@pytest.mark.asyncio
async def test_gateway_keeps_requires_approval_on_wrong_branch(tmp_path: Path):
    gateway = _gateway(_policy(tmp_path, current="main"))
    result = await gateway.check_pre_execution(
        "a4",
        "file-write",
        {"path": str(tmp_path / "a.py"), "content": "x"},
        _ctx([str(tmp_path)]),
    )
    assert result.decision == PolicyDecision.REQUIRES_APPROVAL
    assert "auto_approval_denied" in result.metadata
    assert gateway.records == []


@pytest.mark.asyncio
async def test_gateway_passes_through_allow(tmp_path: Path):
    gateway = _gateway(_policy(tmp_path))
    result = await gateway.check_pre_execution(
        "a5", "pytest-run", {"test_path": str(tmp_path)}, _ctx([str(tmp_path)])
    )
    assert result.decision == PolicyDecision.ALLOW
    assert gateway.records == []
