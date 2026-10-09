"""
Pytest 测试运行工具

功能：运行 Python 单元测试
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..base import (
    BaseTool,
    ExecutionContext,
    RiskLevel,
    ToolResult,
    ValidationResult,
)


class PytestRunnerTool(BaseTool):
    """
    Pytest 测试运行工具
    
    功能：
    1. 运行 pytest 测试
    2. 过滤测试用例
    3. 收集测试结果
    4. 输出覆盖率报告
    """

    @property
    def name(self) -> str:
        return "pytest-run"

    @property
    def description(self) -> str:
        return "Run Python unit tests with pytest"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": "Path to test file or directory"
                },
                "pattern": {
                    "type": "string",
                    "default": "test_*.py",
                    "description": "Test file pattern"
                },
                "keywords": {
                    "type": "string",
                    "description": "Filter tests by keyword"
                },
                "verbose": {
                    "type": "boolean",
                    "default": False,
                    "description": "Verbose output"
                },
                "coverage": {
                    "type": "boolean",
                    "default": False,
                    "description": "Generate coverage report"
                },
                "timeout": {
                    "type": "integer",
                    "default": 300,
                    "description": "Test timeout in seconds"
                },
            },
            "required": ["test_path"],
        }

    @property
    def output_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "passed": {"type": "integer"},
                "failed": {"type": "integer"},
                "skipped": {"type": "integer"},
                "duration": {"type": "number"},
                "coverage_percent": {"type": "number"},
                "summary": {"type": "string"},
            },
        }

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.MEDIUM  # 执行代码但不修改系统

    async def validate_input(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ValidationResult:
        """验证输入参数"""
        errors = []

        if "test_path" not in params:
            errors.append("Missing required parameter: test_path")
            return ValidationResult(valid=False, errors=errors)

        test_path = params.get("test_path")
        if not isinstance(test_path, str):
            errors.append("test_path must be a string")

        # 检查路径是否存在
        try:
            path = Path(test_path).resolve()
            if not path.exists():
                errors.append(f"Test path does not exist: {test_path}")
        except (ValueError, RuntimeError) as e:
            errors.append(f"Invalid test_path: {e}")

        return ValidationResult(valid=not bool(errors), errors=errors)

    async def execute(
        self,
        params: dict,
        context: ExecutionContext,
    ) -> ToolResult:
        """执行 Pytest"""
        try:
            test_path = params.get("test_path")
            pattern = params.get("pattern", "test_*.py")
            keywords = params.get("keywords")
            verbose = params.get("verbose", False)
            coverage = params.get("coverage", False)
            timeout = params.get("timeout", 300)

            # 构建 pytest 命令
            cmd = ["python", "-m", "pytest", test_path]

            if keywords:
                cmd.extend(["-k", keywords])

            if verbose:
                cmd.append("-v")

            if coverage:
                cmd.extend(["--cov", "--cov-report=term-missing"])

            cmd.extend(["--tb=short", "-q"])

            # 执行测试
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(Path(test_path).parent if Path(test_path).is_file() else Path(test_path)),
            )

            # 解析输出
            output = result.stdout + result.stderr
            parsed = self._parse_pytest_output(output)

            return ToolResult(
                success=result.returncode == 0,
                output=parsed,
                metadata={
                    "command": " ".join(cmd),
                    "return_code": result.returncode,
                }
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output=None,
                error=f"Test execution timed out after {timeout}s",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Test execution failed: {e}",
            )

    @staticmethod
    def _parse_pytest_output(output: str) -> dict:
        """解析 pytest 输出"""
        result = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "duration": 0.0,
            "coverage_percent": 0.0,
            "summary": output.split("\n")[-2] if output else "",
        }

        # 简单的正则匹配提取关键信息
        import re

        # 提取测试统计
        match = re.search(r"(\d+) passed", output)
        if match:
            result["passed"] = int(match.group(1))

        match = re.search(r"(\d+) failed", output)
        if match:
            result["failed"] = int(match.group(1))

        match = re.search(r"(\d+) skipped", output)
        if match:
            result["skipped"] = int(match.group(1))

        # 提取执行时间
        match = re.search(r"in ([\d.]+)s", output)
        if match:
            result["duration"] = float(match.group(1))

        # 提取覆盖率
        match = re.search(r"TOTAL\s+(\d+)\s+(\d+)\s+([\d.]+)%", output)
        if match:
            result["coverage_percent"] = float(match.group(3))

        return result
