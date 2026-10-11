"""
SimplifiedPolicyGateway 校验分派回归测试

背景：部分工具的 validate_input 签名为 (params, context) 或 async，
Gateway 原先只传 params，会抛 TypeError。这里覆盖各类签名与异常路径。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.security.policy_gateway import PolicyDecision, SimplifiedPolicyGateway
from src.tools import BaseTool, ExecutionContext, RiskLevel, ToolRegistry, ToolResult
from src.tools.base import ValidationResult
from src.tools.file.read import FileReadTool
from src.tools.file.write import FileWriteTool
from src.tools.test.pytest_runner import PytestRunnerTool


class _ExplodingValidatorTool(BaseTool):
    """validate_input 直接抛异常的工具，用于验证默认拒绝。"""

    @property
    def name(self) -> str:
        return "exploding-tool"

    @property
    def description(self) -> str:
        return "Validator raises"

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"x": {"type": "string"}}}

    @property
    def output_schema(self) -> dict:
        return {"type": "object"}

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    def validate_input(self, params: dict) -> ValidationResult:  # type: ignore[override]
        raise RuntimeError("boom")

    async def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        return ToolResult(success=True, output={})


@pytest.fixture
def gateway() -> SimplifiedPolicyGateway:
    registry = ToolRegistry()
    for tool in (FileReadTool(), FileWriteTool(), PytestRunnerTool(), _ExplodingValidatorTool()):
        registry.register(tool)
    return SimplifiedPolicyGateway(registry)


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
async def test_sync_validator_with_context_inside_allowed_paths(gateway, tmp_path: Path):
    """file-write（同步 + context）：允许路径内 → 通过校验，进入高风险审批。"""
    target = tmp_path / "a.py"
    result = await gateway.check_pre_execution(
        "a1", "file-write", {"path": str(target), "content": "x = 1\n"}, _ctx([str(tmp_path)])
    )
    assert result.decision == PolicyDecision.REQUIRES_APPROVAL


@pytest.mark.asyncio
async def test_sync_validator_with_context_outside_allowed_paths(gateway, tmp_path: Path):
    """file-write：越出 allowed_paths → DENY，且违规信息被保留。"""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.py"
    result = await gateway.check_pre_execution(
        "a2", "file-write", {"path": str(outside), "content": "x"}, _ctx([str(allowed)])
    )
    assert result.decision == PolicyDecision.DENY
    assert any("allowed_paths" in v for v in result.violations)


@pytest.mark.asyncio
async def test_async_validator_with_context(gateway, tmp_path: Path):
    """pytest-run（async + context）：路径存在 → ALLOW（MEDIUM 风险）。"""
    result = await gateway.check_pre_execution(
        "a3", "pytest-run", {"test_path": str(tmp_path)}, _ctx([str(tmp_path)])
    )
    assert result.decision == PolicyDecision.ALLOW
    assert result.metadata["risk_level"] == "MEDIUM"


@pytest.mark.asyncio
async def test_async_validator_rejects_missing_path(gateway, tmp_path: Path):
    """pytest-run：路径不存在 → DENY。"""
    result = await gateway.check_pre_execution(
        "a4", "pytest-run", {"test_path": str(tmp_path / "nope")}, _ctx([str(tmp_path)])
    )
    assert result.decision == PolicyDecision.DENY


@pytest.mark.asyncio
async def test_params_only_validator_still_works(gateway, tmp_path: Path):
    """file-read（仅 params）：旧签名不受影响。"""
    result = await gateway.check_pre_execution(
        "a5", "file-read", {"file_path": str(tmp_path / "x.txt")}, {}
    )
    assert result.decision == PolicyDecision.ALLOW


@pytest.mark.asyncio
async def test_validator_exception_is_denied(gateway):
    """校验器自身抛异常 → DENY（默认拒绝），不向上抛出。"""
    result = await gateway.check_pre_execution("a6", "exploding-tool", {}, {})
    assert result.decision == PolicyDecision.DENY
    assert any("boom" in v for v in result.violations)
