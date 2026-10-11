"""
Kill Switch Gate（src/security/kill_switch/gate.py）。

ActionExecutor 集成点：工具执行前调用 `is_blocked`，若 blocked 则拒绝并返回 409/403。

设计原则：
- fail-open：如果 manager 状态正常但无 trigger，视为放行
- 解耦：gate 不直接依赖 ActionExecutor 内部（通过 BlockReason 传递信息）
- 审计：每次 blocked 都写一行审计日志

与 ActionExecutor 的集成点（在 src/tools/executor.py 第 159 行 execute_action 开头）：
    if self._kill_switch_gate is not None:
        block = self._kill_switch_gate.is_blocked(context=context)
        if block.blocked:
            return ActionExecutionResult(
                success=False,
                action=action,
                error=f"action blocked by kill switch: {block.reason}",
            )
"""
from __future__ import annotations

import logging

from src.security.kill_switch.manager import KillSwitchManager
from src.security.kill_switch.models import BlockReason

logger = logging.getLogger(__name__)


class KillSwitchGate:
    """Kill Switch Gate（ActionExecutor 调用的薄层）。"""

    def __init__(self, manager: KillSwitchManager) -> None:
        self._manager = manager

    @property
    def manager(self) -> KillSwitchManager:
        """暴露 manager 用于 Admin API 集成。"""
        return self._manager

    def is_blocked(
        self,
        *,
        organization_id: str | None = None,
        project_id: str | None = None,
        repository_id: str | None = None,
    ) -> BlockReason:
        """判定当前 Action 是否被 Kill Switch 阻止。"""
        result = self._manager.is_blocked(
            organization_id=organization_id,
            project_id=project_id,
            repository_id=repository_id,
        )
        if result.blocked:
            logger.warning(
                "kill switch BLOCKED: state=%s scope=%s reason=%s",
                result.current_state.value,
                result.current_scope.value if result.current_scope else "?",
                result.reason,
            )
        return result


__all__ = ["KillSwitchGate"]