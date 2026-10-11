"""
Coder Worker 审批策略与 ApprovalAwarePolicyGateway

对齐：REQ-SEC-003（Policy Gateway）、Least Agency。

背景：file-write / git-commit / git-pr / safe-shell 是 HIGH 风险工具，
SimplifiedPolicyGateway 对它们一律返回 REQUIRES_APPROVAL。Coder 在任务分支内
需要自动完成修复闭环，因此用装饰器包一层：只有在满足全部边界条件时才把
REQUIRES_APPROVAL 升级为 ALLOW，并留下 APPROVAL_GRANTED 记录，其余一律保持原决策。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.security.policy_gateway.base import PolicyDecision, PolicyGateway, PolicyResult

# 允许在任务分支内自动审批的高风险工具白名单
AUTO_APPROVE_TOOLS: frozenset[str] = frozenset(
    {"file-write", "git-commit", "git-pr", "safe-shell"}
)

BranchProvider = Callable[[], Awaitable[str]]


class ApprovalRecord(BaseModel):
    """一次自动审批的审计记录，由 Worker 转成 APPROVAL_GRANTED Evidence。"""

    model_config = ConfigDict(frozen=True)

    action_id: str
    tool_name: str
    branch: str
    reason: str
    granted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalDecision(BaseModel):
    """审批策略的判定结果。"""

    model_config = ConfigDict(frozen=True)

    approved: bool
    reason: str
    branch: str = ""


class ApprovalPolicy(Protocol):
    """审批策略接口。"""

    async def evaluate(self, tool_name: str, params: dict[str, Any]) -> ApprovalDecision: ...


def is_within(path: Path, roots: list[str]) -> bool:
    """path 解析后是否位于任一 root 之下。"""
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except (ValueError, OSError, RuntimeError):
            continue
    return False


async def git_current_branch(repo_path: str) -> str:
    """读取仓库当前分支；失败时返回空字符串（调用方按拒绝处理）。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except (OSError, ValueError):
        return ""
    return out.decode("utf-8", errors="replace").strip() if proc.returncode == 0 else ""

class TaskBranchApprovalPolicy:
    """仅在任务分支内、且路径落在 allowed_paths 内时自动批准白名单工具。

    默认拒绝：allowed_paths 为空、当前分支不是 task_branch、或 task_branch
    等于 base_branch 时，一律不批准。
    """

    def __init__(
        self,
        *,
        repo_path: str,
        task_branch: str,
        base_branch: str,
        allowed_paths: list[str],
        branch_provider: BranchProvider | None = None,
    ) -> None:
        self._repo_path = repo_path
        self._task_branch = task_branch
        self._base_branch = base_branch
        self._allowed_paths = list(allowed_paths)
        self._branch_provider = branch_provider or (lambda: git_current_branch(repo_path))

    @property
    def allowed_paths(self) -> list[str]:
        return list(self._allowed_paths)

    async def evaluate(self, tool_name: str, params: dict[str, Any]) -> ApprovalDecision:
        if tool_name not in AUTO_APPROVE_TOOLS:
            return ApprovalDecision(approved=False, reason=f"工具 {tool_name!r} 不在自动审批白名单")
        if not self._allowed_paths:
            return ApprovalDecision(approved=False, reason="allowed_paths 为空，拒绝自动审批")
        if self._task_branch == self._base_branch:
            return ApprovalDecision(approved=False, reason="task_branch 等于 base_branch")

        current = await self._branch_provider()
        if current != self._task_branch:
            return ApprovalDecision(
                approved=False,
                reason=f"当前分支 {current!r} 不是任务分支 {self._task_branch!r}",
            )

        path_error = self._check_paths(tool_name, params)
        if path_error:
            return ApprovalDecision(approved=False, reason=path_error)
        return ApprovalDecision(
            approved=True,
            reason=f"任务分支 {self._task_branch!r} 内的白名单工具 {tool_name!r}",
            branch=current,
        )

    def _check_paths(self, tool_name: str, params: dict[str, Any]) -> str | None:
        if tool_name == "file-write":
            target = params.get("path")
            if not isinstance(target, str) or not is_within(Path(target), self._allowed_paths):
                return "file-write 目标路径不在 allowed_paths 内"
        elif tool_name in {"git-commit", "git-pr"}:
            repo = params.get("repo_path")
            if not isinstance(repo, str) or Path(repo).resolve() != Path(self._repo_path).resolve():
                return f"{tool_name} 的 repo_path 必须是任务仓库"
            source = params.get("source_branch")
            if tool_name == "git-pr" and source not in (None, self._task_branch):
                return "git-pr 的 source_branch 必须是任务分支"
        elif tool_name == "safe-shell":
            cwd = params.get("cwd")
            if not isinstance(cwd, str) or not is_within(Path(cwd), self._allowed_paths):
                return "safe-shell 的 cwd 不在 allowed_paths 内"
        return None


class ApprovalAwarePolicyGateway(PolicyGateway):
    """装饰器：在内层 Gateway 之上，按 ApprovalPolicy 把 REQUIRES_APPROVAL 升级为 ALLOW。

    - 内层的 DENY 永远保持 DENY（校验失败、工具不存在等不会被放行）。
    - 只有内层返回 REQUIRES_APPROVAL 时才咨询审批策略。
    - 上下文里的 allowed_paths 为空时直接 DENY（Coder 场景必须有路径边界）。
    - 每次自动批准都会追加一条 ApprovalRecord，供 Worker 转成 APPROVAL_GRANTED Evidence。
    """

    def __init__(self, inner: PolicyGateway, policy: ApprovalPolicy) -> None:
        self._inner = inner
        self._policy = policy
        self._records: list[ApprovalRecord] = []

    @property
    def records(self) -> list[ApprovalRecord]:
        return list(self._records)

    async def check_pre_execution(
        self,
        action_id: str,
        tool_name: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PolicyResult:
        result = await self._inner.check_pre_execution(action_id, tool_name, params, context)
        if result.decision != PolicyDecision.REQUIRES_APPROVAL:
            return result

        if not context.get("allowed_paths"):
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="执行上下文缺少 allowed_paths，拒绝自动审批",
                violations=["allowed_paths is empty"],
                metadata=result.metadata,
            )

        decision = await self._policy.evaluate(tool_name, params)
        if not decision.approved:
            # 保持 REQUIRES_APPROVAL，并附上未批准原因，便于审计
            return PolicyResult(
                decision=PolicyDecision.REQUIRES_APPROVAL,
                reason=result.reason,
                violations=[decision.reason],
                metadata={**result.metadata, "auto_approval_denied": decision.reason},
            )

        record = ApprovalRecord(
            action_id=action_id,
            tool_name=tool_name,
            branch=decision.branch,
            reason=decision.reason,
        )
        self._records.append(record)
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            reason=f"Auto-approved: {decision.reason}",
            metadata={**result.metadata, "auto_approved": True, "approval_reason": decision.reason},
        )

    async def check_post_execution(
        self,
        action_id: str,
        tool_name: str,
        output: Any,
        context: dict[str, Any],
    ) -> PolicyResult:
        return await self._inner.check_post_execution(action_id, tool_name, output, context)
