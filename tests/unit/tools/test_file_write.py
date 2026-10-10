"""
文件写入工具单元测试
"""
import pytest
import tempfile
from pathlib import Path

from src.tools.file.write import FileWriteTool
from src.tools.base import ExecutionContext, RiskLevel


@pytest.fixture
def temp_workspace():
    """创建临时工作目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def execution_context(temp_workspace):
    """创建执行上下文"""
    return ExecutionContext(
        trace_id="test-123",
        action_id="action-123",
        user_id="user-123",
        organization_id="org-123",
        project_id="project-123",
        task_id="task-123",
        allowed_paths=[temp_workspace],
        read_only=False,
        timeout_seconds=30,
        max_file_size_bytes=10 * 1024 * 1024,
    )


@pytest.fixture
def tool():
    """创建工具实例"""
    return FileWriteTool()


class TestFileWriteToolValidation:
    """输入验证测试"""

    def test_validate_missing_path(self, tool, execution_context):
        """测试缺失 path 参数"""
        result = tool.validate_input(
            {"content": "test"},
            execution_context
        )
        assert not result.valid
        assert "path" in str(result.errors).lower()

    def test_validate_missing_content(self, tool, execution_context):
        """测试缺失 content 参数"""
        result = tool.validate_input(
            {"path": "/tmp/test.txt"},
            execution_context
        )
        assert not result.valid
        assert "content" in str(result.errors).lower()

    def test_validate_path_traversal(self, tool, execution_context):
        """测试路径穿越检查"""
        result = tool.validate_input(
            {"path": "../../etc/passwd", "content": "test"},
            execution_context
        )
        assert not result.valid
        assert any("traversal" in e.lower() for e in result.errors)

    def test_validate_protected_file(self, tool, execution_context, temp_workspace):
        """测试保护文件检查"""
        result = tool.validate_input(
            {"path": str(Path(temp_workspace) / ".env.production"), "content": "test"},
            execution_context
        )
        assert not result.valid
        assert any("protected" in e.lower() for e in result.errors)

    def test_validate_file_size_limit(self, tool, execution_context, temp_workspace):
        """测试文件大小限制"""
        huge_content = "x" * (execution_context.max_file_size_bytes + 1)
        result = tool.validate_input(
            {"path": str(Path(temp_workspace) / "huge.txt"), "content": huge_content},
            execution_context
        )
        assert not result.valid
        assert any("exceeds" in e.lower() for e in result.errors)

    def test_validate_invalid_mode(self, tool, execution_context, temp_workspace):
        """测试无效的写入模式"""
        result = tool.validate_input(
            {
                "path": str(Path(temp_workspace) / "test.txt"),
                "content": "test",
                "mode": "invalid",
            },
            execution_context
        )
        assert not result.valid
        assert any("mode" in e.lower() for e in result.errors)

    def test_validate_success(self, tool, execution_context, temp_workspace):
        """测试验证成功"""
        result = tool.validate_input(
            {"path": str(Path(temp_workspace) / "test.txt"), "content": "hello world"},
            execution_context
        )
        assert result.valid
        assert len(result.errors) == 0


class TestFileWriteToolExecution:
    """执行测试"""

    @pytest.mark.asyncio
    async def test_write_new_file(self, tool, execution_context, temp_workspace):
        """测试创建新文件"""
        filepath = Path(temp_workspace) / "new_file.txt"
        result = await tool.execute(
            {
                "path": str(filepath),
                "content": "hello world",
                "create_dirs": True,
            },
            execution_context
        )
        assert result.success
        assert filepath.exists()
        assert filepath.read_text() == "hello world"
        assert result.output["bytes_written"] == 11

    @pytest.mark.asyncio
    async def test_write_with_subdirs(self, tool, execution_context, temp_workspace):
        """测试创建子目录"""
        filepath = Path(temp_workspace) / "dir1" / "dir2" / "file.txt"
        result = await tool.execute(
            {
                "path": str(filepath),
                "content": "nested",
                "create_dirs": True,
            },
            execution_context
        )
        assert result.success
        assert filepath.exists()
        assert filepath.read_text() == "nested"

    @pytest.mark.asyncio
    async def test_write_append_mode(self, tool, execution_context, temp_workspace):
        """测试追加模式"""
        filepath = Path(temp_workspace) / "append.txt"
        
        # 先写入
        await tool.execute(
            {"path": str(filepath), "content": "line1\n"},
            execution_context
        )
        
        # 再追加
        result = await tool.execute(
            {
                "path": str(filepath),
                "content": "line2\n",
                "mode": "append",
            },
            execution_context
        )
        assert result.success
        content = filepath.read_text()
        assert "line1" in content
        assert "line2" in content

    @pytest.mark.asyncio
    async def test_write_with_custom_encoding(self, tool, execution_context, temp_workspace):
        """测试自定义编码"""
        filepath = Path(temp_workspace) / "utf8.txt"
        result = await tool.execute(
            {
                "path": str(filepath),
                "content": "你好世界",
                "encoding": "utf-8",
            },
            execution_context
        )
        assert result.success
        assert filepath.read_text(encoding="utf-8") == "你好世界"

    @pytest.mark.asyncio
    async def test_overwrite_existing_file(self, tool, execution_context, temp_workspace):
        """测试覆写现有文件"""
        filepath = Path(temp_workspace) / "overwrite.txt"
        filepath.write_text("original")
        
        result = await tool.execute(
            {
                "path": str(filepath),
                "content": "new content",
                "mode": "write",
            },
            execution_context
        )
        assert result.success
        assert filepath.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_metadata_included(self, tool, execution_context, temp_workspace):
        """测试元数据包含"""
        filepath = Path(temp_workspace) / "meta.txt"
        result = await tool.execute(
            {
                "path": str(filepath),
                "content": "test content",
            },
            execution_context
        )
        assert result.success
        assert "encoding" in result.metadata
        assert "file_size" in result.metadata


class TestFileWriteToolEdgeCases:
    """边界情况测试"""

    @pytest.mark.asyncio
    async def test_empty_content(self, tool, execution_context, temp_workspace):
        """测试空内容"""
        filepath = Path(temp_workspace) / "empty.txt"
        result = await tool.execute(
            {"path": str(filepath), "content": ""},
            execution_context
        )
        assert result.success
        assert filepath.exists()
        assert filepath.stat().st_size == 0

    @pytest.mark.asyncio
    async def test_special_characters(self, tool, execution_context, temp_workspace):
        """测试特殊字符"""
        filepath = Path(temp_workspace) / "special.txt"
        content = "Line1\nLine2\tTabbed\nWindows"
        result = await tool.execute(
            {"path": str(filepath), "content": content},
            execution_context
        )
        assert result.success
        # 在 Windows 上，\n 会转换为 \r\n，这是预期行为
        written_content = filepath.read_text()
        assert "Line1" in written_content
        assert "Line2" in written_content
        assert "Tabbed" in written_content
        assert "Windows" in written_content

    @pytest.mark.asyncio
    async def test_large_file(self, tool, execution_context, temp_workspace):
        """测试大文件写入"""
        filepath = Path(temp_workspace) / "large.txt"
        large_content = "x" * (1024 * 1024)  # 1MB
        result = await tool.execute(
            {"path": str(filepath), "content": large_content},
            execution_context
        )
        assert result.success
        assert len(filepath.read_text()) == len(large_content)

    def test_permission_denied_outside_allowed_paths(self, tool, execution_context):
        """测试权限外路径拒绝"""
        result = tool.validate_input(
            {"path": "/root/forbidden.txt", "content": "test"},
            execution_context
        )
        assert not result.valid
        assert any("allowed" in e.lower() for e in result.errors)


class TestFileWriteToolProperties:
    """工具属性测试"""

    def test_tool_name(self, tool):
        """测试工具名称"""
        assert tool.name == "file-write"

    def test_tool_description(self, tool):
        """测试工具描述"""
        assert "write" in tool.description.lower()

    def test_tool_risk_level(self, tool):
        """测试工具风险等级"""
        assert tool.risk_level == RiskLevel.HIGH

    def test_input_schema(self, tool):
        """测试输入 schema"""
        schema = tool.input_schema
        assert "properties" in schema
        assert "path" in schema["properties"]
        assert "content" in schema["properties"]
        assert "path" in schema["required"]
        assert "content" in schema["required"]

    def test_output_schema(self, tool):
        """测试输出 schema"""
        schema = tool.output_schema
        assert "properties" in schema
        assert "bytes_written" in schema["properties"]
        assert "file_path" in schema["properties"]
