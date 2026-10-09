"""
Git Pull Request 工具

功能：创建 Pull Request
"""
from __future__ import annotations

from ..base import (
    ExecutionContext,
    RiskLevel,
    ToolResult,
    ValidationResult,
)
from .base import BaseGitTool


class GitPullRequestTool(BaseGitTool):
    """Git Pull Request 工具：创建 PR"""

    @property
    def name(self) -> str:
        return "git-pull-request"

    @property
    def description(self) -> str:
        return "Create a Pull Request on GitHub"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Repository path"},
                "title": {"type": "string", "description": "PR title"},
                "description": {"type": "string", "description": "PR description"},
                "head_branch": {
                    "type": "string",
                    "description": "Source branch (current branch if omitted)"
                },
                "base_branch": {
                    "type": "string",
                    "default": "main",
                    "description": "Target branch (default: main)"
                },
                "draft": {
                    "type": "boolean",
                    "default": False,
                    "description": "Create as draft PR"
                },
            },
            "required": ["repo_path", "title", "description"],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pr_number": {"type": "integer"},
                "pr_url": {"type": "string"},
                "status": {"type": "string"},
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH  # 创建 PR 会影响团队协作流程

    async def validate_input(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ValidationResult:
        """验证输入参数"""
        errors = []

        for field in ["repo_path", "title", "description"]:
            if field not in params:
                errors.append(f"Missing required parameter: {field}")

        if errors:
            return ValidationResult(valid=False, errors=errors)

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
        """执行 Git Pull Request 创建"""
        try:
            repo_path = params.get("repo_path")
            title = params.get("title")
            description = params.get("description")
            head_branch = params.get("head_branch")
            base_branch = params.get("base_branch", "main")
            draft = params.get("draft", False)

            # 验证是否是 Git 仓库
            is_repo, error = self._validate_git_repo(repo_path)
            if not is_repo:
                return ToolResult(success=False, output=None, error=error)

            # 获取当前分支（如果未指定 head_branch）
            if not head_branch:
                _, head_branch, stderr = self._run_git_command(
                    repo_path,
                    ["rev-parse", "--abbrev-ref", "HEAD"]
                )
                if not head_branch:
                    return ToolResult(
                        success=False,
                        output=None,
                        error="Cannot determine current branch"
                    )
                head_branch = head_branch.strip()

            # 获取远程 origin
            _, origin_url, _ = self._run_git_command(
                repo_path,
                ["config", "--get", "remote.origin.url"]
            )

            if not origin_url:
                return ToolResult(
                    success=False,
                    output=None,
                    error="No remote origin configured"
                )

            origin_url = origin_url.strip()

            # 提取仓库信息
            repo_info = self._extract_repo_info(origin_url)
            if not repo_info:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Cannot extract repo info from: {origin_url}"
                )

            owner, repo = repo_info

            # 推送分支到远程（必要）
            success, _, stderr = self._run_git_command(
                repo_path,
                ["push", "-u", "origin", head_branch]
            )

            if not success and "already exists" not in stderr:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Failed to push branch: {stderr}"
                )

            # 注：实际的 PR 创建需要 GitHub API 集成
            # 这里返回模拟结果，后续需要集成 GitHub API
            pr_number = self._mock_pr_creation(owner, repo, head_branch, base_branch)
            pr_url = f"https://github.com/{owner}/{repo}/pull/{pr_number}"

            return ToolResult(
                success=True,
                output={
                    "pr_number": pr_number,
                    "pr_url": pr_url,
                    "status": "draft" if draft else "open",
                },
                metadata={
                    "owner": owner,
                    "repo": repo,
                    "head_branch": head_branch,
                    "base_branch": base_branch,
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"PR creation failed: {e}",
            )

    @staticmethod
    def _extract_repo_info(url: str) -> tuple[str, str] | None:
        """从 Git URL 提取所有者和仓库名"""
        # 支持 HTTPS 和 SSH 格式
        if url.startswith("https://github.com/"):
            parts = url.replace("https://github.com/", "").replace(".git", "").split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]
        elif url.startswith("git@github.com:"):
            parts = url.replace("git@github.com:", "").replace(".git", "").split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]
        return None

    @staticmethod
    def _mock_pr_creation(owner: str, repo: str, head: str, base: str) -> int:
        """模拟 PR 创建（待 GitHub API 集成）"""
        # TODO: 集成 GitHub API 进行真实 PR 创建
        import hashlib
        pr_hash = hashlib.md5(f"{owner}/{repo}/{head}/{base}".encode()).hexdigest()
        return int(pr_hash[:8], 16) % 100000
