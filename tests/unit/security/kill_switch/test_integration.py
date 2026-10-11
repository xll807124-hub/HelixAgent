"""Kill Switch 与 ActionExecutor 集成测试。"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.runtime.common.types import (
    ResourceRef,
    ResourceType,
    SafeMetadata,
    generate_entity_id,
)
from src.runtime.entities.action import Action, ActionStatus, ActionType
from src.runtime.entities.task import RiskLevel
from src.security.kill_switch import (
    KillSwitchGate,
    KillSwitchManager,
    KillSwitchScope,
)
from src.security.policy_gateway import SimplifiedPolicyGateway
from src.tools.base import ExecutionContext
from src.tools.executor import ActionExecutor
from src.tools.registry import ToolRegistry


def _make_executor(
    registry: ToolRegistry, manager: KillSwitchManager
) -> ActionExecutor:
    return ActionExecutor(
        tool_registry=registry,
        policy_gateway=SimplifiedPolicyGateway(tool_registry=registry),
        kill_switch_gate=KillSwitchGate(manager),
    )


def _make_action(name: str = "file-read") -> Action:
    now = datetime.now(UTC)
    return Action(
        schema_version="runtime.action.v1",
        action_id=generate_entity_id(),
        task_id=generate_entity_id(),
        workflow_id=generate_entity_id(),
        worker_id=generate_entity_id(),
        step_id="integration-test",
        type=ActionType.ANALYZE,
        tool_name=name,
        tool_schema_version="v1",
        arguments={},
        target_resources=[
            ResourceRef(
                resource_type=ResourceType.EXTERNAL_SERVICE,
                resource_id=name,
                scope="test",
            )
        ],
        source_revision="unknown",
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        policy_decision_id=None,
        idempotency_key=None,
        expected_observation_schema=None,
        status_projection=ActionStatus.PROPOSED,
        trace_id="0123456789abcdef0123456789abcdef",
        created_at=now,
        updated_at=now,
        proposed_at=now,
        authorized_at=None,
        started_at=None,
        completed_at=None,
        metadata=SafeMetadata(),
    )


def _make_context() -> ExecutionContext:
    return ExecutionContext(
        trace_id="0123456789abcdef0123456789abcdef",
        action_id=generate_entity_id(),
        user_id="test-user",
        organization_id="00000000-0000-0000-0000-000000000001",
        project_id="00000000-0000-0000-0000-000000000002",
        task_id="00000000-0000-0000-0000-000000000003",
        allowed_paths=[],
        read_only=False,
        timeout_seconds=5,
    )


class TestKillSwitchIntegration:
    """ActionExecutor + KillSwitchGate 集成。"""

    def _make_registry(self) -> ToolRegistry:
        return ToolRegistry()

    @pytest.mark.asyncio
    async def test_idle_passes_through(self) -> None:
        """IDLE 状态：工具可执行。"""
        manager = KillSwitchManager()
        executor = _make_executor(self._make_registry(), manager)
        result = await executor.execute_action(_make_action(), _make_context())
        # file-read 工具执行会失败（路径为空），但不是 kill switch 拒绝
        if not result.success:
            assert "kill switch" not in (result.error or "")

    @pytest.mark.asyncio
    async def test_triggered_blocks_action(self) -> None:
        """TRIGGERED 状态：所有工具调用被拒绝。"""
        manager = KillSwitchManager()
        await manager.trigger(
            scope=KillSwitchScope.GLOBAL,
            reason="test emergency",
            actor_id="test",
        )
        executor = _make_executor(self._make_registry(), manager)
        result = await executor.execute_action(_make_action(), _make_context())
        assert result.success is False
        assert "kill switch" in (result.error or "").lower()
        assert result.action.status_projection == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_recovering_still_blocks(self) -> None:
        """RECOVERING 状态：仍被阻止。"""
        manager = KillSwitchManager()
        await manager.trigger(
            scope=KillSwitchScope.GLOBAL, reason="x", actor_id="u"
        )
        await manager.request_recovery(actor_id="u")
        executor = _make_executor(self._make_registry(), manager)
        result = await executor.execute_action(_make_action(), _make_context())
        assert result.success is False
        assert "kill switch" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_recovered_unblocks(self) -> None:
        """恢复后：工具可执行。"""
        manager = KillSwitchManager()
        await manager.trigger(
            scope=KillSwitchScope.GLOBAL, reason="x", actor_id="u"
        )
        req = await manager.request_recovery(actor_id="u")
        await manager.confirm_recovery(
            confirm_token=req.confirm_token, actor_id="u"
        )
        executor = _make_executor(self._make_registry(), manager)
        result = await executor.execute_action(_make_action(), _make_context())
        # 不应是 kill switch 失败
        if not result.success:
            assert "kill switch" not in (result.error or "").lower()
