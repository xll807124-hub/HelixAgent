"""
Git Status 工具

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


class GitStatusTool(BaseTool):
    """
    Git Status 工具
    
    功能：
    1. 获取仓库状态
    2. 列出修改的文件
    3. 显示当前分支
    4. 检测未暂存的变更
    """

    @property
    def name(self) -> str:
        return "git-status"

    @property
    def description(self) -> str:
        return "Get the status of a Git repository"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository",
                },
                "porcelain": {
                    "type": "boolean",
                    "description": "Use porcelain format for machine-readable output",
                    "default": False,
                },
            },
            "required": ["repo_path"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "Current branch name",
                },
                "modified_files": {
                    "type": "array",
                    "description": "List of modified files",
                },
                "untracked_files": {
                    "type": "array",
                    "description": "List of untracked files",
                },
                "staged_files": {
                    "type": "array",
                    "description": "List of staged files",
                },
                "status_text": {
                    "type": "string",
                    "description": "Raw status output",
                },
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW  # 只读操作

    @property
    def timeout_seconds(self) -> int:
        return 10

    @property
    def capabilities(self) -> list[str]:
        return ["git", "status", "inspect"]

    def validate_input(self, params: dict[str, Any]) -> ValidationResult:
        """验证输入参数"""
        result = super().validate_input(params)
        if not result.valid:
            return result

        errors: list[str] = []
        repo_path = params.get("repo_path", "")

        if ".." in repo_path:
            errors.append("repo_path must not contain path traversal sequences")

        return ValidationResult(valid=len(errors) == 0, errors=result.errors + errors)

    async def execute(
        self,
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """执行 git status"""
        repo_path = params["repo_path"]
        porcelain = params.get("porcelain", False)

        try:
            # 验证路径
            repo = Path(repo_path).resolve()
            git_dir = repo / ".git"

            if not git_dir.exists():
                raise ToolExecutionError(f"Not a git repository: {repo_path}")

            # 构建命令
            cmd = ["git", "-C", str(repo), "status"]
            if porcelain:
                cmd.append("--porcelain")

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

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise ToolExecutionError(f"Git status failed: {error_msg}")

            status_text = stdout.decode()

            # 获取分支信息
            branch = await self._get_branch(repo)

            # 解析状态
            modified, untracked, staged = self._parse_status(status_text)

            return ToolResult(
                success=True,
                output={
                    "branch": branch,
                    "modified_files": modified,
                    "untracked_files": untracked,
                    "staged_files": staged,
                    "status_text": status_text,
                },
            )

        except ToolExecutionError:
            raise
        except TimeoutError as err:
            raise ToolExecutionError(f"Git status timeout after {self.timeout_seconds}s") from err
        except Exception as e:
            raise ToolExecutionError(f"Unexpected error: {e}") from e

    async def _get_branch(self, repo_path: Path) -> str:
        """获取当前分支"""
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo_path),
                "rev-parse",
                "--abbrev-ref",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=5,
            )

            return stdout.decode().strip()
        except Exception:
            return "unknown"

    def _parse_status(self, status_text: str) -> tuple[list[str], list[str], list[str]]:
        """解析 git status 输出"""
        modified: list[str] = []
        untracked: list[str] = []
        staged: list[str] = []

        for line in status_text.split("\n"):
            if not line.strip():
                continue

            # 简单解析（非 porcelain 格式）
            if "modified:" in line:
                file = line.split("modified:")[-1].strip()
                modified.append(file)
            elif "new file:" in line:
                file = line.split("new file:")[-1].strip()
                staged.append(file)
            elif "Untracked files:" in line:
                # 切换到 untracked 模式
                break

        return modified, untracked, staged
