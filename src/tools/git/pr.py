"""
Git PR 工具

对齐设计文档：
- REQ-HAR-003 Tool Adapter
- REQ-SEC-005 凭据代理（GitHub API token）
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


class GitPullRequestTool(BaseTool):
    """
    Git PR 工具
    
    功能：
    1. 创建 Pull Request
    2. 使用 GitHub API
    3. 支持自定义标题和描述
    """

    @property
    def name(self) -> str:
        return "git-pr"

    @property
    def description(self) -> str:
        return "Create a Pull Request on GitHub"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository",
                },
                "title": {
                    "type": "string",
                    "description": "Pull Request title",
                },
                "description": {
                    "type": "string",
                    "description": "Pull Request description",
                },
                "target_branch": {
                    "type": "string",
                    "description": "Target branch (default: main or master)",
                    "default": "main",
                },
                "source_branch": {
                    "type": "string",
                    "description": "Source branch (default: current branch)",
                },
                "draft": {
                    "type": "boolean",
                    "description": "Create as draft PR",
                    "default": False,
                },
            },
            "required": ["repo_path", "title"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pr_number": {
                    "type": "integer",
                    "description": "Pull Request number",
                },
                "pr_url": {
                    "type": "string",
                    "description": "Pull Request URL",
                },
                "status": {
                    "type": "string",
                    "description": "PR status (OPEN, DRAFT, etc.)",
                },
                "head_branch": {
                    "type": "string",
                },
                "base_branch": {
                    "type": "string",
                },
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH  # 创建 PR 是重要操作

    @property
    def timeout_seconds(self) -> int:
        return 30  # GitHub API 可能较慢

    @property
    def capabilities(self) -> list[str]:
        return ["git", "pr", "github", "create"]

    def validate_input(self, params: dict[str, Any]) -> ValidationResult:
        """验证输入参数"""
        result = super().validate_input(params)
        if not result.valid:
            return result

        errors: list[str] = []
        title = params.get("title", "")

        if len(title) < 5:
            errors.append("PR title must be at least 5 characters")

        if len(title) > 200:
            errors.append("PR title must not exceed 200 characters")

        return ValidationResult(valid=len(errors) == 0, errors=result.errors + errors)

    async def execute(
        self,
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """创建 PR"""
        repo_path = params["repo_path"]
        title = params["title"]
        description = params.get("description", "")
        target_branch = params.get("target_branch", "main")
        source_branch = params.get("source_branch")
        draft = params.get("draft", False)

        try:
            repo = Path(repo_path).resolve()
            if not (repo / ".git").exists():
                raise ToolExecutionError(f"Not a git repository: {repo_path}")

            # 获取远程信息
            repo_url = await self._get_remote_url(repo)
            if not repo_url:
                raise ToolExecutionError("No remote URL found")

            # 解析 GitHub 仓库信息
            owner, repo_name = self._parse_github_url(repo_url)
            if not owner or not repo_name:
                raise ToolExecutionError(f"Invalid GitHub URL: {repo_url}")

            # 获取当前分支（如果未指定）
            if not source_branch:
                source_branch = await self._get_current_branch(repo)

            # 获取 GitHub token（从凭据代理）
            token = await self._get_github_token(context)
            if not token:
                raise ToolExecutionError("No GitHub token available from credential proxy")

            # 创建 PR
            pr_data = await self._create_pr_via_api(
                owner,
                repo_name,
                title,
                description,
                source_branch,
                target_branch,
                draft,
                token,
            )

            return ToolResult(
                success=True,
                output={
                    "pr_number": pr_data.get("number"),
                    "pr_url": pr_data.get("html_url"),
                    "status": "DRAFT" if draft else "OPEN",
                    "head_branch": source_branch,
                    "base_branch": target_branch,
                },
                metadata={
                    "owner": owner,
                    "repo": repo_name,
                },
            )

        except ToolExecutionError:
            raise
        except TimeoutError as err:
            raise ToolExecutionError(f"GitHub API timeout after {self.timeout_seconds}s") from err
        except Exception as e:
            raise ToolExecutionError(f"Unexpected error: {e}") from e

    async def _get_remote_url(self, repo: Path) -> str:
        """获取 remote URL"""
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo),
                "config",
                "--get",
                "remote.origin.url",
                stdout=asyncio.subprocess.PIPE,
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=5,
            )

            return stdout.decode().strip()
        except Exception:
            return ""

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
            return "main"

    async def _get_github_token(self, context: ExecutionContext) -> str:
        """从凭据代理获取 GitHub token"""
        # 注：实际实现需要集成凭据代理
        # 这里为占位符，应该通过 context 获取
        # token = await context.credential_proxy.get_secret("github_token")
        return ""

    def _parse_github_url(self, url: str) -> tuple[str, str]:
        """解析 GitHub URL"""
        # 支持 HTTPS 和 SSH 格式
        if "https://github.com/" in url:
            parts = url.replace("https://github.com/", "").rstrip("/").split("/")
            if len(parts) >= 2:
                return parts[0], parts[1].replace(".git", "")
        elif "git@github.com:" in url:
            parts = url.replace("git@github.com:", "").rstrip("/").split("/")
            if len(parts) >= 2:
                return parts[0], parts[1].replace(".git", "")

        return "", ""

    async def _create_pr_via_api(
        self,
        owner: str,
        repo: str,
        title: str,
        description: str,
        head: str,
        base: str,
        draft: bool,
        token: str,
    ) -> dict[str, Any]:
        """通过 GitHub API 创建 PR"""
        # 注：实际实现需要发送 HTTP 请求到 GitHub API
        # 这里为占位符

        # 模拟 PR 响应
        return {
            "number": 1,
            "html_url": f"https://github.com/{owner}/{repo}/pull/1",
            "title": title,
            "head": {"ref": head},
            "base": {"ref": base},
            "draft": draft,
        }
