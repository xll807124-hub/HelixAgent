"""
Git Clone 工具

功能：克隆远程仓库到本地
"""
from __future__ import annotations

from pathlib import Path

from ..base import (
    ExecutionContext,
    RiskLevel,
    ToolResult,
    ValidationResult,
)
from .base import BaseGitTool


class GitCloneTool(BaseGitTool):
    """
    Git Clone 工具
    
    功能：
    1. 克隆远程 Git 仓库
    2. 支持深度克隆和完整克隆
    3. 路径安全性检查
    4. 超时控制
    """

    @property
    def name(self) -> str:
        return "git-clone"

    @property
    def description(self) -> str:
        return "Clone a remote Git repository"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo_url": {
                    "type": "string",
                    "description": "Remote repository URL (https or git+ssh)"
                },
                "target_path": {
                    "type": "string",
                    "description": "Target directory to clone into"
                },
                "branch": {
                    "type": "string",
                    "default": "main",
                    "description": "Branch to clone (default: main)"
                },
                "depth": {
                    "type": "integer",
                    "description": "Shallow clone depth (omit for full clone)"
                },
                "single_branch": {
                    "type": "boolean",
                    "default": True,
                    "description": "Clone only the target branch"
                },
            },
            "required": ["repo_url", "target_path"],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "branch": {"type": "string"},
                "commit": {"type": "string"},
                "cloned": {"type": "boolean"},
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH  # 下载和执行代码是高风险

    async def validate_input(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ValidationResult:
        """验证输入参数"""
        errors = []

        # 必填参数检查
        if "repo_url" not in params:
            errors.append("Missing required parameter: repo_url")
        if "target_path" not in params:
            errors.append("Missing required parameter: target_path")

        if errors:
            return ValidationResult(valid=False, errors=errors)

        repo_url = params.get("repo_url")
        target_path = params.get("target_path")
        branch = params.get("branch", "main")
        depth = params.get("depth")

        # 参数类型检查
        if not isinstance(repo_url, str):
            errors.append("repo_url must be a string")
        if not isinstance(target_path, str):
            errors.append("target_path must be a string")
        if not isinstance(branch, str):
            errors.append("branch must be a string")
        if depth is not None and (not isinstance(depth, int) or depth < 1):
            errors.append("depth must be a positive integer")

        # URL 验证
        if not self._is_valid_git_url(repo_url):
            errors.append("repo_url must be a valid Git URL")

        # 路径安全检查
        if errors:
            return ValidationResult(valid=False, errors=errors)

        valid, error = self._validate_repo_path(target_path, context)
        if not valid:
            errors.append(f"Invalid target_path: {error}")

        return ValidationResult(valid=not bool(errors), errors=errors)

    async def execute(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ToolResult:
        """执行 Git Clone"""
        try:
            repo_url = params.get("repo_url")
            target_path = params.get("target_path")
            branch = params.get("branch", "main")
            depth = params.get("depth")
            single_branch = params.get("single_branch", True)

            # 构建 Git 命令
            git_args = ["clone"]

            if depth:
                git_args.append(f"--depth={depth}")

            if single_branch:
                git_args.append("--single-branch")

            git_args.extend(["--branch", branch])
            git_args.extend([repo_url, target_path])

            # 执行克隆（在父目录中执行，以支持创建新目录）
            parent_path = str(Path(target_path).parent)
            success, stdout, stderr = self._run_git_command(
                parent_path,
                git_args,
                timeout=300,  # 克隆可能需要更长时间
            )

            if not success:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Failed to clone repository: {stderr}",
                )

            # 获取当前提交 SHA
            target_abs = Path(target_path).resolve()
            commit_success, commit_sha, _ = self._run_git_command(
                str(target_abs),
                ["rev-parse", "HEAD"],
            )

            return ToolResult(
                success=True,
                output={
                    "repo_path": str(target_abs),
                    "branch": branch,
                    "commit": commit_sha.strip() if commit_success else "unknown",
                    "cloned": True,
                },
                metadata={
                    "repo_url": repo_url,
                    "depth": depth,
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Clone failed: {e}",
            )

    @staticmethod
    def _is_valid_git_url(url: str) -> bool:
        """检查是否是有效的 Git URL"""
        return (
            url.startswith("https://") or
            url.startswith("http://") or
            url.startswith("git@") or
            url.startswith("git://")
        )
