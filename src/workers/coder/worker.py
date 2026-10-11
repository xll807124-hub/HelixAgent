"""
Coder Worker：把 ReAct Loop、模型、Action 执行器和完成闸门串起来

对齐：REQ-RT-001（Action/Evidence）、REQ-RT-005（Checkpoint）、REQ-SEC-003/006

设计要点：
- 模型只"提议"工具调用，经 ActionBuilder 转成 Action 后由 ActionExecutor 执行
- 完成闸门（_verify）用 git 与实际工具结果判定，不信任模型的 final_summary
- 每轮观察前保存检查点，支持进程崩溃后 resume
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.runtime.common.types import generate_entity_id
from src.runtime.entities.action import Action, ActionStatus
from src.runtime.entities.evidence import (
    Evidence,
    EvidenceResult,
    EvidenceSource,
    EvidenceType,
    VerificationMethod,
    VerifierType,
)
from src.runtime.trace.context import TraceContext
from src.tools.base import ExecutionContext
from src.tools.executor import ActionExecutor
from src.workers.coder.action_builder import TOOL_PROFILES, ActionBuilder, ActionBuildError
from src.workers.coder.approval import ApprovalAwarePolicyGateway, ApprovalRecord, is_within
from src.workers.coder.checkpoint_store import LoopCheckpointStore
from src.workers.coder.model_client import (
    ModelClient,
    ModelMessage,
    ToolCall,
)
from src.workers.coder.models import CoderResult, CoderTaskSpec, VerificationReport
from src.workers.coder.prompts import (
    SYSTEM_PROMPT,
    TOOL_SPECS,
    build_task_message,
    wrap_tool_output,
)
from src.workers.react_loop.loop import ReActLoop
from src.workers.react_loop.models import (
    Observation,
    ReActLoopCheckpoint,
    ReActLoopConfig,
    ReActLoopResult,
    Reasoning,
)


async def _git(repo: str, *args: str) -> tuple[int, str]:
    """在仓库内执行 git，返回 (退出码, stdout)。启动失败时返回 (1, "")。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", repo, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except (OSError, ValueError):
        return 1, ""
    code = proc.returncode if proc.returncode is not None else 1
    return code, out.decode("utf-8", errors="replace").strip()


def _tests_green(output: Any) -> bool:
    """pytest-run 的解析结果是否表示全部通过（至少跑了一个用例且无失败）。"""
    return (
        isinstance(output, dict)
        and output.get("failed", 1) == 0
        and output.get("passed", 0) > 0
    )


def _render(output: Any, error: str | None) -> str:
    if output is None:
        return error or "(无输出)"
    try:
        return json.dumps(output, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(output)


@dataclass
class _ActResult:
    """actor 返回给 ReAct Loop 的结果（Loop 只读取 action / evidence / metadata）。"""

    action: Action | None = None
    evidence: Evidence | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CoderWorker:
    """Coder Worker：run() 从头执行，resume() 从检查点继续。"""

    def __init__(
        self,
        *,
        spec: CoderTaskSpec,
        model: ModelClient,
        executor: ActionExecutor,
        checkpoint_store: LoopCheckpointStore,
        approval_gateway: ApprovalAwarePolicyGateway | None = None,
        gate_rejection_limit: int = 2,
    ) -> None:
        self._spec = spec
        self._model = model
        self._executor = executor
        self._store = checkpoint_store
        self._approval_gateway = approval_gateway
        self._gate_limit = gate_rejection_limit
        self._builder = ActionBuilder(spec)
        self.approval_evidences: list[Evidence] = []
        self._reset_state()

    def _reset_state(self) -> None:
        self._loop: ReActLoop | None = None
        self._messages: list[ModelMessage] = [
            ModelMessage(role="system", content=SYSTEM_PROMPT),
            build_task_message(self._spec),
        ]
        self._start_sha = ""
        self._head_sha = ""
        self._final_head = ""
        self._pending: ToolCall | None = None
        self._last_result: str | None = None
        self._tests_ok_after_write = False
        self._gate_rejections = 0
        self._approvals_seen = 0
        self._summary = ""
        self._changed_files: list[str] = []

    async def run(self) -> CoderResult:
        return await self._execute(resume=False)

    async def resume(self) -> CoderResult:
        return await self._execute(resume=True)

    async def _execute(self, *, resume: bool) -> CoderResult:
        t0 = time.monotonic()
        spec = self._spec
        self._reset_state()
        checkpoint: ReActLoopCheckpoint | None = None
        if resume:
            checkpoint = self._store.load(spec.task_id)
            if checkpoint is None:
                return self._failure("", "没有可恢复的检查点", t0)
            self._restore(checkpoint)
        code, sha = await _git(spec.repo_path, "rev-parse", "HEAD")
        if code != 0 or not sha:
            return self._failure("", "无法读取仓库 HEAD", t0)
        self._head_sha = sha
        if not self._start_sha:
            self._start_sha = sha

        config = ReActLoopConfig(
            max_iterations=spec.max_iterations,
            timeout_seconds=spec.timeout_seconds,
            max_tokens=spec.max_tokens,
            max_cost_cents=spec.max_cost_cents,
        )
        trace = TraceContext(trace_id=spec.trace_id, span_id=uuid.uuid4().hex[:16])
        if checkpoint is not None:
            loop = ReActLoop.from_checkpoint(
                checkpoint, self._observe, self._reason, self._act, trace, config
            )
        else:
            loop = ReActLoop(
                loop_id=generate_entity_id(),
                worker_id=spec.worker_id,
                task_id=spec.task_id,
                config=config,
                observer=self._observe,
                reasoner=self._reason,
                actor=self._act,
                trace_context=trace,
            )
        self._loop = loop
        result = await loop.run()
        report = await self._verify()
        if report.passed:
            self._store.delete(spec.task_id)
        else:
            self._store.save(loop.to_checkpoint())
        return self._to_result(result, report)

    def _restore(self, checkpoint: ReActLoopCheckpoint) -> None:
        """从检查点恢复 Worker 侧状态：起始 SHA 与"写后测试是否通过"。"""
        actions = [a for a in checkpoint.actions if isinstance(a, Action)]
        if actions and actions[0].source_revision:
            self._start_sha = actions[0].source_revision
        for action in actions:
            if action.status_projection != ActionStatus.SUCCEEDED:
                continue
            if action.tool_name == "file-write":
                self._tests_ok_after_write = False
            elif action.tool_name == "pytest-run":
                extra = action.metadata.model_extra or {}
                self._tests_ok_after_write = _tests_green(extra.get("output"))
        self._messages.append(
            ModelMessage(
                role="user",
                content=f"任务从检查点恢复，已完成 {checkpoint.current_iteration} 轮，请继续。",
            )
        )

    def _failure(self, loop_id: str, message: str, t0: float) -> CoderResult:
        return CoderResult(
            task_id=self._spec.task_id,
            worker_id=self._spec.worker_id,
            loop_id=loop_id,
            success=False,
            termination_reason="Failed",
            error_message=message,
            total_execution_time_ms=int((time.monotonic() - t0) * 1000),
        )

    def _to_result(self, result: ReActLoopResult, report: VerificationReport) -> CoderResult:
        failures = list(report.failures)
        success = result.succeeded and report.passed
        error = result.error_message
        if error is None and not success and failures:
            error = "; ".join(failures)
        commit_sha = self._final_head if report.committed else None
        return CoderResult(
            task_id=result.task_id,
            worker_id=result.worker_id,
            loop_id=result.loop_id,
            success=success,
            termination_reason=result.termination_reason,
            error_message=error,
            iteration_count=result.iteration_count,
            summary=self._summary,
            commit_sha=commit_sha,
            changed_files=list(self._changed_files),
            verification=report,
            total_tokens_consumed=result.total_tokens_consumed,
            total_cost_cents=result.total_cost_cents,
            total_execution_time_ms=result.total_execution_time_ms,
        )

    async def _observe(self, context: dict[str, Any]) -> Observation:
        # 每轮观察前保存检查点（REQ-RT-005），崩溃后可 resume
        if self._loop is not None:
            self._store.save(self._loop.to_checkpoint())
        return Observation(
            iteration=int(context.get("iteration", 0)),
            context_summary=(
                f"HEAD={self._head_sha[:12]} 分支={self._spec.task_branch} "
                f"写后测试通过={self._tests_ok_after_write}"
            ),
            available_tools=[s.name for s in TOOL_SPECS],
            last_observation_result=self._last_result,
            remaining_budget=dict(context.get("budget", {})),
        )

    async def _reason(self, observation: Observation) -> Reasoning:
        if observation.last_observation_result:
            self._messages.append(
                ModelMessage(role="user", content=observation.last_observation_result)
            )
            self._last_result = None
        started = time.monotonic()
        response = await self._model.complete(self._messages, TOOL_SPECS)
        elapsed = int((time.monotonic() - started) * 1000)
        meta = {"tokens_used": response.usage.tokens, "cost_cents": response.usage.cost_cents}

        call = response.tool_call
        if response.is_final or call is None:
            return await self._handle_final(
                observation.iteration, response.thought, response.final_summary or "", elapsed, meta
            )
        self._messages.append(
            ModelMessage(
                role="assistant",
                content=f"{response.thought}\n调用 {call.name} "
                f"{json.dumps(call.arguments, ensure_ascii=False, default=str)}",
            )
        )
        profile = TOOL_PROFILES.get(call.name)
        return Reasoning(
            iteration=observation.iteration,
            thought=response.thought,
            next_action_type=profile[0] if profile else None,
            next_tool_name=call.name,
            next_tool_args=dict(call.arguments),
            reasoning_time_ms=elapsed,
            metadata=meta,
        )

    async def _handle_final(
        self, iteration: int, thought: str, summary: str, elapsed: int, meta: dict[str, Any]
    ) -> Reasoning:
        """模型声明完成：以完成闸门为准，不信任自述。"""
        self._summary = summary
        report = await self._verify()
        if report.passed:
            return Reasoning(
                iteration=iteration, thought=thought, should_continue=False,
                termination_reason="Task completed", reasoning_time_ms=elapsed, metadata=meta,
            )
        self._gate_rejections += 1
        reasons = "; ".join(report.failures)
        if self._gate_rejections > self._gate_limit:
            return Reasoning(
                iteration=iteration, thought=thought, should_continue=False,
                termination_reason=f"完成闸门多次未通过: {reasons}",
                reasoning_time_ms=elapsed, metadata=meta,
            )
        self._messages.append(
            ModelMessage(role="user", content=f"完成闸门未通过，请继续修复: {reasons}")
        )
        return Reasoning(
            iteration=iteration, thought=thought, should_continue=True,
            reasoning_time_ms=elapsed, metadata=meta,
        )

    def _exec_context(self, action_id: str) -> ExecutionContext:
        spec = self._spec
        return ExecutionContext(
            trace_id=spec.trace_id,
            action_id=action_id,
            user_id=spec.user_id,
            organization_id=spec.organization_id,
            project_id=spec.project_id,
            task_id=spec.task_id,
            allowed_paths=list(spec.allowed_paths),
            read_only=False,
            timeout_seconds=min(spec.timeout_seconds, 300),
        )

    async def _act(self, reasoning: Reasoning) -> _ActResult:
        if not reasoning.next_tool_name:
            # 闸门拒绝后的空轮：不执行任何工具
            return _ActResult()
        call = ToolCall(name=reasoning.next_tool_name, arguments=reasoning.next_tool_args)
        try:
            action = self._builder.build(
                call, step_id=f"step-{reasoning.iteration}", head_sha=self._head_sha
            )
        except ActionBuildError as exc:
            self._last_result = wrap_tool_output(f"动作被拒绝: {exc}")
            return _ActResult()

        exec_result = await self._executor.execute_action(
            action, self._exec_context(action.action_id)
        )
        self._record_approvals()
        final_action = exec_result.action
        output = (final_action.metadata.model_extra or {}).get("output")

        if exec_result.success:
            if call.name == "file-write":
                self._tests_ok_after_write = False
            elif call.name == "pytest-run":
                self._tests_ok_after_write = _tests_green(output)
            elif call.name == "git-commit":
                code, sha = await _git(self._spec.repo_path, "rev-parse", "HEAD")
                if code == 0 and sha:
                    self._head_sha = sha
            body = _render(output, None)
        else:
            if call.name == "pytest-run":
                self._tests_ok_after_write = False
            body = f"失败: {exec_result.error or 'unknown'}"
        self._last_result = wrap_tool_output(f"[{call.name}] {body}")
        return _ActResult(action=final_action, evidence=exec_result.evidence)

    def _record_approvals(self) -> None:
        """把审批网关新增的 ApprovalRecord 转成 APPROVAL_GRANTED Evidence。"""
        if self._approval_gateway is None:
            return
        records = self._approval_gateway.records
        for record in records[self._approvals_seen:]:
            self.approval_evidences.append(self._approval_evidence(record))
        self._approvals_seen = len(records)

    def _approval_evidence(self, record: ApprovalRecord) -> Evidence:
        content = record.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        now = datetime.now(UTC)
        return Evidence(
            evidence_id=str(uuid.uuid4()),
            task_id=self._spec.task_id,
            workflow_id=self._spec.workflow_id,
            producer_worker_id=self._spec.worker_id,
            source_action_id=record.action_id,
            type=EvidenceType.APPROVAL_GRANTED,
            source=EvidenceSource.SYSTEM,
            source_revision=self._head_sha or "unknown",
            verification_method=VerificationMethod.POLICY_DECISION,
            verifier_type=VerifierType.SYSTEM,
            verifier_id="task-branch-approval-policy",
            result=EvidenceResult.PASSED,
            content_schema="coder.approval.v1",
            content_schema_version="1.0.0",
            content_hash=digest,
            content_inline=content,
            trace_id=self._spec.trace_id,
            created_at=now,
            verified_at=now,
        )

    async def _verify(self) -> VerificationReport:
        """完成闸门：用 git 与工具实际结果核对，不信任模型自述。"""
        spec = self._spec
        failures: list[str] = []

        code, head = await _git(spec.repo_path, "rev-parse", "HEAD")
        if code != 0 or not head:
            return VerificationReport(passed=False, failures=["无法读取仓库 HEAD"])
        self._final_head = head

        _, branch = await _git(spec.repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        if branch != spec.task_branch:
            failures.append(f"当前分支 {branch!r} 不是任务分支 {spec.task_branch!r}")

        committed = bool(self._start_sha) and head != self._start_sha
        if not committed:
            failures.append("尚未提交：HEAD 与起始提交相同")

        _, dirty = await _git(spec.repo_path, "status", "--porcelain", "--untracked-files=no")
        if dirty:
            failures.append("存在未提交的修改")

        changed: list[str] = []
        if self._start_sha:
            diff_code, names = await _git(
                spec.repo_path, "diff", "--name-only", "--relative", self._start_sha, "HEAD"
            )
            if diff_code == 0:
                changed = [line for line in names.splitlines() if line.strip()]
        self._changed_files = changed

        diff_non_empty = bool(changed)
        if not diff_non_empty:
            failures.append("diff 为空，没有任何代码修改")

        within = diff_non_empty and all(
            is_within(Path(spec.repo_path) / name, spec.allowed_paths) for name in changed
        )
        if diff_non_empty and not within:
            failures.append("diff 包含 allowed_paths 之外的文件")

        if not self._tests_ok_after_write:
            failures.append("最后一次写入之后没有通过的测试运行")

        return VerificationReport(
            passed=not failures,
            tests_passed_after_last_write=self._tests_ok_after_write,
            diff_non_empty=diff_non_empty,
            diff_within_allowed_paths=within,
            committed=committed,
            failures=failures,
        )
