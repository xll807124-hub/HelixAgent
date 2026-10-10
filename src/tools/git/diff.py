"""
Git Diff 工具

对齐设计文档：
- REQ-HAR-003 Tool Adapter
"""
from __future__ import annotations

import asyncio
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


class GitDiffTool(BaseTool):
    """
    Git Diff 工具
    
    功能：
    1. 显示两个分支/commit 之间的差异
    2. 生成 diff 统计
    3. 支持文件过滤
    """

    @property
    def name(self) -> str:
        return "git-diff"

    @property
    def description(self) -> str:
        return "Show differences between Git branches or commits"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository",
                },
                "from_branch": {
                    "type": "string",
                    "description": "Source branch or commit (default: HEAD)",
                },
                "to_branch": {
                    "type": "string",
                    "description": "Target branch or commit (default: working tree)",
                },
                "stat": {
                    "type": "boolean",
                    "description": "Show statistics instead of full diff",
                    "default": False,
                },
                "file_filter": {
                    "type": "string",
                    "description": "Filter by file pattern (e.g., '*.py')",
                },
            },
            "required": ["repo_path"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "diff_content": {
                    "type": "string",
                    "description": "Diff content",
                },
                "stats": {
                    "type": "object",
                    "description": "Diff statistics",
                },
                "files_changed": {
                    "type": "integer",
                },
                "insertions": {
                    "type": "integer",
                },
                "deletions": {
                    "type": "integer",
                },
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW  # 只读操作

    @property
    def timeout_seconds(self) -> int:
        return 15

    @property
    def capabilities(self) -> list[str]:
        return ["git", "diff", "inspect"]

    def validate_input(self, params: dict[str, Any]) -> ValidationResult:
        """验证输入参数"""
        result = super().validate_input(params)
        if not result.valid:
            return result

        errors: list[str] = []

        # 可选验证
        from_branch = params.get("from_branch", "")
        if from_branch and ".." in from_branch:
            errors.append("from_branch contains invalid characters")

        return ValidationResult(valid=len(errors) == 0, errors=result.errors + errors)

    async def execute(
        self,
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """执行 diff"""
        repo_path = params["repo_path"]
        from_branch = params.get("from_branch", "HEAD")
        to_branch = params.get("to_branch", "")
        use_stat = params.get("stat", False)
        file_filter = params.get("file_filter", "")

        try:
            repo = Path(repo_path).resolve()
            if not (repo / ".git").exists():
                raise ToolExecutionError(f"Not a git repository: {repo_path}")

            # 构建命令
            cmd = ["git", "-C", str(repo), "diff"]

            if use_stat:
                cmd.append("--stat")

            cmd.append(from_branch)

            if to_branch:
                cmd.append(to_branch)

            if file_filter:
                cmd.append("--")
                cmd.append(file_filter)

            # 执行命令
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )

            if process.returncode != 0 and process.returncode != 1:  # 1 = 有差异
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise ToolExecutionError(f"Git diff failed: {error_msg}")

            diff_content = stdout.decode()

            # 解析统计
            stats = self._parse_diff_stats(diff_content)

            return ToolResult(
                success=True,
                output={
                    "diff_content": diff_content,
                    "stats": stats,
                    "files_changed": stats.get("files", 0),
                    "insertions": stats.get("insertions", 0),
                    "deletions": stats.get("deletions", 0),
                },
            )

        except ToolExecutionError:
            raise
        except asyncio.TimeoutError:
            raise ToolExecutionError(f"Git diff timeout after {self.timeout_seconds}s")
        except Exception as e:
            raise ToolExecutionError(f"Unexpected error: {e}")

    def _parse_diff_stats(self, diff_content: str) -> dict[str, int]:
        """解析 diff 统计"""
        stats = {
            "files": 0,
            "insertions": 0,
            "deletions": 0,
        }

        for line in diff_content.split("\n"):
            # 统计插入和删除
            if line.startswith("+") and not line.startswith("+++"):
                stats["insertions"] += 1
            elif line.startswith("-") and not line.startswith("---"):
                stats["deletions"] += 1
            # 统计文件变化
            elif line.startswith("diff --git"):
                stats["files"] += 1

        return stats
