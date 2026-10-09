"""
安全 Shell 工具

功能：在沙箱环境中执行受限命令
对齐设计文档：REQ-HAR-003 / REQ-SEC-004 沙箱隔离
"""
from __future__ import annotations

import subprocess

from ..base import (
    BaseTool,
    ExecutionContext,
    RiskLevel,
    ToolResult,
    ValidationResult,
)


class SafeShellTool(BaseTool):
    """
    安全 Shell 工具
    
    功能：
    1. 执行白名单命令
    2. 超时控制
    3. 输出大小限制
    4. 工作目录隔离
    
    安全约束：
    - 仅允许特定命令（白名单）
    - 禁止 shell 特殊字符（|, ;, &&, 等）
    - 工作目录必须在 allowed_paths
    - 输出大小限制
    """

    # 允许的命令白名单
    ALLOWED_COMMANDS = {
        # 文件相关
        "ls", "pwd", "cat", "head", "tail", "wc", "diff",
        # 搜索
        "grep", "find",
        # 编译/构建
        "make", "gcc", "python", "pip", "npm", "yarn",
        # 版本控制
        "git",
        # 系统
        "echo", "date", "whoami",
    }

    # 禁止的字符（防止注入）
    DANGEROUS_CHARS = {"|", ";", "&", "`", "$", "(", ")", "<", ">", "\n", "\r"}

    @property
    def name(self) -> str:
        return "safe-shell"

    @property
    def description(self) -> str:
        return "Execute whitelisted shell commands safely"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command to execute (e.g., 'python -m pytest')"
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory"
                },
                "timeout": {
                    "type": "integer",
                    "default": 60,
                    "description": "Command timeout in seconds"
                },
                "env": {
                    "type": "object",
                    "description": "Environment variables (limited subset)"
                },
            },
            "required": ["command", "cwd"],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "return_code": {"type": "integer"},
                "duration": {"type": "number"},
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH  # 命令执行总是高风险

    async def validate_input(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ValidationResult:
        """验证输入参数"""
        errors = []

        if "command" not in params or "cwd" not in params:
            errors.append("Missing required parameters: command, cwd")
            return ValidationResult(valid=False, errors=errors)

        command = params.get("command", "")

        # 命令白名单检查
        cmd_parts = command.split()
        if not cmd_parts:
            errors.append("Empty command")
            return ValidationResult(valid=False, errors=errors)

        base_cmd = cmd_parts[0]
        if base_cmd not in self.ALLOWED_COMMANDS:
            errors.append(f"Command not in whitelist: {base_cmd}")

        # 危险字符检查（防止注入）
        for char in self.DANGEROUS_CHARS:
            if char in command:
                # 允许在引号中的某些字符
                if not self._is_quoted_char(command, char):
                    errors.append(f"Dangerous character not allowed: '{char}'")
                    break

        # 工作目录权限检查
        cwd = params.get("cwd")
        if context.allowed_paths:
            allowed = False
            for allowed_path in context.allowed_paths:
                if str(cwd).startswith(str(allowed_path)):
                    allowed = True
                    break
            if not allowed:
                errors.append(f"Working directory not in allowed_paths: {cwd}")

        return ValidationResult(valid=not bool(errors), errors=errors)

    async def execute(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ToolResult:
        """执行命令"""
        try:
            command = params.get("command", "")
            cwd = params.get("cwd")
            timeout = params.get("timeout", 60)
            env_vars = params.get("env", {})

            # 限制环境变量（仅允许安全的变量）
            safe_env = self._filter_env(env_vars)

            import time
            start = time.time()

            # 执行命令（使用数组形式，避免 shell 解析）
            cmd_args = command.split()
            result = subprocess.run(
                cmd_args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=safe_env,
            )

            duration = time.time() - start

            # 限制输出大小（防止输出溢出）
            stdout = result.stdout[:10 * 1024]  # 10KB
            stderr = result.stderr[:10 * 1024]  # 10KB

            return ToolResult(
                success=result.returncode == 0,
                output={
                    "stdout": stdout,
                    "stderr": stderr,
                    "return_code": result.returncode,
                    "duration": duration,
                },
                metadata={
                    "command": command,
                    "timeout": timeout,
                    "truncated": len(result.stdout) > 10 * 1024,
                }
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output=None,
                error=f"Command timed out after {timeout}s",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Command execution failed: {e}",
            )

    @staticmethod
    def _is_quoted_char(text: str, char: str) -> bool:
        """检查字符是否在引号内"""
        in_single = False
        in_double = False

        for i, c in enumerate(text):
            if c == "'" and (i == 0 or text[i-1] != "\\"):
                in_single = not in_single
            elif c == '"' and (i == 0 or text[i-1] != "\\"):
                in_double = not in_double
            elif c == char and (in_single or in_double):
                return True

        return False

    @staticmethod
    def _filter_env(env: dict) -> dict:
        """过滤环保险全的环境变量"""
        # 允许的环境变量前缀
        ALLOWED_ENV_PREFIXES = {
            "PYTHON", "PATH", "HOME", "USER", "LANG", "LC_",
            "HTTP_", "HTTPS_", "GIT_",
        }

        filtered = {}
        for key, value in env.items():
            if any(key.startswith(prefix) for prefix in ALLOWED_ENV_PREFIXES):
                if isinstance(value, str) and len(value) < 1024:  # 限制长度
                    filtered[key] = value

        return filtered
