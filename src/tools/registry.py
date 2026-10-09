"""
工具注册表，管理所有可用工具的注册和查找

对齐设计文档：REQ-HAR-003 Tool Adapter，REQ-HAR-005 统一路由
"""
from __future__ import annotations

from typing import Any

from .base import BaseTool, ValidationResult


class ToolRegistry:
    """
    工具注册表
    
    职责：
    1. 管理工具的注册和注销
    2. 按名称查找工具
    3. 按能力标签筛选工具
    4. 提供统一的输入校验接口
    
    线程安全：单线程使用（后续可扩展为线程安全）
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        注册工具
        
        Args:
            tool: 工具实例
        
        Raises:
            ValueError: 工具名称冲突
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")

        self._tools[tool.name] = tool

    def unregister(self, tool_name: str) -> None:
        """
        注销工具
        
        Args:
            tool_name: 工具名称
        """
        self._tools.pop(tool_name, None)

    def get_tool(self, tool_name: str) -> BaseTool | None:
        """
        按名称查找工具
        
        Args:
            tool_name: 工具名称
        
        Returns:
            BaseTool | None: 工具实例，不存在返回 None
        """
        return self._tools.get(tool_name)

    def list_tools(self, capability: str | None = None) -> list[BaseTool]:
        """
        列出所有工具，可按能力筛选
        
        Args:
            capability: 能力标签（如 "file", "git", "test"）
        
        Returns:
            list[BaseTool]: 工具列表
        """
        tools = list(self._tools.values())

        if capability:
            tools = [
                tool for tool in tools
                if capability in tool.capabilities
            ]

        return tools

    def validate_input(
        self,
        tool_name: str,
        params: dict[str, Any]
    ) -> ValidationResult:
        """
        校验工具输入参数
        
        Args:
            tool_name: 工具名称
            params: 输入参数
        
        Returns:
            ValidationResult: 校验结果
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return ValidationResult(
                valid=False,
                errors=[f"Tool '{tool_name}' not found"]
            )

        return tool.validate_input(params)

    def get_tool_count(self) -> int:
        """获取已注册工具数量"""
        return len(self._tools)

    def clear(self) -> None:
        """清空所有已注册工具（用于测试）"""
        self._tools.clear()


# 全局单例（简化版，生产环境应使用依赖注入）
_global_registry: ToolRegistry | None = None


def get_global_registry() -> ToolRegistry:
    """获取全局工具注册表单例"""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def reset_global_registry() -> None:
    """重置全局注册表（用于测试）"""
    global _global_registry
    _global_registry = None
