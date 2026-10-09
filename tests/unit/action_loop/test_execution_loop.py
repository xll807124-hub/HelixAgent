"""
Action 执行闭环端到端集成测试

测试覆盖：
1. 完整的 Action 执行流程（提议 → 校验 → 执行 → Evidence）
2. 工具注册、Policy Gateway、ActionExecutor 协同工作
3. 真实文件操作
4. 失败场景恢复
"""
import pytest

from src.runtime.entities.action import ActionStatus
from src.runtime.entities.evidence import EvidenceType
from src.security.policy_gateway import SimplifiedPolicyGateway
from src.tools import ExecutionContext, ToolRegistry
from src.tools.executor import ActionExecutor
from src.tools.file import FileReadTool
from tests.helpers import create_test_action


class TestActionExecutionLoop:
    """Action 执行闭环集成测试"""

    @pytest.mark.asyncio
    async def test_full_action_lifecycle(self, tmp_path):
        """测试：完整 Action 生命周期"""
        # 准备测试文件
        test_file = tmp_path / "source.py"
        test_content = """def hello():
    return "Hello, World!"
"""
        test_file.write_text(test_content)

        # 初始化基础设施
        registry = ToolRegistry()
        registry.register(FileReadTool())
        gateway = SimplifiedPolicyGateway(registry)
        executor = ActionExecutor(registry, gateway)

        trace_id = "a" * 32
        context = ExecutionContext(
            trace_id=trace_id,
            action_id="action-001",
            user_id="user-001",
            organization_id="org-001",
            project_id="proj-001",
            task_id="task-001",
            allowed_paths=[str(tmp_path)]
        )

        # Worker 提议 Action
        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(test_file)},
            status=ActionStatus.PROPOSED,
            trace_id=trace_id
        )

        # 执行 Action
        result = await executor.execute_action(action, context)

        # 验证结果
        assert result.success is True
        assert result.action.status_projection == ActionStatus.SUCCEEDED
        assert result.action.metadata.model_extra["output"]["content"] == test_content
        assert result.evidence.type == EvidenceType.TEST_PASSED
        assert result.evidence.trace_id == trace_id

    @pytest.mark.asyncio
    async def test_multiple_actions_sequential(self, tmp_path):
        """测试：顺序执行多个 Action"""
        # 创建多个测试文件
        files = []
        for i in range(3):
            file_path = tmp_path / f"file{i}.txt"
            file_path.write_text(f"Content of file {i}")
            files.append(file_path)

        registry = ToolRegistry()
        registry.register(FileReadTool())
        gateway = SimplifiedPolicyGateway(registry)
        executor = ActionExecutor(registry, gateway)

        context = ExecutionContext(
            trace_id="a" * 32,
            action_id="action-001",
            user_id="user-001",
            organization_id="org-001",
            project_id="proj-001",
            task_id="task-001",
            allowed_paths=[str(tmp_path)]
        )

        # 顺序执行
        results = []
        for i, file_path in enumerate(files):
            action = create_test_action(
                tool_name="file-read",
                parameters={"file_path": str(file_path)},
                status=ActionStatus.PROPOSED
            )
            result = await executor.execute_action(action, context)
            results.append(result)

        # 验证所有成功
        assert all(r.success for r in results)
        for i, result in enumerate(results):
            expected = f"Content of file {i}"
            assert result.action.metadata.model_extra["output"]["content"] == expected

    @pytest.mark.asyncio
    async def test_action_failure_recovery(self, tmp_path):
        """测试：Action 失败后可以重试"""
        registry = ToolRegistry()
        registry.register(FileReadTool())
        gateway = SimplifiedPolicyGateway(registry)
        executor = ActionExecutor(registry, gateway)

        context = ExecutionContext(
            trace_id="a" * 32,
            action_id="action-001",
            user_id="user-001",
            organization_id="org-001",
            project_id="proj-001",
            task_id="task-001",
            allowed_paths=[str(tmp_path)]
        )

        test_file = tmp_path / "recover.txt"

        # 第一次尝试：文件不存在
        action1 = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(test_file)},
            status=ActionStatus.PROPOSED
        )
        result1 = await executor.execute_action(action1, context)
        assert result1.success is False
        assert result1.action.status_projection == ActionStatus.FAILED

        # 创建文件后重试
        test_file.write_text("Now it exists!")
        action2 = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(test_file)},
            status=ActionStatus.PROPOSED
        )
        result2 = await executor.execute_action(action2, context)
        assert result2.success is True
        assert result2.action.metadata.model_extra["output"]["content"] == "Now it exists!"

    @pytest.mark.asyncio
    async def test_policy_gateway_blocks_sensitive_file(self, tmp_path):
        """测试：Policy Gateway 阻止访问敏感文件"""
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET_KEY=very_secret_123")

        registry = ToolRegistry()
        registry.register(FileReadTool())
        gateway = SimplifiedPolicyGateway(registry)
        executor = ActionExecutor(registry, gateway)

        context = ExecutionContext(
            trace_id="a" * 32,
            action_id="action-001",
            user_id="user-001",
            organization_id="org-001",
            project_id="proj-001",
            task_id="task-001",
            allowed_paths=[str(tmp_path)]
        )

        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(env_file)},
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, context)
        assert result.success is False
        assert result.evidence.type == EvidenceType.TEST_FAILED

    @pytest.mark.asyncio
    async def test_trace_id_propagation(self, tmp_path):
        """测试：Trace ID 在整个执行链路中传播"""
        test_file = tmp_path / "trace_test.txt"
        test_file.write_text("test")

        registry = ToolRegistry()
        registry.register(FileReadTool())
        gateway = SimplifiedPolicyGateway(registry)
        executor = ActionExecutor(registry, gateway)

        trace_id = "b" * 32
        context = ExecutionContext(
            trace_id=trace_id,
            action_id="action-001",
            user_id="user-001",
            organization_id="org-001",
            project_id="proj-001",
            task_id="task-001",
            allowed_paths=[str(tmp_path)]
        )

        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(test_file)},
            status=ActionStatus.PROPOSED,
            trace_id=trace_id
        )

        result = await executor.execute_action(action, context)
        assert result.success is True
        assert result.evidence.trace_id == trace_id

    @pytest.mark.asyncio
    async def test_permission_boundary_enforcement(self, tmp_path):
        """测试：权限边界严格执行"""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        forbidden_dir = tmp_path / "forbidden"
        forbidden_dir.mkdir()

        forbidden_file = forbidden_dir / "secret.txt"
        forbidden_file.write_text("You should not see this!")

        registry = ToolRegistry()
        registry.register(FileReadTool())
        gateway = SimplifiedPolicyGateway(registry)
        executor = ActionExecutor(registry, gateway)

        context = ExecutionContext(
            trace_id="a" * 32,
            action_id="action-001",
            user_id="user-001",
            organization_id="org-001",
            project_id="proj-001",
            task_id="task-001",
            allowed_paths=[str(allowed_dir)]
        )

        action = create_test_action(
            tool_name="file-read",
            parameters={"file_path": str(forbidden_file)},
            status=ActionStatus.PROPOSED
        )

        result = await executor.execute_action(action, context)
        assert result.success is False
        assert result.action.status_projection == ActionStatus.FAILED
