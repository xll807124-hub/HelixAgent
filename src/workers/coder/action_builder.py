"""
ToolCall -> Action 转换

对齐：REQ-RT-001 §5.4（Action 实体）、REQ-SEC-006（模型输出不可信，需结构化校验后才转 Action）

模型只"提议"工具调用；这里负责：
- 拒绝未知工具（默认拒绝，不允许模型调用白名单之外的工具）
- 生成 UUID action_id、绑定具体 head SHA（不变量6）
- 推导 target_resources（至少一个）
- 生成稳定幂等键（同一任务 + 步骤 + 工具 + 参数 => 同一个键）
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.runtime.common.types import ResourceRef, ResourceType
from src.runtime.entities.action import Action, ActionStatus, ActionType
from src.runtime.entities.task import RiskLevel
from src.workers.coder.model_client import ToolCall
from src.workers.coder.models import CoderTaskSpec

TOOL_SCHEMA_VERSION = "1.0.0"

# 工具名 -> (ActionType, RiskLevel)。风险级别与 src/tools 中各工具声明保持一致。
TOOL_PROFILES: dict[str, tuple[ActionType, RiskLevel]] = {
    "file-read": (ActionType.READ, RiskLevel.LOW),
    "file-search": (ActionType.READ, RiskLevel.LOW),
    "file-write": (ActionType.WRITE, RiskLevel.HIGH),
    "git-status": (ActionType.READ, RiskLevel.LOW),
    "git-diff": (ActionType.READ, RiskLevel.LOW),
    "git-branch": (ActionType.WRITE, RiskLevel.MEDIUM),
    "git-commit": (ActionType.WRITE, RiskLevel.HIGH),
    "git-pr": (ActionType.REPORT, RiskLevel.HIGH),
    "pytest-run": (ActionType.EXECUTE, RiskLevel.MEDIUM),
    "safe-shell": (ActionType.EXECUTE, RiskLevel.HIGH),
}

# 参数里可能出现的路径类字段 -> 资源类型
_FILE_KEYS = ("path", "file_path")
_DIR_KEYS = ("search_path", "test_path", "cwd")


class ActionBuildError(Exception):
    """模型提议无法转成合法 Action（未知工具、实体校验失败等）。"""


def compute_idempotency_key(
    task_id: str, step_id: str, tool_name: str, arguments: dict[str, Any]
) -> str:
    """稳定幂等键：对规范化 JSON 取 SHA-256。"""
    payload = json.dumps(
        {"task": task_id, "step": step_id, "tool": tool_name, "args": arguments},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return "idem-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:48]


class ActionBuilder:
    """把 ToolCall 构造成 Action。无状态，可复用。"""

    def __init__(self, spec: CoderTaskSpec) -> None:
        self._spec = spec

    def build(self, call: ToolCall, *, step_id: str, head_sha: str) -> Action:
        profile = TOOL_PROFILES.get(call.name)
        if profile is None:
            raise ActionBuildError(f"未知或未授权的工具: {call.name!r}")
        action_type, risk = profile
        now = datetime.now(UTC)

        try:
            return Action(
                action_id=str(uuid.uuid4()),
                task_id=self._spec.task_id,
                workflow_id=self._spec.workflow_id,
                worker_id=self._spec.worker_id,
                step_id=step_id,
                type=action_type,
                tool_name=call.name,
                tool_schema_version=TOOL_SCHEMA_VERSION,
                arguments=dict(call.arguments),
                target_resources=self._targets(call.arguments),
                source_revision=head_sha,
                risk_level=risk,
                requires_approval=risk == RiskLevel.HIGH,
                idempotency_key=compute_idempotency_key(
                    self._spec.task_id, step_id, call.name, call.arguments
                ),
                status_projection=ActionStatus.PROPOSED,
                trace_id=self._spec.trace_id,
                created_at=now,
                updated_at=now,
                proposed_at=now,
            )
        except ValueError as exc:
            raise ActionBuildError(f"Action 校验失败: {exc}") from exc

    def _targets(self, arguments: dict[str, Any]) -> list[ResourceRef]:
        scope = self._spec.repo_path
        refs: list[ResourceRef] = []
        for key in _FILE_KEYS:
            value = arguments.get(key)
            if isinstance(value, str) and value:
                refs.append(
                    ResourceRef(
                        resource_type=ResourceType.FILE,
                        resource_id=value[:500],
                        scope=scope,
                        locator=value,
                    )
                )
        for key in _DIR_KEYS:
            value = arguments.get(key)
            if isinstance(value, str) and value:
                refs.append(
                    ResourceRef(
                        resource_type=ResourceType.DIRECTORY,
                        resource_id=value[:500],
                        scope=scope,
                        locator=value,
                    )
                )
        if not refs:
            # git-* 等没有显式路径的工具：目标为任务仓库
            refs.append(
                ResourceRef(
                    resource_type=ResourceType.REPOSITORY,
                    resource_id=scope,
                    scope=scope,
                    locator=scope,
                )
            )
        return refs
