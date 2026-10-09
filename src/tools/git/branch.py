"""
Git Branch 工具

功能：创建、删除、切换分支
"""
from __future__ import annotations

from ..base import (
    ExecutionContext,
    RiskLevel,
    ToolResult,
    ValidationResult,
)
from .base import BaseGitTool


class GitBranchTool(BaseGitTool):
    """Git Branch 工具：创建、删除、切换分支"""

    @property
    def name(self) -> str:
        return "git-branch"

    @property
    def description(self) -> str:
        return "Create, delete, or switch Git branches"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Repository path"},
                "action": {
                    "type": "string",
                    "enum": ["create", "delete", "switch", "list"],
                    "description": "Branch action"
                },
                "branch_name": {"type": "string", "description": "Branch name"},
                "from_branch": {
                    "type": "string",
                    "default": "main",
                    "description": "Create from branch (for create action)"
                },
            },
            "required": ["repo_path", "action"],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "current_branch": {"type": "string"},
                "branches": {"type": "array", "items": {"type": "string"}},
                "action": {"type": "string"},
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.MEDIUM  # 分支操作有副作用但可逆

    async def validate_input(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ValidationResult:
        """验证输入参数"""
        errors = []

        if "repo_path" not in params or "action" not in params:
            errors.append("Missing required parameters: repo_path, action")
            return ValidationResult(valid=False, errors=errors)

        action = params.get("action")
        if action not in ["create", "delete", "switch", "list"]:
            errors.append("Invalid action")

        if action in ["create", "delete", "switch"] and "branch_name" not in params:
            errors.append(f"branch_name required for {action} action")

        # 路径安全检查
        valid, error = self._validate_repo_path(params.get("repo_path"), context)
        if not valid:
            errors.append(error)

        return ValidationResult(valid=not bool(errors), errors=errors)

    async def execute(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ToolResult:
        """执行分支操作"""
        try:
            repo_path = params.get("repo_path")
            action = params.get("action")
            branch_name = params.get("branch_name", "")
            from_branch = params.get("from_branch", "main")

            # 验证是否是 Git 仓库
            is_repo, error = self._validate_git_repo(repo_path)
            if not is_repo:
                return ToolResult(success=False, output=None, error=error)

            if action == "create":
                success, stdout, stderr = self._run_git_command(
                    repo_path,
                    ["checkout", "-b", branch_name, from_branch]
                )
                if not success:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Failed to create branch: {stderr}"
                    )
                msg = f"Created branch '{branch_name}' from '{from_branch}'"

            elif action == "delete":
                success, stdout, stderr = self._run_git_command(
                    repo_path,
                    ["branch", "-d", branch_name]
                )
                if not success:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Failed to delete branch: {stderr}"
                    )
                msg = f"Deleted branch '{branch_name}'"

            elif action == "switch":
                success, stdout, stderr = self._run_git_command(
                    repo_path,
                    ["checkout", branch_name]
                )
                if not success:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Failed to switch branch: {stderr}"
                    )
                msg = f"Switched to branch '{branch_name}'"

            elif action == "list":
                success, stdout, stderr = self._run_git_command(
                    repo_path,
                    ["branch", "-a"]
                )
                if not success:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Failed to list branches: {stderr}"
                    )
                branches = [b.strip() for b in stdout.split("\n") if b.strip()]
                return ToolResult(
                    success=True,
                    output={"branches": branches, "action": "list"},
                )

            # 获取当前分支
            _, current, _ = self._run_git_command(
                repo_path,
                ["rev-parse", "--abbrev-ref", "HEAD"]
            )

            return ToolResult(
                success=True,
                output={
                    "current_branch": current.strip(),
                    "action": action,
                    "message": msg,
                },
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Branch operation failed: {e}",
            )
