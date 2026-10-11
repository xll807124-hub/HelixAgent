"""
文件搜索工具单元测试
"""
import tempfile
from pathlib import Path

import pytest

from src.tools.base import ExecutionContext
from src.tools.file.search import FileSearchTool


@pytest.fixture
def temp_workspace():
    """创建临时工作目录和文件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        # 创建目录结构
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / ".git").mkdir()
        (root / "__pycache__").mkdir()
        
        # 创建测试文件
        (root / "README.md").write_text("# Project\nThis is a test project")
        (root / "src" / "main.py").write_text("def hello():\n    print('hello')\n")
        (root / "src" / "utils.py").write_text("def util_func():\n    pass\n")
        (root / "tests" / "test_main.py").write_text("def test_hello():\n    assert True\n")
        (root / ".env").write_text("API_KEY=secret")
        
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
        read_only=True,
        timeout_seconds=30,
    )


@pytest.fixture
def tool():
    """创建工具实例"""
    return FileSearchTool()


class TestFileSearchToolByFilename:
    """按文件名搜索测试"""

    @pytest.mark.asyncio
    async def test_search_by_filename_pattern(self, tool, execution_context, temp_workspace):
        """测试文件名模式搜索"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "*.py",
                "search_type": "filename",
            },
            execution_context
        )
        assert result.success
        assert len(result.output["results"]) > 0
        py_files = [r for r in result.output["results"] if r["path"].endswith(".py")]
        assert len(py_files) >= 2  # main.py, utils.py, test_main.py

    @pytest.mark.asyncio
    async def test_search_by_filename_substring(self, tool, execution_context, temp_workspace):
        """测试文件名子串搜索"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "main",
                "search_type": "filename",
            },
            execution_context
        )
        assert result.success
        results = result.output["results"]
        assert any("main" in r["path"] for r in results)

    @pytest.mark.asyncio
    async def test_search_with_extension_filter(self, tool, execution_context, temp_workspace):
        """测试扩展名过滤"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "*",
                "search_type": "filename",
                "file_extensions": [".py"],
            },
            execution_context
        )
        assert result.success
        for r in result.output["results"]:
            assert r["path"].endswith(".py")

    @pytest.mark.asyncio
    async def test_search_max_results_limit(self, tool, execution_context, temp_workspace):
        """测试结果数量限制"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "*",
                "search_type": "filename",
                "max_results": 2,
            },
            execution_context
        )
        assert result.success
        assert len(result.output["results"]) <= 2
        assert result.output["truncated"] == (len(result.output["results"]) >= 2)

    @pytest.mark.asyncio
    async def test_search_excludes_sensitive_files(self, tool, execution_context, temp_workspace):
        """测试敏感文件过滤"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "*",
                "search_type": "filename",
            },
            execution_context
        )
        assert result.success
        paths = [r["path"] for r in result.output["results"]]
        # .env 应该被过滤
        assert not any(".env" in p for p in paths)

    @pytest.mark.asyncio
    async def test_search_excludes_system_dirs(self, tool, execution_context, temp_workspace):
        """测试系统目录过滤"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "*",
                "search_type": "filename",
            },
            execution_context
        )
        assert result.success
        paths = [r["path"] for r in result.output["results"]]
        # __pycache__ 和 .git 应该被过滤
        assert not any("__pycache__" in p for p in paths)
        assert not any(".git" in p for p in paths)


class TestFileSearchToolByContent:
    """按内容搜索测试"""

    @pytest.mark.asyncio
    async def test_search_by_content_simple(self, tool, execution_context, temp_workspace):
        """测试简单内容搜索"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "print",
                "search_type": "content",
            },
            execution_context
        )
        assert result.success
        assert len(result.output["results"]) > 0
        assert any("matches" in r for r in result.output["results"])

    @pytest.mark.asyncio
    async def test_search_by_content_regex(self, tool, execution_context, temp_workspace):
        """测试正则表达式搜索"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": r"def\s+\w+\(",
                "search_type": "content",
            },
            execution_context
        )
        assert result.success
        # 应该找到函数定义
        assert len(result.output["results"]) > 0

    @pytest.mark.asyncio
    async def test_search_case_sensitive(self, tool, execution_context, temp_workspace):
        """测试大小写敏感搜索"""
        result_sensitive = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "HELLO",
                "search_type": "content",
                "case_sensitive": True,
            },
            execution_context
        )
        
        result_insensitive = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "hello",
                "search_type": "content",
                "case_sensitive": False,
            },
            execution_context
        )
        
        assert result_sensitive.success
        assert result_insensitive.success
        # 不区分大小写应该找到更多结果
        assert len(result_insensitive.output["results"]) >= len(result_sensitive.output["results"])

    @pytest.mark.asyncio
    async def test_search_content_with_extension_filter(
        self, tool, execution_context, temp_workspace
    ):
        """测试内容搜索 + 扩展名过滤"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "def",
                "search_type": "content",
                "file_extensions": [".py"],
            },
            execution_context
        )
        assert result.success
        for r in result.output["results"]:
            assert r["path"].endswith(".py")


class TestFileSearchToolValidation:
    """输入验证测试"""

    def test_validate_missing_search_path(self, tool, execution_context):
        """测试缺失搜索路径"""
        result = tool.validate_input(
            {"pattern": "test"},
            execution_context
        )
        assert not result.valid

    def test_validate_missing_pattern(self, tool, execution_context, temp_workspace):
        """测试缺失模式"""
        result = tool.validate_input(
            {"search_path": temp_workspace},
            execution_context
        )
        assert not result.valid

    def test_validate_nonexistent_path(self, tool, execution_context):
        """测试不存在的路径"""
        result = tool.validate_input(
            {
                "search_path": "/nonexistent/path",
                "pattern": "test",
            },
            execution_context
        )
        assert not result.valid

    def test_validate_path_traversal(self, tool, execution_context):
        """测试路径穿越检查"""
        result = tool.validate_input(
            {
                "search_path": "../../etc/",
                "pattern": "test",
            },
            execution_context
        )
        assert not result.valid

    def test_validate_outside_allowed_paths(self, tool):
        """测试权限外路径"""
        ctx = ExecutionContext(
            trace_id="", action_id="", user_id="", organization_id="",
            project_id="", task_id="",
            allowed_paths=["/safe/path"],
        )
        result = tool.validate_input(
            {
                "search_path": "/unsafe/path",
                "pattern": "test",
            },
            ctx
        )
        assert not result.valid


class TestFileSearchToolEdgeCases:
    """边界情况测试"""

    @pytest.mark.asyncio
    async def test_search_empty_directory(self, tool, execution_context):
        """测试空目录搜索"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = ExecutionContext(
                trace_id="", action_id="", user_id="", organization_id="",
                project_id="", task_id="",
                allowed_paths=[tmpdir],
            )
            result = await tool.execute(
                {
                    "search_path": tmpdir,
                    "pattern": "*",
                    "search_type": "filename",
                },
                ctx
            )
            assert result.success
            assert len(result.output["results"]) == 0

    @pytest.mark.asyncio
    async def test_search_no_matches(self, tool, execution_context, temp_workspace):
        """测试无匹配结果"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "nonexistent_pattern_xyz",
                "search_type": "filename",
            },
            execution_context
        )
        assert result.success
        assert len(result.output["results"]) == 0

    @pytest.mark.asyncio
    async def test_search_result_contains_metadata(self, tool, execution_context, temp_workspace):
        """测试结果元数据"""
        result = await tool.execute(
            {
                "search_path": temp_workspace,
                "pattern": "*.py",
                "search_type": "filename",
            },
            execution_context
        )
        assert result.success
        if result.output["results"]:
            item = result.output["results"][0]
            assert "path" in item
            assert "type" in item
            assert "size" in item


class TestFileSearchToolProperties:
    """工具属性测试"""

    def test_tool_name(self, tool):
        """测试工具名称"""
        assert tool.name == "file-search"

    def test_tool_description(self, tool):
        """测试工具描述"""
        assert "search" in tool.description.lower()

    def test_tool_risk_level(self, tool):
        """测试工具风险等级"""
        from src.tools.base import RiskLevel
        assert tool.risk_level == RiskLevel.LOW

    def test_input_schema_required_fields(self, tool):
        """测试输入 schema 必填项"""
        schema = tool.input_schema
        assert "search_path" in schema["required"]
        assert "pattern" in schema["required"]

    def test_output_schema(self, tool):
        """测试输出 schema"""
        schema = tool.output_schema
        assert "results" in schema["properties"]
        assert "total" in schema["properties"]
        assert "truncated" in schema["properties"]
