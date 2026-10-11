"""
Git Branch 工具

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


class GitBranchTool(BaseTool):
    """
    Git Branch 工具
    
    功能：
    1. 创建分支
    2. 切换分支
    3. 删除分支
    4. 列出分支
    """

    @property
    def name(self) -> str:
        return "git-branch"

    @property
    def description(self) -> str:
        return "Manage Git branches (create, switch, delete, list)"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository",
                },
                "action": {
                    "type": "string",
                    "enum": ["create", "switch", "delete", "list"],
                    "description": "Branch action to perform",
                },
                "branch_name": {
                    "type": "string",
                    "description": "Branch name (required for create/switch/delete)",
                },
                "from_branch": {
                    "type": "string",
                    "description": "Source branch for create action (default: current)",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force delete branch (only for delete action)",
                    "default": False,
                },
            },
            "required": ["repo_path", "action"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                },
                "current_branch": {
                    "type": "string",
                    "description": "Current branch after operation",
                },
                "all_branches": {
                    "type": "array",
                    "description": "List of all branches",
                },
                "message": {
                    "type": "string",
                },
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.MEDIUM  # 修改仓库状态

    @property
    def timeout_seconds(self) -> int:
        return 10

    @property
    def capabilities(self) -> list[str]:
        return ["git", "branch", "manage"]

    def validate_input(self, params: dict[str, Any]) -> ValidationResult:
        """验证输入参数"""
        result = super().validate_input(params)
        if not result.valid:
            return result

        errors: list[str] = []
        action = params.get("action", "")
        branch_name = params.get("branch_name", "")

        # 校验分支名称
        if action in ["create", "switch", "delete"]:
            if not branch_name:
                errors.append(f"{action} action requires branch_name")
            elif not self._is_valid_branch_name(branch_name):
                errors.append(f"Invalid branch name: {branch_name}")

        return ValidationResult(valid=len(errors) == 0, errors=result.errors + errors)

    async def execute(
        self,
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """执行分支操作"""
        repo_path = params["repo_path"]
        action = params["action"]
        branch_name = params.get("branch_name", "")
        from_branch = params.get("from_branch")
        force = params.get("force", False)

        try:
            repo = Path(repo_path).resolve()
            if not (repo / ".git").exists():
                raise ToolExecutionError(f"Not a git repository: {repo_path}")

            if action == "create":
                await self._create_branch(repo, branch_name, from_branch)
            elif action == "switch":
                await self._switch_branch(repo, branch_name)
            elif action == "delete":
                await self._delete_branch(repo, branch_name, force)
            elif action == "list":
                pass  # 无需执行，在下面获取列表

            current_branch = await self._get_current_branch(repo)
            all_branches = await self._list_branches(repo)

            return ToolResult(
                success=True,
                output={
                    "success": True,
                    "current_branch": current_branch,
                    "all_branches": all_branches,
                    "message": f"Branch {action} completed",
                },
            )

        except ToolExecutionError:
            raise
        except TimeoutError as err:
            raise ToolExecutionError(
                f"Git branch operation timeout after {self.timeout_seconds}s"
            ) from err
        except Exception as e:
            raise ToolExecutionError(f"Unexpected error: {e}") from e

    async def _create_branch(
        self, repo: Path, branch_name: str, from_branch: str | None = None
    ) -> None:
        """创建分支"""
        cmd = ["git", "-C", str(repo), "branch", branch_name]
        if from_branch:
            cmd.append(from_branch)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=self.timeout_seconds,
        )

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise ToolExecutionError(f"Failed to create branch: {error_msg}")

    async def _switch_branch(self, repo: Path, branch_name: str) -> None:
        """切换分支"""
        cmd = ["git", "-C", str(repo), "checkout", branch_name]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=self.timeout_seconds,
        )

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise ToolExecutionError(f"Failed to switch branch: {error_msg}")

    async def _delete_branch(self, repo: Path, branch_name: str, force: bool) -> None:
        """删除分支"""
        cmd = ["git", "-C", str(repo), "branch"]
        if force:
            cmd.append("-D")
        else:
            cmd.append("-d")
        cmd.append(branch_name)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=self.timeout_seconds,
        )

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise ToolExecutionError(f"Failed to delete branch: {error_msg}")

    async def _get_current_branch(self, repo: Path) -> str:
        """获取当前分支"""
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo),
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

    async def _list_branches(self, repo: Path) -> list[str]:
        """列出所有分支"""
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo),
                "branch",
                "-a",
                stdout=asyncio.subprocess.PIPE,
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=5,
            )

            lines = stdout.decode().split("\n")
            branches = [line.strip("* ").strip() for line in lines if line.strip()]
            return branches
        except Exception:
            return []

    def _is_valid_branch_name(self, name: str) -> bool:
        """验证分支名称的有效性"""
        # 简单的验证规则
        if not name:
            return False
        if name.startswith("-"):
            return False
        if name.endswith(".lock"):
            return False
        if any(c in name for c in ["...", " ", "\t", "\n"]):
            return False
        return True
