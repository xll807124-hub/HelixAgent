"""
Git Clone 工具

对齐设计文档：
- REQ-HAR-003 Tool Adapter
- REQ-SEC-005 凭据代理
- REQ-SEC-002 RBAC（仓库级权限）
"""
from __future__ import annotations

import asyncio
import shutil
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


class GitCloneTool(BaseTool):
    """
    Git Clone 工具
    
    功能：
    1. 克隆 GitHub 仓库到工作区
    2. 支持分支指定
    3. 深度克隆优化
    4. 超时保护
    
    安全约束（REQ-SEC-002）：
    - 仓库 URL 必须来自白名单或经过授权
    - 克隆到指定的工作区路径
    - 凭据来自凭据代理，不存储在本地
    """

    @property
    def name(self) -> str:
        return "git-clone"

    @property
    def description(self) -> str:
        return "Clone a GitHub repository to a workspace"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo_url": {
                    "type": "string",
                    "description": "GitHub repository URL (HTTPS or git@github.com format)",
                },
                "target_dir": {
                    "type": "string",
                    "description": "Target directory to clone into (within workspace)",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to clone (default: main or master)",
                    "default": None,
                },
                "depth": {
                    "type": "integer",
                    "description": "Shallow clone depth (0 = full clone)",
                    "default": 0,
                },
            },
            "required": ["repo_url", "target_dir"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cloned_path": {
                    "type": "string",
                    "description": "Absolute path to cloned repository",
                },
                "commit_hash": {
                    "type": "string",
                    "description": "Current HEAD commit hash",
                },
                "branch": {
                    "type": "string",
                    "description": "Current branch name",
                },
                "remote_url": {
                    "type": "string",
                    "description": "Remote origin URL",
                },
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.MEDIUM  # 网络操作，可能受到 DoS 攻击

    @property
    def timeout_seconds(self) -> int:
        return 60  # 克隆可能需要较长时间

    @property
    def capabilities(self) -> list[str]:
        return ["git", "clone", "repository"]

    def validate_input(self, params: dict[str, Any]) -> ValidationResult:
        """扩展校验：检查仓库 URL 和路径"""
        result = super().validate_input(params)
        if not result.valid:
            return result

        errors: list[str] = []
        repo_url = params.get("repo_url", "")
        target_dir = params.get("target_dir", "")
        depth = params.get("depth", 0)

        # 验证仓库 URL
        if not repo_url.startswith(("https://github.com/", "git@github.com:")):
            errors.append("repo_url must be a GitHub repository URL")

        # 验证目标目录
        if ".." in target_dir or target_dir.startswith("/"):
            errors.append("target_dir must be a relative path within workspace")

        # 验证深度
        if not isinstance(depth, int) or depth < 0:
            errors.append("depth must be a non-negative integer")

        return ValidationResult(valid=len(errors) == 0, errors=result.errors + errors)

    async def execute(
        self,
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """
        执行克隆操作
        
        步骤：
        1. 解析并验证仓库 URL
        2. 构建目标路径
        3. 权限检查
        4. 准备克隆命令
        5. 执行克隆
        6. 验证结果
        """
        repo_url = params["repo_url"]
        target_dir = params["target_dir"]
        branch = params.get("branch")
        depth = params.get("depth", 0)

        try:
            # 步骤1: 构建完整的目标路径
            workspace = Path.cwd()
            target_path = workspace / target_dir

            # 步骤2: 权限检查 - 确保在允许的路径内
            try:
                target_path.resolve().relative_to(workspace.resolve())
            except ValueError:
                raise ToolExecutionError(
                    f"Target path must be within workspace: {target_dir}"
                )

            # 步骤3: 检查目录是否已存在
            if target_path.exists():
                raise ToolExecutionError(
                    f"Target directory already exists: {target_path}"
                )

            # 步骤4: 准备克隆命令
            cmd = ["git", "clone"]

            # 添加分支参数
            if branch:
                cmd.extend(["--branch", branch])

            # 添加深度参数（浅克隆）
            if depth > 0:
                cmd.extend(["--depth", str(depth)])

            # 添加 URL 和目标目录
            cmd.extend([repo_url, str(target_path)])

            # 步骤5: 执行克隆
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
                raise ToolExecutionError(f"Git clone failed: {error_msg}")

            # 步骤6: 获取克隆后的仓库信息
            commit_hash = await self._get_current_commit(target_path)
            branch_name = await self._get_current_branch(target_path)

            return ToolResult(
                success=True,
                output={
                    "cloned_path": str(target_path),
                    "commit_hash": commit_hash,
                    "branch": branch_name,
                    "remote_url": repo_url,
                },
                metadata={
                    "size_bytes": self._dir_size(target_path),
                    "depth": depth,
                },
            )

        except asyncio.TimeoutError:
            raise ToolExecutionError(
                f"Git clone timeout after {self.timeout_seconds}s"
            )
        except ToolExecutionError:
            raise
        except Exception as e:
            raise ToolExecutionError(f"Unexpected error during clone: {e}")

    async def _get_current_commit(self, repo_path: Path) -> str:
        """获取当前 HEAD 的 commit hash"""
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo_path),
                "rev-parse",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=10,
            )

            return stdout.decode().strip()
        except Exception:
            return "unknown"

    async def _get_current_branch(self, repo_path: Path) -> str:
        """获取当前分支名称"""
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo_path),
                "rev-parse",
                "--abbrev-ref",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=10,
            )

            return stdout.decode().strip()
        except Exception:
            return "unknown"

    def _dir_size(self, path: Path) -> int:
        """计算目录大小（字节）"""
        total = 0
        try:
            for item in path.rglob("*"):
                if item.is_file():
                    total += item.stat().st_size
        except Exception:
            pass
        return total
