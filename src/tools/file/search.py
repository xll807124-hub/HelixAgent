"""
文件搜索工具

对齐设计文档：
- REQ-HAR-003 Tool Adapter
- REQ-CTX-001 代码索引和检索
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from ..base import (
    BaseTool,
    ExecutionContext,
    RiskLevel,
    ToolResult,
    ValidationResult,
)


class FileSearchTool(BaseTool):
    """
    文件搜索工具
    
    功能：
    1. 按文件名搜索（glob 模式）
    2. 按内容搜索（正则表达式）
    3. 结果过滤和限制
    4. 敏感文件排除
    
    安全约束：
    - 搜索范围限制在 allowed_paths
    - 敏感文件不返回
    - 结果数量限制
    """

    # 默认排除的目录
    EXCLUDED_DIRS = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        "dist",
        "build",
        "*.egg-info",
    }

    # 敏感文件模式
    SENSITIVE_PATTERNS = [
        ".env",
        ".env.*",
        "credentials",
        "secret",
        "token",
        "password",
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    ]

    @property
    def name(self) -> str:
        return "file-search"

    @property
    def description(self) -> str:
        return "Search for files by name or content pattern"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "search_path": {
                    "type": "string",
                    "description": "Directory to search in"
                },
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (filename glob or regex)"
                },
                "search_type": {
                    "type": "string",
                    "enum": ["filename", "content"],
                    "default": "filename",
                    "description": "Search by filename or file content"
                },
                "max_results": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum number of results"
                },
                "file_extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only search these file extensions (e.g., ['.py', '.js'])"
                },
                "case_sensitive": {
                    "type": "boolean",
                    "default": False,
                    "description": "Case sensitive search"
                },
            },
            "required": ["search_path", "pattern"],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "type": {"type": "string", "enum": ["file", "directory"]},
                            "size": {"type": "integer"},
                            "matches": {
                                "type": "array",
                                "description": "For content search: matched lines"
                            }
                        }
                    }
                },
                "total": {"type": "integer"},
                "truncated": {"type": "boolean"},
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW  # 只读操作

    def validate_input(  # type: ignore[override]
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ValidationResult:
        """验证输入参数"""
        errors = []

        # 必填参数检查
        if "search_path" not in params:
            errors.append("Missing required parameter: search_path")
        if "pattern" not in params:
            errors.append("Missing required parameter: pattern")

        if errors:
            return ValidationResult(valid=False, errors=errors)

        search_path = params.get("search_path")
        search_type = params.get("search_type", "filename")
        max_results = params.get("max_results", 100)

        # 参数类型检查
        if not isinstance(search_path, str):
            errors.append("search_path must be a string")
        if search_type not in ["filename", "content"]:
            errors.append("search_type must be 'filename' or 'content'")
        if not isinstance(max_results, int) or max_results < 1:
            errors.append("max_results must be a positive integer")

        # 路径安全性检查
        if errors:
            return ValidationResult(valid=False, errors=errors)

        # isinst检查通过后，search_path 实际是 str（mypy 不会自动 narrow 隐式 Any）
        search_path_str = cast(str, search_path)
        try:
            abs_path = Path(search_path_str).resolve()
        except (ValueError, RuntimeError) as e:
            errors.append(f"Invalid search_path: {e}")
            return ValidationResult(valid=False, errors=errors)

        # 权限检查
        if context.allowed_paths:
            allowed = False
            for allowed_path in context.allowed_paths:
                try:
                    abs_allowed = Path(allowed_path).resolve()
                    abs_path.relative_to(abs_allowed)
                    allowed = True
                    break
                except ValueError:
                    continue

            if not allowed:
                errors.append(
                    f"Search path not in allowed_paths: {context.allowed_paths}"
                )

        # 路径穿越检查
        if ".." in search_path_str:
            errors.append("Path traversal (..) not allowed")

        return ValidationResult(valid=not bool(errors), errors=errors)

    async def execute(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ToolResult:
        """执行文件搜索"""
        validation = self.validate_input(params, context)
        if not validation.valid:
            return ToolResult(success=False, output=None, error="; ".join(validation.errors))
        try:
            # validate_input 已保证以下字段类型正确（params: dict 显式 cast）
            search_path = cast(str, params.get("search_path"))
            pattern = cast(str, params.get("pattern"))
            search_type = cast(str, params.get("search_type", "filename"))
            max_results_raw = params.get("max_results", 100)
            file_extensions_raw = params.get("file_extensions", [])
            case_sensitive_raw = params.get("case_sensitive", False)
            # 标量收窄
            max_results = cast(int, max_results_raw)
            file_extensions = cast(list[str], file_extensions_raw)
            case_sensitive = cast(bool, case_sensitive_raw)

            abs_path = Path(search_path).resolve()

            if not abs_path.exists():
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Search path does not exist: {abs_path}",
                )

            if not abs_path.is_dir():
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Search path is not a directory: {abs_path}",
                )

            results: list[dict[str, Any]] = []

            if search_type == "filename":
                results = self._search_by_filename(
                    abs_path,
                    pattern,
                    file_extensions,
                    max_results,
                )
            elif search_type == "content":
                results = self._search_by_content(
                    abs_path,
                    pattern,
                    case_sensitive,
                    file_extensions,
                    max_results,
                )

            truncated = len(results) >= max_results

            return ToolResult(
                success=True,
                output={
                    "results": results[:max_results],
                    "total": len(results),
                    "truncated": truncated,
                },
                metadata={
                    "search_type": search_type,
                    "pattern": pattern,
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Search failed: {e}",
            )

    def _search_by_filename(
        self,
        root: Path,
        pattern: str,
        extensions: list[str],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """按文件名搜索"""
        results: list[dict[str, Any]] = []

        # 转换 glob 模式
        glob_pattern = f"**/*{pattern}*" if not pattern.startswith("*") else f"**/{pattern}"

        for match in root.glob(glob_pattern):
            if not self._safe_search_target(match, root):
                continue
            if self._should_exclude(match):
                continue

            # 文件扩展名过滤
            if extensions and match.suffix not in extensions:
                continue

            # 敏感文件过滤
            if self._is_sensitive_file(match):
                continue

            result = {
                "path": str(match.relative_to(root)),
                "type": "directory" if match.is_dir() else "file",
                "size": match.stat().st_size if match.is_file() else 0,
            }
            results.append(result)

            if len(results) >= max_results:
                break

        return results

    def _search_by_content(
        self,
        root: Path,
        pattern: str,
        case_sensitive: bool,
        extensions: list[str],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """按内容搜索"""
        results: list[dict[str, Any]] = []

        try:
            regex = re.compile(
                pattern,
                0 if case_sensitive else re.IGNORECASE,
            )
        except re.error:
            return results  # 返回空结果如果正则不有效

        for file_path in root.rglob("*"):
            if len(results) >= max_results:
                break

            if not file_path.is_file():
                continue

            if not self._safe_search_target(file_path, root):
                continue

            if self._should_exclude(file_path):
                continue

            # 扩展名过滤
            if extensions and file_path.suffix not in extensions:
                continue

            # 敏感文件过滤
            if self._is_sensitive_file(file_path):
                continue

            # 尝试读取文件内容
            try:
                with open(file_path, encoding="utf-8", errors="ignore") as f:
                    matches = []
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append({
                                "line": line_num,
                                "text": line.rstrip(),
                            })

                    if matches:
                        result = {
                            "path": str(file_path.relative_to(root)),
                            "type": "file",
                            "size": file_path.stat().st_size,
                            "matches": matches[:10],  # 限制每个文件的匹配行数
                        }
                        results.append(result)

            except OSError:
                continue  # 跳过无法读取的文件

        return results

    def _safe_search_target(self, path: Path, root: Path) -> bool:
        """Check the resolved target as well as the visible name before opening it."""
        try:
            resolved = path.resolve(strict=True)
            return (
                resolved.is_relative_to(root)
                and not self._should_exclude(resolved)
                and not self._is_sensitive_file(resolved)
            )
        except (OSError, ValueError, RuntimeError):
            return False

    def _should_exclude(self, path: Path) -> bool:
        """检查路径是否应该被排除"""
        for excluded in self.EXCLUDED_DIRS:
            if excluded.replace("*", "") in path.parts:
                return True
        return False

    def _is_sensitive_file(self, path: Path) -> bool:
        """检查是否是敏感文件"""
        name = path.name
        return any(
            pattern.replace("*", "") in name
            for pattern in self.SENSITIVE_PATTERNS
        )
