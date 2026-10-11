"""
工具基类和执行上下文定义

对齐设计文档：REQ-HAR-003 Tool Adapter and Tool Schema
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """工具风险级别（REQ-HAR-003 §3.2）"""
    LOW = "LOW"           # 只读操作，无副作用
    MEDIUM = "MEDIUM"     # 有限副作用（写临时文件）
    HIGH = "HIGH"         # 高风险操作（修改代码、执行命令）


class ToolResult(BaseModel):
    """工具执行结果（REQ-HAR-003 §4）"""
    success: bool
    output: Any
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    execution_time_ms: int = 0


class ValidationResult(BaseModel):
    """输入校验结果"""
    valid: bool
    errors: list[str] = Field(default_factory=list)


class ExecutionContext(BaseModel):
    """工具执行上下文（REQ-RT-001 TraceContext + 权限）"""
    trace_id: str
    action_id: str
    user_id: str
    organization_id: str
    project_id: str
    task_id: str

    # 权限上下文（REQ-SEC-002）
    allowed_paths: list[str] = Field(default_factory=list)  # 允许访问的路径
    read_only: bool = False  # 是否只读模式

    # 资源限制
    timeout_seconds: int = 30
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10MB


class BaseTool(ABC):
    """
    工具基类，定义所有工具的标准接口
    
    对齐设计文档：REQ-HAR-003 Tool Adapter
    职责：
    1. 声明工具元数据（名称、描述、Schema、风险级别）
    2. 实现输入校验逻辑
    3. 实现工具执行逻辑
    """

    def __init__(self) -> None:
        self._validate_metadata()

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一名称（kebab-case）"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具功能描述（一句话）"""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """
        输入参数 JSON Schema
        
        示例：
        {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"}
            },
            "required": ["file_path"]
        }
        """
        pass

    @property
    @abstractmethod
    def output_schema(self) -> dict[str, Any]:
        """
        输出结果 JSON Schema
        
        示例：
        {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "size": {"type": "integer"}
            }
        }
        """
        pass

    @property
    @abstractmethod
    def risk_level(self) -> RiskLevel:
        """工具风险级别"""
        pass

    @property
    def timeout_seconds(self) -> int:
        """执行超时时间（秒），默认 30 秒"""
        return 30

    @property
    def capabilities(self) -> list[str]:
        """工具能力标签，用于分类和查找"""
        return []

    @abstractmethod
    async def execute(
        self,
        params: dict[str, Any],
        context: ExecutionContext
    ) -> ToolResult:
        """
        执行工具
        
        Args:
            params: 输入参数（已通过 Schema 校验）
            context: 执行上下文（包含 Trace ID、权限等）
        
        Returns:
            ToolResult: 执行结果
        
        Raises:
            ToolExecutionError: 执行失败
            TimeoutError: 执行超时
        """
        pass

    def validate_input(self, params: dict[str, Any]) -> ValidationResult:
        """
        校验输入参数

        默认实现：基于 input_schema 的基础校验
        子类可重写以添加业务逻辑校验
        """
        errors: list[str] = []

        # 检查必填字段
        required = self.input_schema.get("required", [])
        for field in required:
            if field not in params:
                errors.append(f"Missing required field: {field}")

        # 检查字段类型（简化版，生产环境应使用 jsonschema 库）
        properties = self.input_schema.get("properties", {})
        for field, value in params.items():
            if field not in properties:
                errors.append(f"Unknown field: {field}")
                continue

            expected_type = properties[field].get("type")
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"Field '{field}' must be string, got {type(value).__name__}")
            elif expected_type == "integer" and not isinstance(value, int):
                errors.append(f"Field '{field}' must be integer, got {type(value).__name__}")

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def _validate_metadata(self) -> None:
        """验证工具元数据完整性"""
        if not self.name:
            raise ValueError("Tool name cannot be empty")
        if not self.description:
            raise ValueError("Tool description cannot be empty")
        if not self.input_schema:
            raise ValueError("Tool input_schema cannot be empty")


class ToolExecutionError(Exception):
    """工具执行错误"""
    pass
