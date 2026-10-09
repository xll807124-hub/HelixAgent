"""
文件写入工具

对齐设计文档：
- REQ-HAR-003 Tool Adapter
- REQ-SEC-002 RBAC 与资源授权
- REQ-SEC-003 Policy Gateway（写入前置检查）
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..base import (
    BaseTool,
    ExecutionContext,
    RiskLevel,
    ToolExecutionError,
    ToolResult,
    ValidationResult,
)


class FileWriteTool(BaseTool):
    """
    文件写入工具
    
    功能：
    1. 安全写入文件内容
    2. 路径穿越检查
    3. 创建目录（如需要）
    4. 敏感文件检查
    5. 覆盖保护
    
    安全约束（REQ-SEC-002）：
    - 必须在 allowed_paths 范围内
    - 禁止覆写敏感文件（默认）
    - 禁止路径穿越
    - 文件大小限制
    """

    # 禁止覆写的文件模式
    PROTECTED_PATTERNS = [
        ".git",
        ".gitignore",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        ".env.production",
        "pytest.ini",
    ]

    @property
    def name(self) -> str:
        return "file-write"

    @property
    def description(self) -> str:
        return "Write content to a file with safety checks"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to write to"
                },
                "content": {
                    "type": "string",
                    "description": "File content"
                },
                "create_dirs": {
                    "type": "boolean",
                    "default": True,
                    "description": "Create parent directories if they don't exist"
                },
                "mode": {
                    "type": "string",
                    "enum": ["write", "append"],
                    "default": "write",
                    "description": "Write mode: 'write' (replace) or 'append'"
                },
                "encoding": {
                    "type": "string",
                    "default": "utf-8",
                    "description": "File encoding"
                },
            },
            "required": ["path", "content"],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "bytes_written": {"type": "integer"},
                "file_path": {"type": "string"},
                "created": {"type": "boolean"},
                "mode": {"type": "string"},
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH  # 写入文件是高风险操作

    async def validate_input(self, params: dict, context: ExecutionContext) -> ValidationResult:
        """验证输入参数"""
        errors = []

        # 必填参数检查
        if "path" not in params:
            errors.append("Missing required parameter: path")
        if "content" not in params:
            errors.append("Missing required parameter: content")

        if errors:
            return ValidationResult(valid=False, errors=errors)

        # 参数类型检查
        path = params.get("path")
        content = params.get("content")
        mode = params.get("mode", "write")
        encoding = params.get("encoding", "utf-8")

        if not isinstance(path, str):
            errors.append("path must be a string")
        if not isinstance(content, str):
            errors.append("content must be a string")
        if mode not in ["write", "append"]:
            errors.append("mode must be 'write' or 'append'")
        if not isinstance(encoding, str):
            errors.append("encoding must be a string")

        # 路径安全性检查
        if errors:
            return ValidationResult(valid=False, errors=errors)

        try:
            abs_path = Path(path).resolve()
        except (ValueError, RuntimeError) as e:
            errors.append(f"Invalid path: {e}")
            return ValidationResult(valid=False, errors=errors)

        # 路径穿越检查
        if ".." in path:
            errors.append("Path traversal (..) not allowed")

        # 权限检查：路径必须在 allowed_paths 范围内
        if context.allowed_paths:
            allowed = False
            for allowed_path in context.allowed_paths:
                try:
                    abs_allowed = Path(allowed_path).resolve()
                    # 检查是否在允许的路径下
                    abs_path.relative_to(abs_allowed)
                    allowed = True
                    break
                except ValueError:
                    continue

            if not allowed:
                errors.append(
                    f"Path not in allowed_paths: {context.allowed_paths}"
                )

        # 敏感文件检查
        if self._is_protected_file(abs_path):
            errors.append(
                f"Cannot write to protected file: {abs_path.name}"
            )

        # 文件大小限制
        if len(content.encode(encoding)) > context.max_file_size_bytes:
            errors.append(
                f"Content exceeds max size: {len(content.encode(encoding))} > {context.max_file_size_bytes}"
            )

        return ValidationResult(valid=not bool(errors), errors=errors)

    async def execute(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ToolResult:
        """执行文件写入"""
        try:
            path = params.get("path")
            content = params.get("content")
            create_dirs = params.get("create_dirs", True)
            mode = params.get("mode", "write")
            encoding = params.get("encoding", "utf-8")

            abs_path = Path(path).resolve()

            # 创建父目录（如需要）
            if create_dirs and not abs_path.parent.exists():
                abs_path.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件
            write_mode = "a" if mode == "append" else "w"
            with open(abs_path, write_mode, encoding=encoding) as f:
                bytes_written = f.write(content)

            return ToolResult(
                success=True,
                output={
                    "bytes_written": bytes_written,
                    "file_path": str(abs_path),
                    "created": not abs_path.exists(),
                    "mode": mode,
                },
                metadata={
                    "file_size": abs_path.stat().st_size,
                    "encoding": encoding,
                }
            )

        except (OSError, IOError) as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Failed to write file: {e}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Unexpected error: {e}",
            )

    def _is_protected_file(self, path: Path) -> bool:
        """检查是否是受保护的文件"""
        name = path.name
        return any(pattern in str(path) for pattern in self.PROTECTED_PATTERNS)
