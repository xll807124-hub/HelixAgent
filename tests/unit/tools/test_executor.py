"""
ActionExecutor 单元测试

测试覆盖：
1. 完整执行流程
2. 状态机约束
3. Policy Gateway 集成
4. 失败处理
5. Evidence 记录
"""
import pytest

from src.runtime.entities.action import ActionStatus
from src.runtime.entities.evidence import EvidenceType
from src.security.policy_gateway import SimplifiedPolicyGateway
from src.tools import ExecutionContext, ToolRegistry
from src.tools.executor import ActionExecutor
from src.tools.file import FileReadTool
from tests.helpers import create_test_action


@pytest.fixture
def tool_registry():
    """创建测试用工具注册表"""
    registry = ToolRegistry()
    registry.register(FileReadTool())
    return registry


@pytest.fixture
def policy_gateway(tool_registry):
    """创建策略网关"""
    return SimplifiedPolicyGateway(tool_registry)


@pytest.fixture
def executor(tool_registry, policy_gateway):
    """创建执行器"""
    return ActionExecutor(tool_registry, policy_gateway)


@pytest.fixture
def execution_context(tmp_path):
    """创建执行上下文"""
    return ExecutionContext(
        trace_id="a" * 32,  # 32位十六进制
        action_id="action-001",
        user_id="user-001",
        organization_id="org-001",
        project_id="proj-001",
        task_id="task-001",
        allowed_paths=[str(tmp_path)],
        timeout_seconds=30
    )


class TestActionExecutor:
    """ActionExecutor 测试套件"""

    @pytest.mark.asyncio
    async def test_execute_action_success(self, executor, execution_context, tmp_path):
        """测试：成功执行 Action"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(test_file)},
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, execution_context)

        assert result.success is True
        assert result.action.status_projection == ActionStatus.SUCCEEDED
        assert result.action.metadata.model_extra["output"]["content"] == "Hello, World!"
        assert result.evidence.type == EvidenceType.TEST_PASSED

    @pytest.mark.asyncio
    async def test_execute_action_invalid_state(self, executor, execution_context):
        """测试：Action 状态不是 PROPOSED"""
        action = create_test_action(
            tool_name="file-read",
            parameters={},
            status=ActionStatus.EXECUTING
        )

        result = await executor.execute_action(action, execution_context)

        assert result.success is False
        assert "PROPOSED" in result.error

    @pytest.mark.asyncio
    async def test_execute_action_tool_not_found(self, executor, execution_context):
        """测试：工具不存在"""
        action = create_test_action(
            tool_name="nonexistent-tool",
            parameters={},
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, execution_context)

        assert result.success is False
        assert result.action.status_projection == ActionStatus.FAILED
        assert result.evidence.type == EvidenceType.TEST_FAILED

    @pytest.mark.asyncio
    async def test_execute_action_invalid_params(self, executor, execution_context):
        """测试：参数无效"""
        action = create_test_action(
            tool_name="file-read",
            parameters={},  # 缺少 file_path
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, execution_context)

        assert result.success is False
        assert result.action.status_projection == ActionStatus.FAILED
        assert result.evidence.type == EvidenceType.TEST_FAILED

    @pytest.mark.asyncio
    async def test_execute_action_file_not_found(self, executor, execution_context, tmp_path):
        """测试：文件不存在"""
        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(tmp_path / "nonexistent.txt")},
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, execution_context)

        assert result.success is False
        assert result.action.status_projection == ActionStatus.FAILED
        assert result.evidence.type == EvidenceType.TEST_FAILED

    @pytest.mark.asyncio
    async def test_execute_action_permission_denied(self, executor, tmp_path):
        """测试：权限拒绝"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        context = ExecutionContext(
            trace_id="a" * 32,
            action_id="action-001",
            user_id="user-001",
            organization_id="org-001",
            project_id="proj-001",
            task_id="task-001",
            allowed_paths=["/different/path"]
        )

        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(test_file)},
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, context)

        assert result.success is False
        assert result.action.status_projection == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_action_sensitive_file(self, executor, execution_context, tmp_path):
        """测试：尝试访问敏感文件"""
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET_KEY=abc123")

        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(env_file)},
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, execution_context)

        assert result.success is False
        assert result.action.status_projection == ActionStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_action_updates_timestamps(self, executor, execution_context, tmp_path):
        """测试：正确更新时间戳"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(test_file)},
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, execution_context)

        assert result.success is True
        assert result.action.started_at is not None
        assert result.action.completed_at is not None
        assert result.action.completed_at >= result.action.started_at

    @pytest.mark.asyncio
    async def test_execute_action_records_execution_time(self, executor, execution_context, tmp_path):
        """测试：记录执行时间"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(test_file)},
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, execution_context)

        assert result.success is True
        assert "execution_time_ms" in result.action.metadata.model_extra

    @pytest.mark.asyncio
    async def test_execute_action_evidence_includes_trace_id(self, executor, execution_context, tmp_path):
        """测试：Evidence 包含 Trace ID"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(test_file)},
            status=ActionStatus.PROPOSED,
            trace_id=execution_context.trace_id
        )

        result = await executor.execute_action(action, execution_context)

        assert result.success is True
        assert result.evidence.trace_id == execution_context.trace_id

    @pytest.mark.asyncio
    async def test_execute_action_multiple_lines_file(self, executor, execution_context, tmp_path):
        """测试：读取多行文件"""
        test_file = tmp_path / "multiline.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3\n")

        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(test_file)},
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, execution_context)

        assert result.success is True
        assert result.action.metadata.model_extra["output"]["lines"] == 4
        assert "Line 1" in result.action.metadata.model_extra["output"]["content"]
