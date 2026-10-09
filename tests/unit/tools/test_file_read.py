"""
FileReadTool 单元测试

测试覆盖：
1. 正常文件读取
2. 路径穿越攻击防护
3. 文件大小限制
4. 敏感文件过滤
5. 权限检查
6. 二进制文件检测
7. 边界场景
"""
import tempfile
from pathlib import Path

import pytest

from src.tools import ExecutionContext, RiskLevel, ToolExecutionError
from src.tools.file import FileReadTool


class TestFileReadTool:
    """FileReadTool 测试套件"""

    def test_tool_metadata(self):
        """测试：工具元数据"""
        tool = FileReadTool()

        assert tool.name == "file-read"
        assert "read" in tool.description.lower()
        assert tool.risk_level == RiskLevel.LOW
        assert tool.timeout_seconds == 5
        assert "file" in tool.capabilities
        assert "read" in tool.capabilities

    def test_input_schema_validation(self):
        """测试：输入 Schema 校验"""
        tool = FileReadTool()

        # 有效输入
        result = tool.validate_input({"file_path": "/path/to/file.txt"})
        assert result.valid is True

        # 缺少必填字段
        result = tool.validate_input({})
        assert result.valid is False
        assert any("file_path" in error for error in result.errors)

    def test_validate_input_rejects_path_traversal(self):
        """测试：输入校验拒绝路径穿越"""
        tool = FileReadTool()

        result = tool.validate_input({"file_path": "../../../etc/passwd"})

        assert result.valid is False
        assert any("traversal" in error.lower() for error in result.errors)

    def test_validate_input_empty_path(self):
        """测试：输入校验拒绝空路径"""
        tool = FileReadTool()

        result = tool.validate_input({"file_path": ""})

        assert result.valid is False
        assert any("empty" in error.lower() for error in result.errors)

    @pytest.mark.asyncio
    async def test_read_file_success(self):
        """测试：成功读取文件"""
        tool = FileReadTool()

        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("Hello, World!\nLine 2\nLine 3")
            temp_path = f.name

        try:
            # 准备上下文
            temp_dir = str(Path(temp_path).parent)
            context = ExecutionContext(
                trace_id="trace-001",
                action_id="action-001",
                user_id="user-001",
                organization_id="org-001",
                project_id="proj-001",
                task_id="task-001",
                allowed_paths=[temp_dir]
            )

            # 执行
            result = await tool.execute({"file_path": temp_path}, context)

            # 验证
            assert result.success is True
            assert result.output["content"] == "Hello, World!\nLine 2\nLine 3"
            assert result.output["lines"] == 3
            assert result.output["size"] > 0
            assert result.output["path"] == str(Path(temp_path).resolve())

        finally:
            # 清理
            Path(temp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_read_file_not_found(self):
        """测试：文件不存在"""
        tool = FileReadTool()

        context = ExecutionContext(
            trace_id="trace-001",
            action_id="action-001",
            user_id="user-001",
            organization_id="org-001",
            project_id="proj-001",
            task_id="task-001",
            allowed_paths=["/tmp"]
        )

        with pytest.raises(ToolExecutionError, match="not found"):
            await tool.execute({"file_path": "/tmp/nonexistent-file.txt"}, context)

    @pytest.mark.asyncio
    async def test_read_directory_fails(self):
        """测试：尝试读取目录失败"""
        tool = FileReadTool()

        with tempfile.TemporaryDirectory() as temp_dir:
            context = ExecutionContext(
                trace_id="trace-001",
                action_id="action-001",
                user_id="user-001",
                organization_id="org-001",
                project_id="proj-001",
                task_id="task-001",
                allowed_paths=[temp_dir]
            )

            with pytest.raises(ToolExecutionError, match="Not a file"):
                await tool.execute({"file_path": temp_dir}, context)

    @pytest.mark.asyncio
    async def test_permission_check_default_deny(self):
        """测试：默认拒绝 - 无 allowed_paths"""
        tool = FileReadTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test")
            temp_path = f.name

        try:
            context = ExecutionContext(
                trace_id="trace-001",
                action_id="action-001",
                user_id="user-001",
                organization_id="org-001",
                project_id="proj-001",
                task_id="task-001",
                allowed_paths=[]  # 空列表 = 默认拒绝
            )

            with pytest.raises(ToolExecutionError, match="no allowed_paths"):
                await tool.execute({"file_path": temp_path}, context)

        finally:
            Path(temp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_permission_check_path_not_in_allowed(self):
        """测试：路径不在 allowed_paths 内"""
        tool = FileReadTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test")
            temp_path = f.name

        try:
            context = ExecutionContext(
                trace_id="trace-001",
                action_id="action-001",
                user_id="user-001",
                organization_id="org-001",
                project_id="proj-001",
                task_id="task-001",
                allowed_paths=["/completely/different/path"]
            )

            with pytest.raises(ToolExecutionError, match="not in allowed_paths"):
                await tool.execute({"file_path": temp_path}, context)

        finally:
            Path(temp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_sensitive_file_blocked_env(self):
        """测试：敏感文件被阻止 - .env"""
        tool = FileReadTool()

        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建 .env 文件
            env_file = Path(temp_dir) / ".env"
            env_file.write_text("SECRET_KEY=abc123")

            context = ExecutionContext(
                trace_id="trace-001",
                action_id="action-001",
                user_id="user-001",
                organization_id="org-001",
                project_id="proj-001",
                task_id="task-001",
                allowed_paths=[temp_dir]
            )

            with pytest.raises(ToolExecutionError, match="sensitive file"):
                await tool.execute({"file_path": str(env_file)}, context)

    @pytest.mark.asyncio
    async def test_sensitive_file_blocked_private_key(self):
        """测试：敏感文件被阻止 - SSH 私钥"""
        tool = FileReadTool()

        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建私钥文件
            key_file = Path(temp_dir) / "id_rsa"
            key_file.write_text("-----BEGIN RSA PRIVATE KEY-----\ntest")

            context = ExecutionContext(
                trace_id="trace-001",
                action_id="action-001",
                user_id="user-001",
                organization_id="org-001",
                project_id="proj-001",
                task_id="task-001",
                allowed_paths=[temp_dir]
            )

            with pytest.raises(ToolExecutionError, match="sensitive"):
                await tool.execute({"file_path": str(key_file)}, context)

    @pytest.mark.asyncio
    async def test_file_size_limit_exceeded(self):
        """测试：文件大小超限"""
        tool = FileReadTool()

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            # 写入大量数据
            f.write("x" * (11 * 1024 * 1024))  # 11MB
            temp_path = f.name

        try:
            context = ExecutionContext(
                trace_id="trace-001",
                action_id="action-001",
                user_id="user-001",
                organization_id="org-001",
                project_id="proj-001",
                task_id="task-001",
                allowed_paths=[str(Path(temp_path).parent)],
                max_file_size_bytes=10 * 1024 * 1024  # 10MB
            )

            with pytest.raises(ToolExecutionError, match="too large"):
                await tool.execute({"file_path": temp_path}, context)

        finally:
            Path(temp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_binary_file_rejected(self):
        """测试：二进制文件被拒绝"""
        tool = FileReadTool()

        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".bin") as f:
            # 写入包含空字节的二进制数据
            f.write(b"\x00\x01\x02\x03\xff\xfe")
            temp_path = f.name

        try:
            context = ExecutionContext(
                trace_id="trace-001",
                action_id="action-001",
                user_id="user-001",
                organization_id="org-001",
                project_id="proj-001",
                task_id="task-001",
                allowed_paths=[str(Path(temp_path).parent)]
            )

            with pytest.raises(ToolExecutionError, match="Binary file not supported"):
                await tool.execute({"file_path": temp_path}, context)

        finally:
            Path(temp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_custom_encoding(self):
        """测试：自定义编码"""
        tool = FileReadTool()

        with tempfile.NamedTemporaryFile(mode="w", encoding="gbk", delete=False) as f:
            f.write("中文测试")
            temp_path = f.name

        try:
            context = ExecutionContext(
                trace_id="trace-001",
                action_id="action-001",
                user_id="user-001",
                organization_id="org-001",
                project_id="proj-001",
                task_id="task-001",
                allowed_paths=[str(Path(temp_path).parent)]
            )

            result = await tool.execute(
                {"file_path": temp_path, "encoding": "gbk"},
                context
            )

            assert result.success is True
            assert result.output["content"] == "中文测试"

        finally:
            Path(temp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_path_traversal_after_normalization(self):
        """测试：规范化后仍存在路径穿越"""
        tool = FileReadTool()

        # 创建测试文件结构
        with tempfile.TemporaryDirectory() as temp_dir:
            allowed_dir = Path(temp_dir) / "allowed"
            allowed_dir.mkdir()

            secret_dir = Path(temp_dir) / "secret"
            secret_dir.mkdir()

            secret_file = secret_dir / "secret.txt"
            secret_file.write_text("secret data")

            context = ExecutionContext(
                trace_id="trace-001",
                action_id="action-001",
                user_id="user-001",
                organization_id="org-001",
                project_id="proj-001",
                task_id="task-001",
                allowed_paths=[str(allowed_dir)]
            )

            # 尝试通过相对路径访问 secret 文件
            tricky_path = str(allowed_dir / ".." / "secret" / "secret.txt")

            with pytest.raises(ToolExecutionError, match="not in allowed_paths"):
                await tool.execute({"file_path": tricky_path}, context)
