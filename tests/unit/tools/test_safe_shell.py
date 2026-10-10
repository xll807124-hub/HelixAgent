"""
安全 Shell 工具单元测试
"""
import pytest

from src.tools.base import ExecutionContext, RiskLevel
from src.tools.shell.safe_shell import SafeShellTool


@pytest.fixture
def tool():
    return SafeShellTool()


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


class TestSafeShellToolProperties:
    """工具属性测试"""

    def test_tool_name(self, tool):
        assert tool.name == "safe-shell"

    def test_tool_description(self, tool):
        assert "shell" in tool.description.lower()

    def test_tool_risk_level(self, tool):
        assert tool.risk_level == RiskLevel.HIGH

    def test_input_schema(self, tool):
        schema = tool.input_schema
        assert "command" in schema["properties"]
        assert "cwd" in schema["properties"]
        assert "command" in schema["required"]
        assert "cwd" in schema["required"]

    def test_output_schema(self, tool):
        schema = tool.output_schema
        assert "stdout" in schema["properties"]
        assert "stderr" in schema["properties"]
        assert "return_code" in schema["properties"]


class TestSafeShellToolValidation:
    """输入验证测试"""

    @pytest.mark.asyncio
    async def test_validate_missing_command(self, tool, execution_context):
        result = await tool.validate_input({"cwd": "."}, execution_context)
        assert not result.valid

    @pytest.mark.asyncio
    async def test_validate_missing_cwd(self, tool, execution_context):
        result = await tool.validate_input({"command": "echo test"}, execution_context)
        assert not result.valid

    @pytest.mark.asyncio
    async def test_validate_safe_command(self, tool, execution_context):
        result = await tool.validate_input({
            "command": "echo hello",
            "cwd": ".",
        }, execution_context)
        assert result.valid

    @pytest.mark.asyncio
    async def test_validate_with_timeout(self, tool, execution_context):
        result = await tool.validate_input({
            "command": "echo test",
            "cwd": ".",
            "timeout": 5,
        }, execution_context)
        assert result.valid


class TestSafeShellToolCommandWhitelisting:
    """命令白名单测试"""

    def test_allowed_commands(self, tool):
        # 检查允许的命令列表
        allowed = tool.ALLOWED_COMMANDS
        assert isinstance(allowed, set)
        assert "echo" in allowed
        assert "python" in allowed
        assert "git" in allowed

    def test_dangerous_chars(self, tool):
        # 检查危险字符集
        dangerous = tool.DANGEROUS_CHARS
        assert isinstance(dangerous, set)
        assert "|" in dangerous
        assert ";" in dangerous
        assert "&" in dangerous


class TestSafeShellToolSafety:
    """安全性测试"""

    def test_tool_has_validation(self, tool):
        # 确保 validate_input 存在
        assert hasattr(tool, "validate_input")

    def test_tool_has_execute(self, tool):
        # 确保 execute 存在
        assert hasattr(tool, "execute")


class TestSafeShellToolTimeout:
    """超时保护测试"""

    def test_timeout_configuration(self, tool):
        timeout = tool.timeout_seconds
        assert isinstance(timeout, int)
        assert timeout > 0
        assert timeout <= 300  # 合理的超时时间

