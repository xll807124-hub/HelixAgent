"""
文件读取工具

对齐设计文档：
- REQ-HAR-003 Tool Adapter
- REQ-SEC-002 RBAC 与资源授权（路径级权限）
- REQ-CTX-005 检索权限与敏感路径过滤
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


class FileReadTool(BaseTool):
    """
    文件读取工具
    
    功能：
    1. 安全读取文件内容
    2. 路径穿越检查
    3. 文件大小限制
    4. 敏感文件过滤
    5. 二进制文件检测
    
    安全约束（REQ-SEC-002）：
    - 必须在 allowed_paths 范围内
    - 禁止路径穿越（../ 等）
    - 禁止访问敏感文件（.env, .git/config, 密钥等）
    """

    # 敏感文件模式列表（REQ-CTX-005 §4.2）
    SENSITIVE_PATTERNS = [
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
        "service-account.json",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        "secret",
        "token",
        "password",
        ".git/config",
        ".netrc",
        ".npmrc",
        ".pypirc",
    ]

    @property
    def name(self) -> str:
        return "file-read"

    @property
    def description(self) -> str:
        return "Read file content from the filesystem (read-only)"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative or absolute file path to read"
                },
                "encoding": {
                    "type": "string",
                    "description": "File encoding (default: utf-8)",
                    "default": "utf-8"
                }
            },
            "required": ["file_path"]
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "File content"
                },
                "size": {
                    "type": "integer",
                    "description": "File size in bytes"
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines"
                },
                "path": {
                    "type": "string",
                    "description": "Resolved absolute path"
                }
            }
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW  # 只读操作，无副作用

    @property
    def timeout_seconds(self) -> int:
        return 5  # 文件读取 5 秒超时

    @property
    def capabilities(self) -> list[str]:
        return ["file", "read", "filesystem"]

    def validate_input(self, params: dict[str, Any]) -> ValidationResult:
        """扩展校验：检查路径格式"""
        # 先执行基础 Schema 校验
        result = super().validate_input(params)
        if not result.valid:
            return result

        errors: list[str] = []
        file_path = params.get("file_path", "")

        # 检查路径不为空
        if not file_path or not file_path.strip():
            errors.append("file_path cannot be empty")

        # 检查路径穿越特征（初步检查，execute 中会做规范化后再检查）
        if ".." in file_path:
            errors.append("Path traversal detected: '..' not allowed in file_path")

        # 检查绝对路径格式（Windows 和 Unix）
        if file_path.startswith("/") or (len(file_path) > 1 and file_path[1] == ":"):
            # 绝对路径需要在 execute 时检查 allowed_paths
            pass

        return ValidationResult(
            valid=len(errors) == 0,
            errors=result.errors + errors
        )

    async def execute(
        self,
        params: dict[str, Any],
        context: ExecutionContext
    ) -> ToolResult:
        """
        执行文件读取
        
        安全检查顺序（REQ-SEC-002）：
        1. 路径规范化（解析符号链接、相对路径）
        2. 路径穿越检查
        3. allowed_paths 权限检查
        4. 敏感文件过滤
        5. 文件大小检查
        6. 二进制文件检测
        7. 读取内容
        """
        file_path = params["file_path"]
        encoding = params.get("encoding", "utf-8")

        try:
            # 步骤1: 路径规范化
            resolved_path = self._resolve_path(file_path)

            # 步骤2: 路径穿越检查（规范化后仍可能出现 ..）
            if ".." in str(resolved_path):
                raise ToolExecutionError(
                    f"Path traversal detected after normalization: {resolved_path}"
                )

            # 步骤3: 权限检查
            self._check_permission(resolved_path, context)

            # 步骤4: 敏感文件过滤
            self._check_sensitive_file(resolved_path)

            # 步骤5: 文件存在性和大小检查
            if not resolved_path.exists():
                raise ToolExecutionError(f"File not found: {resolved_path}")

            if not resolved_path.is_file():
                raise ToolExecutionError(f"Not a file: {resolved_path}")

            file_size = resolved_path.stat().st_size
            if file_size > context.max_file_size_bytes:
                raise ToolExecutionError(
                    f"File too large: {file_size} bytes "
                    f"(max: {context.max_file_size_bytes})"
                )

            # 步骤6: 二进制文件检测（读取前 8KB）
            if self._is_binary_file(resolved_path):
                raise ToolExecutionError(
                    f"Binary file not supported: {resolved_path}"
                )

            # 步骤7: 读取内容
            content = resolved_path.read_text(encoding=encoding)
            lines = content.count("\n") + 1 if content else 0

            return ToolResult(
                success=True,
                output={
                    "content": content,
                    "size": file_size,
                    "lines": lines,
                    "path": str(resolved_path)
                },
                metadata={
                    "encoding": encoding,
                    "resolved_path": str(resolved_path)
                }
            )

        except ToolExecutionError:
            raise
        except UnicodeDecodeError as e:
            raise ToolExecutionError(
                f"Failed to decode file with encoding '{encoding}': {e}"
            )
        except Exception as e:
            raise ToolExecutionError(f"Failed to read file: {e}")

    def _resolve_path(self, file_path: str) -> Path:
        """
        解析路径为规范化的绝对路径
        
        处理：
        - 相对路径转绝对路径（相对于当前工作目录）
        - 解析符号链接
        - 规范化路径分隔符
        """
        path = Path(file_path)

        # 转换为绝对路径
        if not path.is_absolute():
            path = Path.cwd() / path

        # 规范化路径（resolve 会解析符号链接）
        try:
            path = path.resolve()
        except Exception:
            # resolve 失败（如路径不存在），使用 absolute
            path = path.absolute()

        return path

    def _check_permission(
        self,
        resolved_path: Path,
        context: ExecutionContext
    ) -> None:
        """
        检查路径权限（REQ-SEC-002 路径级权限）
        
        规则：
        1. 如果 allowed_paths 为空，拒绝访问（默认拒绝）
        2. 路径必须在 allowed_paths 的某个前缀下
        """
        if not context.allowed_paths:
            raise ToolExecutionError(
                "Access denied: no allowed_paths configured "
                "(REQ-SEC-002 default deny)"
            )

        resolved_str = str(resolved_path)

        # 检查是否在任一允许路径下
        allowed = False
        for allowed_path in context.allowed_paths:
            # 规范化 allowed_path
            allowed_prefix = str(Path(allowed_path).resolve())

            # 检查是否为前缀（或完全匹配）
            if resolved_str == allowed_prefix or resolved_str.startswith(
                allowed_prefix + os.sep
            ):
                allowed = True
                break

        if not allowed:
            raise ToolExecutionError(
                f"Access denied: {resolved_path} not in allowed_paths "
                f"(REQ-SEC-002)"
            )

    def _check_sensitive_file(self, resolved_path: Path) -> None:
        """
        敏感文件过滤（REQ-CTX-005 §4.2）
        
        检查文件名或路径是否包含敏感模式
        """
        path_str = str(resolved_path).lower()
        file_name = resolved_path.name.lower()

        for pattern in self.SENSITIVE_PATTERNS:
            pattern_lower = pattern.lower()

            # 检查文件名包含敏感模式
            if pattern_lower in file_name:
                raise ToolExecutionError(
                    f"Access denied: sensitive file pattern '{pattern}' "
                    f"detected (REQ-CTX-005)"
                )

            # 检查路径包含敏感模式（如 .git/config）
            if "/" in pattern_lower and pattern_lower in path_str:
                raise ToolExecutionError(
                    f"Access denied: sensitive path pattern '{pattern}' "
                    f"detected (REQ-CTX-005)"
                )

    def _is_binary_file(self, path: Path) -> bool:
        """
        检测是否为二进制文件
        
        策略：读取前 8KB，检查是否包含空字节（\x00）
        """
        try:
            with open(path, "rb") as f:
                chunk = f.read(8192)
                return b"\x00" in chunk
        except Exception:
            # 读取失败时保守处理，视为二进制
            return True
