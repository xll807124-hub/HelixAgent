"""
ToolRegistry 单元测试

测试覆盖：
1. 工具注册和查找
2. 工具名称冲突
3. 按能力标签筛选
4. 输入校验
5. 边界场景
"""
import pytest

from src.tools import (
    BaseTool,
    ExecutionContext,
    RiskLevel,
    ToolRegistry,
    ToolResult,
)


class DummyTool(BaseTool):
    """测试用假工具"""

    @property
    def name(self) -> str:
        return "dummy-tool"

    @property
    def description(self) -> str:
        return "A dummy tool for testing"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param1": {"type": "string"}
            },
            "required": ["param1"]
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "result": {"type": "string"}
            }
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    @property
    def capabilities(self) -> list[str]:
        return ["test", "dummy"]

    async def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        return ToolResult(success=True, output={"result": "ok"})


class AnotherTool(BaseTool):
    """另一个测试工具"""

    @property
    def name(self) -> str:
        return "another-tool"

    @property
    def description(self) -> str:
        return "Another tool"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "value": {"type": "integer"}
            },
            "required": ["value"]
        }

    @property
    def output_schema(self) -> dict:
        return {"type": "object"}

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.MEDIUM

    @property
    def capabilities(self) -> list[str]:
        return ["compute"]

    async def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        return ToolResult(success=True, output={"value": params["value"] * 2})


class TestToolRegistry:
    """ToolRegistry 测试套件"""

    def test_register_tool(self):
        """测试：注册工具"""
        registry = ToolRegistry()
        tool = DummyTool()

        registry.register(tool)

        assert registry.get_tool_count() == 1
        assert registry.get_tool("dummy-tool") is tool

    def test_register_duplicate_tool_raises_error(self):
        """测试：重复注册工具名称冲突"""
        registry = ToolRegistry()
        tool1 = DummyTool()
        tool2 = DummyTool()

        registry.register(tool1)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(tool2)

    def test_get_tool_not_found(self):
        """测试：查找不存在的工具"""
        registry = ToolRegistry()

        result = registry.get_tool("nonexistent-tool")

        assert result is None

    def test_unregister_tool(self):
        """测试：注销工具"""
        registry = ToolRegistry()
        tool = DummyTool()
        registry.register(tool)

        registry.unregister("dummy-tool")

        assert registry.get_tool_count() == 0
        assert registry.get_tool("dummy-tool") is None

    def test_unregister_nonexistent_tool_no_error(self):
        """测试：注销不存在的工具不报错"""
        registry = ToolRegistry()

        # 不应抛出异常
        registry.unregister("nonexistent-tool")

        assert registry.get_tool_count() == 0

    def test_list_all_tools(self):
        """测试：列出所有工具"""
        registry = ToolRegistry()
        tool1 = DummyTool()
        tool2 = AnotherTool()

        registry.register(tool1)
        registry.register(tool2)

        tools = registry.list_tools()

        assert len(tools) == 2
        assert tool1 in tools
        assert tool2 in tools

    def test_list_tools_by_capability(self):
        """测试：按能力标签筛选工具"""
        registry = ToolRegistry()
        tool1 = DummyTool()  # capabilities: ["test", "dummy"]
        tool2 = AnotherTool()  # capabilities: ["compute"]

        registry.register(tool1)
        registry.register(tool2)

        test_tools = registry.list_tools(capability="test")
        compute_tools = registry.list_tools(capability="compute")

        assert len(test_tools) == 1
        assert test_tools[0] is tool1

        assert len(compute_tools) == 1
        assert compute_tools[0] is tool2

    def test_list_tools_capability_not_found(self):
        """测试：筛选不存在的能力标签"""
        registry = ToolRegistry()
        tool = DummyTool()
        registry.register(tool)

        tools = registry.list_tools(capability="nonexistent")

        assert len(tools) == 0

    def test_validate_input_success(self):
        """测试：输入校验成功"""
        registry = ToolRegistry()
        tool = DummyTool()
        registry.register(tool)

        result = registry.validate_input("dummy-tool", {"param1": "value"})

        assert result.valid is True
        assert len(result.errors) == 0

    def test_validate_input_missing_required_field(self):
        """测试：输入校验失败 - 缺少必填字段"""
        registry = ToolRegistry()
        tool = DummyTool()
        registry.register(tool)

        result = registry.validate_input("dummy-tool", {})

        assert result.valid is False
        assert any("param1" in error for error in result.errors)

    def test_validate_input_tool_not_found(self):
        """测试：输入校验 - 工具不存在"""
        registry = ToolRegistry()

        result = registry.validate_input("nonexistent-tool", {})

        assert result.valid is False
        assert any("not found" in error for error in result.errors)

    def test_clear_registry(self):
        """测试：清空注册表"""
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(AnotherTool())

        registry.clear()

        assert registry.get_tool_count() == 0

    def test_multiple_tools_same_capability(self):
        """测试：多个工具共享同一能力标签"""
        registry = ToolRegistry()

        # 创建两个都有 "test" 能力的工具
        tool1 = DummyTool()  # capabilities: ["test", "dummy"]
        registry.register(tool1)

        # 创建另一个工具并添加 "test" 能力
        class TestTool(AnotherTool):
            @property
            def name(self) -> str:
                return "test-tool"

            @property
            def capabilities(self) -> list[str]:
                return ["test", "compute"]

        tool2 = TestTool()
        registry.register(tool2)

        test_tools = registry.list_tools(capability="test")

        assert len(test_tools) == 2
        assert tool1 in test_tools
        assert tool2 in test_tools
