"""
Pytest 测试运行工具单元测试
"""
import pytest

from src.tools.base import ExecutionContext, RiskLevel
from src.tools.test.pytest_runner import PytestRunnerTool


@pytest.fixture
def tool():
    return PytestRunnerTool()


@pytest.fixture
def execution_context():
    return ExecutionContext(
        trace_id="test-123",
        action_id="action-123",
        user_id="user-123",
        organization_id="org-123",
        project_id="project-123",
        task_id="task-123",
    )


class TestPytestRunnerToolProperties:
    """工具属性测试"""

    def test_tool_name(self, tool):
        assert tool.name == "pytest-run"

    def test_tool_description(self, tool):
        assert "pytest" in tool.description.lower()

    def test_tool_risk_level(self, tool):
        assert tool.risk_level == RiskLevel.MEDIUM

    def test_input_schema(self, tool):
        schema = tool.input_schema
        assert "test_path" in schema["properties"]
        assert "test_path" in schema["required"]

    def test_output_schema(self, tool):
        schema = tool.output_schema
        assert "passed" in schema["properties"]
        assert "failed" in schema["properties"]
        # 检查实际存在的字段
        assert any(k in schema["properties"] for k in ["total", "duration"])


class TestPytestRunnerToolValidation:
    """输入验证测试"""

    @pytest.mark.asyncio
    async def test_validate_missing_test_path(self, tool, execution_context):
        result = await tool.validate_input({}, execution_context)
        assert not result.valid

    @pytest.mark.asyncio
    async def test_validate_success(self, tool, execution_context):
        result = await tool.validate_input({
            "test_path": "tests/",
        }, execution_context)
        assert result.valid

    @pytest.mark.asyncio
    async def test_validate_with_options(self, tool, execution_context):
        result = await tool.validate_input({
            "test_path": "tests/",
            "verbose": True,
            "coverage": True,
            "timeout": 60,
        }, execution_context)
        assert result.valid


class TestPytestRunnerToolConfiguration:
    """配置测试"""

    def test_timeout_configuration(self, tool):
        timeout = tool.timeout_seconds
        assert isinstance(timeout, int)
        assert timeout > 0

