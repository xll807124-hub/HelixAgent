"""
Git Commit 工具

对齐设计文档：
- REQ-HAR-003 Tool Adapter
- REQ-SEC-002 身份验证
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


class GitCommitTool(BaseTool):
    """
    Git Commit 工具
    
    功能：
    1. 暂存文件
    2. 提交变更
    3. 支持自定义消息
    4. 作者信息来自 ExecutionContext
    """

    @property
    def name(self) -> str:
        return "git-commit"

    @property
    def description(self) -> str:
        return "Commit changes to a Git repository"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository",
                },
                "message": {
                    "type": "string",
                    "description": "Commit message",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files to commit (default: all staged)",
                },
                "all": {
                    "type": "boolean",
                    "description": "Stage all modified files before committing",
                    "default": False,
                },
            },
            "required": ["repo_path", "message"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "commit_hash": {
                    "type": "string",
                    "description": "Commit hash (SHA-1)",
                },
                "author": {
                    "type": "string",
                    "description": "Commit author",
                },
                "timestamp": {
                    "type": "string",
                    "description": "Commit timestamp",
                },
                "files_changed": {
                    "type": "integer",
                    "description": "Number of files changed",
                },
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH  # 修改 Git 历史

    @property
    def timeout_seconds(self) -> int:
        return 20

    @property
    def capabilities(self) -> list[str]:
        return ["git", "commit", "modify"]

    def validate_input(self, params: dict[str, Any]) -> ValidationResult:
        """验证输入参数"""
        result = super().validate_input(params)
        if not result.valid:
            return result

        errors: list[str] = []
        message = params.get("message", "")

        if not message or len(message) < 3:
            errors.append("Commit message must be at least 3 characters")

        if len(message) > 1000:
            errors.append("Commit message must not exceed 1000 characters")

        return ValidationResult(valid=len(errors) == 0, errors=result.errors + errors)

    async def execute(
        self,
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """执行提交"""
        repo_path = params["repo_path"]
        message = params["message"]
        files = params.get("files", [])
        all_modified = params.get("all", False)

        try:
            repo = Path(repo_path).resolve()
            if not (repo / ".git").exists():
                raise ToolExecutionError(f"Not a git repository: {repo_path}")

            # 配置提交人信息
            author_name = context.user_id or "Agent"
            author_email = f"{author_name}@ai-agent.local"

            # 设置 git 配置
            await self._set_git_config(repo, author_name, author_email)

            # 暂存文件
            if all_modified:
                await self._stage_all(repo)
            elif files:
                await self._stage_files(repo, files)

            # 执行提交
            commit_hash = await self._do_commit(repo, message)

            # 获取提交信息
            commit_info = await self._get_commit_info(repo, commit_hash)

            return ToolResult(
                success=True,
                output={
                    "commit_hash": commit_hash,
                    "author": f"{author_name} <{author_email}>",
                    "timestamp": commit_info.get("timestamp", ""),
                    "files_changed": commit_info.get("files_changed", 0),
                },
                metadata={
                    "message": message,
                },
            )

        except ToolExecutionError:
            raise
        except asyncio.TimeoutError:
            raise ToolExecutionError(
                f"Git commit timeout after {self.timeout_seconds}s"
            )
        except Exception as e:
            raise ToolExecutionError(f"Unexpected error: {e}")

    async def _set_git_config(self, repo: Path, name: str, email: str) -> None:
        """设置本地 git 配置"""
        for key, value in [("user.name", name), ("user.email", email)]:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo),
                "config",
                key,
                value,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            await asyncio.wait_for(
                process.communicate(),
                timeout=5,
            )

    async def _stage_all(self, repo: Path) -> None:
        """暂存所有修改"""
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo),
            "add",
            "-A",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=10,
        )

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise ToolExecutionError(f"Failed to stage files: {error_msg}")

    async def _stage_files(self, repo: Path, files: list[str]) -> None:
        """暂存指定文件"""
        cmd = ["git", "-C", str(repo), "add"]
        cmd.extend(files)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=10,
        )

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise ToolExecutionError(f"Failed to stage files: {error_msg}")

    async def _do_commit(self, repo: Path, message: str) -> str:
        """执行提交"""
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo),
            "commit",
            "-m",
            message,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=self.timeout_seconds,
        )

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise ToolExecutionError(f"Failed to commit: {error_msg}")

        # 获取提交的 hash
        commit_hash = await self._get_head_hash(repo)
        return commit_hash

    async def _get_head_hash(self, repo: Path) -> str:
        """获取 HEAD commit 的 hash"""
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo),
            "rev-parse",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
        )

        stdout, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=5,
        )

        return stdout.decode().strip()

    async def _get_commit_info(self, repo: Path, commit_hash: str) -> dict[str, Any]:
        """获取提交信息"""
        try:
            # 获取时间戳
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo),
                "log",
                "-1",
                "--format=%ai",
                commit_hash,
                stdout=asyncio.subprocess.PIPE,
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=5,
            )

            timestamp = stdout.decode().strip()

            # 获取修改的文件数
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo),
                "log",
                "-1",
                "--oneline",
                "--stat",
                commit_hash,
                stdout=asyncio.subprocess.PIPE,
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=5,
            )

            # 简单计数（最后一行包含 "X files changed"）
            lines = stdout.decode().split("\n")
            files_changed = len(lines) - 2  # 估算

            return {
                "timestamp": timestamp,
                "files_changed": max(files_changed, 0),
            }
        except Exception:
            return {"timestamp": "", "files_changed": 0}
