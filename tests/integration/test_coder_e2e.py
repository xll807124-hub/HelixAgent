"""Coder Worker 端到端测试：真实 git 仓库 + 真实工具 + MockModelClient。

场景：calc.add 有 bug，模型按剧本 读文件 -> 修复 -> 跑测试 -> 提交 -> 声明完成。
"""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from src.runtime.entities.evidence import EvidenceType
from src.security.policy_gateway import SimplifiedPolicyGateway
from src.tools import ToolRegistry
from src.tools.executor import ActionExecutor
from src.tools.file.read import FileReadTool
from src.tools.file.write import FileWriteTool
from src.tools.git.commit import GitCommitTool
from src.tools.git.diff import GitDiffTool
from src.tools.git.status import GitStatusTool
from src.tools.test.pytest_runner import PytestRunnerTool
from src.workers.coder.approval import ApprovalAwarePolicyGateway, TaskBranchApprovalPolicy
from src.workers.coder.checkpoint_store import MemoryLoopCheckpointStore
from src.workers.coder.model_client import (
    MockModelClient,
    ModelClientError,
    ModelResponse,
    ToolCall,
)
from src.workers.coder.models import CoderTaskSpec
from src.workers.coder.worker import CoderWorker

BRANCH = "fix/issue-1"
BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST_SRC = (
    "from calc import add\n\n\n"
    "def test_add():\n    assert add(1, 2) == 3\n"
)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n", encoding="utf-8")
    (root / "calc.py").write_text(BUGGY, encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(TEST_SRC, encoding="utf-8")
    (root / "tests" / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent.parent))\n",
        encoding="utf-8",
    )
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "tester")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    _git(root, "checkout", "-b", BRANCH)
    return root


def make_spec(repo: Path, **overrides: object) -> CoderTaskSpec:
    data: dict[str, object] = {
        "task_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "worker_id": str(uuid.uuid4()),
        "trace_id": uuid.uuid4().hex,
        "issue_title": "修复 add",
        "issue_description": "add(1, 2) 应返回 3",
        "repo_path": str(repo),
        "task_branch": BRANCH,
        "test_path": str(repo / "tests"),
        "allowed_paths": [str(repo)],
        "max_iterations": 12,
    }
    data.update(overrides)
    return CoderTaskSpec(**data)  # type: ignore[arg-type]


def build_worker(
    spec: CoderTaskSpec, model: MockModelClient, store: MemoryLoopCheckpointStore | None = None
) -> tuple[CoderWorker, MemoryLoopCheckpointStore]:
    registry = ToolRegistry()
    for tool in (
        FileReadTool(), FileWriteTool(), GitCommitTool(),
        GitDiffTool(), GitStatusTool(), PytestRunnerTool(),
    ):
        registry.register(tool)
    policy = TaskBranchApprovalPolicy(
        repo_path=spec.repo_path,
        task_branch=spec.task_branch,
        base_branch=spec.base_branch,
        allowed_paths=spec.allowed_paths,
    )
    gateway = ApprovalAwarePolicyGateway(SimplifiedPolicyGateway(registry), policy)
    store = store or MemoryLoopCheckpointStore()
    worker = CoderWorker(
        spec=spec,
        model=model,
        executor=ActionExecutor(registry, gateway),
        checkpoint_store=store,
        approval_gateway=gateway,
    )
    return worker, store


def call(name: str, **arguments: object) -> ModelResponse:
    return ModelResponse(thought=f"调用 {name}", tool_call=ToolCall(name=name, arguments=arguments))


def done(summary: str = "已修复") -> ModelResponse:
    return ModelResponse(thought="完成", final_summary=summary)


def fix_script(repo: Path) -> list[ModelResponse | Exception]:
    return [
        call("file-read", file_path=str(repo / "calc.py")),
        call("file-write", path=str(repo / "calc.py"), content=FIXED),
        call("pytest-run", test_path=str(repo / "tests")),
        call("git-commit", repo_path=str(repo), message="fix: add", all=True),
        done(),
    ]


@pytest.mark.asyncio
async def test_happy_path_fixes_bug_and_commits(repo: Path):
    spec = make_spec(repo)
    worker, store = build_worker(spec, MockModelClient(fix_script(repo)))

    result = await worker.run()

    assert result.success, result.error_message
    assert result.verification is not None and result.verification.passed
    assert result.commit_sha == _git(repo, "rev-parse", "HEAD")
    assert result.changed_files == ["calc.py"]
    assert (repo / "calc.py").read_text(encoding="utf-8") == FIXED
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    # 成功后检查点被清理
    assert store.load(spec.task_id) is None
    # 自动审批留下了 APPROVAL_GRANTED 证据（file-write 与 git-commit）
    types = {e.type for e in worker.approval_evidences}
    assert types == {EvidenceType.APPROVAL_GRANTED}
    assert len(worker.approval_evidences) == 2


@pytest.mark.asyncio
async def test_gate_rejects_premature_completion(repo: Path):
    """模型什么都没做就声明完成：闸门多次拒绝后失败，且仓库未被改动。"""
    spec = make_spec(repo)
    model = MockModelClient([done(), done(), done()])
    worker, _ = build_worker(spec, model)

    result = await worker.run()

    assert not result.success
    assert result.verification is not None and not result.verification.passed
    assert result.commit_sha is None
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY

@pytest.mark.asyncio
async def test_resume_after_model_crash(repo: Path):
    """写入后模型崩溃：检查点保留；新 Worker resume 后继续完成任务。"""
    spec = make_spec(repo)
    first_script: list[ModelResponse | Exception] = [
        call("file-write", path=str(repo / "calc.py"), content=FIXED),
        ModelClientError("模拟模型服务中断"),
    ]
    worker1, store = build_worker(spec, MockModelClient(first_script))
    first = await worker1.run()

    assert not first.success
    checkpoint = store.load(spec.task_id)
    assert checkpoint is not None
    assert any(getattr(a, "tool_name", "") == "file-write" for a in checkpoint.actions)

    second_script: list[ModelResponse | Exception] = [
        call("pytest-run", test_path=str(repo / "tests")),
        call("git-commit", repo_path=str(repo), message="fix: add", all=True),
        done(),
    ]
    worker2, _ = build_worker(spec, MockModelClient(second_script), store)
    second = await worker2.resume()

    assert second.success, second.error_message
    assert second.changed_files == ["calc.py"]
    assert store.load(spec.task_id) is None


@pytest.mark.asyncio
async def test_resume_without_checkpoint_fails(repo: Path):
    worker, _ = build_worker(make_spec(repo), MockModelClient([]))
    result = await worker.resume()
    assert not result.success
    assert "检查点" in (result.error_message or "")


@pytest.mark.asyncio
async def test_write_outside_allowed_paths_is_denied(repo: Path, tmp_path: Path):
    """allowed_paths 只含 repo/src：写 calc.py 被拒，文件保持原样。"""
    src = repo / "src"
    src.mkdir()
    spec = make_spec(repo, allowed_paths=[str(src)])
    script: list[ModelResponse | Exception] = [
        call("file-write", path=str(repo / "calc.py"), content=FIXED),
        done(), done(), done(),
    ]
    worker, _ = build_worker(spec, MockModelClient(script))

    result = await worker.run()

    assert not result.success
    assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY
    assert worker.approval_evidences == []


@pytest.mark.asyncio
async def test_failing_tests_block_completion(repo: Path):
    """写入了错误修复并提交，但测试失败：闸门不放行。"""
    spec = make_spec(repo)
    wrong = "def add(a, b):\n    return a * b\n"
    script: list[ModelResponse | Exception] = [
        call("file-write", path=str(repo / "calc.py"), content=wrong),
        call("pytest-run", test_path=str(repo / "tests")),
        call("git-commit", repo_path=str(repo), message="wrong fix", all=True),
        done(), done(), done(),
    ]
    worker, _ = build_worker(spec, MockModelClient(script))

    result = await worker.run()

    assert not result.success
    assert result.verification is not None
    assert result.verification.committed
    assert not result.verification.tests_passed_after_last_write
