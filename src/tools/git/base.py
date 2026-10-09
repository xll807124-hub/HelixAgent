"""
Git 工具基类

提供 Git 操作的公共功能
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..base import (
    BaseTool,
    ExecutionContext,
)


class BaseGitTool(BaseTool):
    """
    Git 工具基类
    
    提供公共 Git 命令执行和错误处理
    """

    @staticmethod
    def _run_git_command(
        cwd: str,
        args: list[str],
        timeout: int = 30,
    ) -> tuple[bool, str, str]:
        """
        执行 Git 命令
        
        Args:
            cwd: 工作目录
            args: Git 命令参数
            timeout: 超时时间（秒）
            
        Returns:
            (success, stdout, stderr)
        """
        try:
            cmd = ["git"] + args
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return (
                result.returncode == 0,
                result.stdout,
                result.stderr,
            )
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)

    def _validate_git_repo(self, path: str) -> tuple[bool, str]:
        """
        验证是否是 Git 仓库
        
        Returns:
            (is_git_repo, error_message)
        """
        success, _, stderr = self._run_git_command(path, ["rev-parse", "--git-dir"])
        if not success:
            return False, f"Not a git repository: {stderr}"
        return True, ""

    def _validate_repo_path(
        self,
        path: str,
        context: ExecutionContext,
    ) -> tuple[bool, str]:
        """
        验证仓库路径安全性
        
        Returns:
            (valid, error_message)
        """
        try:
            abs_path = Path(path).resolve()
        except (ValueError, RuntimeError) as e:
            return False, f"Invalid path: {e}"

        # 路径穿越检查
        if ".." in path:
            return False, "Path traversal (..) not allowed"

        # 权限检查
        if context.allowed_paths:
            allowed = False
            for allowed_path in context.allowed_paths:
                try:
                    abs_allowed = Path(allowed_path).resolve()
                    abs_path.relative_to(abs_allowed)
                    allowed = True
                    break
                except ValueError:
                    continue

            if not allowed:
                return False, f"Path not in allowed_paths: {context.allowed_paths}"

        return True, ""
