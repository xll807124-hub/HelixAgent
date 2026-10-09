"""
Git Commit 工具

功能：提交代码变更
"""
from __future__ import annotations

from ..base import (
    ExecutionContext,
    RiskLevel,
    ToolResult,
    ValidationResult,
)
from .base import BaseGitTool


class GitCommitTool(BaseGitTool):
    """Git Commit 工具：暂存和提交变更"""

    @property
    def name(self) -> str:
        return "git-commit"

    @property
    def description(self) -> str:
        return "Stage and commit changes to Git"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Repository path"},
                "message": {"type": "string", "description": "Commit message"},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["."],
                    "description": "Files to stage (. for all)"
                },
                "author_name": {"type": "string", "description": "Author name"},
                "author_email": {"type": "string", "description": "Author email"},
                "allow_empty": {
                    "type": "boolean",
                    "default": False,
                    "description": "Allow empty commit"
                },
            },
            "required": ["repo_path", "message", "author_name", "author_email"],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "commit_sha": {"type": "string"},
                "message": {"type": "string"},
                "changed_files": {"type": "integer"},
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH  # 修改版本历史

    async def validate_input(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ValidationResult:
        """验证输入参数"""
        errors = []

        for field in ["repo_path", "message", "author_name", "author_email"]:
            if field not in params:
                errors.append(f"Missing required parameter: {field}")

        if errors:
            return ValidationResult(valid=False, errors=errors)

        # 路径安全检查
        valid, error = self._validate_repo_path(params.get("repo_path"), context)
        if not valid:
            errors.append(error)

        # 邮箱格式检查
        email = params.get("author_email", "")
        if "@" not in email:
            errors.append("Invalid author email format")

        return ValidationResult(valid=not bool(errors), errors=errors)

    async def execute(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ToolResult:
        """执行 Git Commit"""
        try:
            repo_path = params.get("repo_path")
            message = params.get("message")
            files = params.get("files", ["."])
            author_name = params.get("author_name")
            author_email = params.get("author_email")
            allow_empty = params.get("allow_empty", False)

            # 验证是否是 Git 仓库
            is_repo, error = self._validate_git_repo(repo_path)
            if not is_repo:
                return ToolResult(success=False, output=None, error=error)

            # 配置 Git 用户（如果需要）
            for cmd in [
                ["config", "user.name", author_name],
                ["config", "user.email", author_email],
            ]:
                self._run_git_command(repo_path, cmd)

            # 暂存文件
            success, _, stderr = self._run_git_command(
                repo_path,
                ["add"] + files
            )
            if not success:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Failed to stage files: {stderr}"
                )

            # 获取 diff 统计
            _, diff_stat, _ = self._run_git_command(
                repo_path,
                ["diff", "--cached", "--numstat"]
            )
            changed_files = len([l for l in diff_stat.split("\n") if l.strip()])

            # 提交
            commit_args = ["commit", "-m", message]
            if allow_empty:
                commit_args.append("--allow-empty")

            success, stdout, stderr = self._run_git_command(
                repo_path,
                commit_args
            )

            if not success:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Failed to commit: {stderr}"
                )

            # 获取提交 SHA
            _, commit_sha, _ = self._run_git_command(
                repo_path,
                ["rev-parse", "HEAD"]
            )

            return ToolResult(
                success=True,
                output={
                    "commit_sha": commit_sha.strip(),
                    "message": message,
                    "changed_files": changed_files,
                },
                metadata={"author": f"{author_name} <{author_email}>"}
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Commit failed: {e}",
            )
