"""
工具模块导出

提供工具基础设施和具体工具实现：
- BaseTool: 工具基类
- ToolRegistry: 工具注册表
- ActionExecutor: Action 执行器
- ExecutionContext: 执行上下文
- RiskLevel: 风险级别枚举

具体工具：
- 文件操作：FileReadTool, FileWriteTool, FileSearchTool
- Git 操作：GitCloneTool, GitBranchTool, GitCommitTool, GitPullRequestTool
- 测试：PytestRunnerTool
- Shell：SafeShellTool
"""
from .base import (
    BaseTool,
    ExecutionContext,
    RiskLevel,
    ToolExecutionError,
    ToolResult,
    ValidationResult,
)
from .executor import ActionExecutionResult, ActionExecutor
from .registry import ToolRegistry, get_global_registry, reset_global_registry

# 文件工具
from .file.read import FileReadTool
from .file.write import FileWriteTool
from .file.search import FileSearchTool

# Git 工具
from .git.clone import GitCloneTool
from .git.branch import GitBranchTool
from .git.commit import GitCommitTool
from .git.pr import GitPullRequestTool

# 测试工具
from .test.pytest_runner import PytestRunnerTool

# Shell 工具
from .shell.safe_shell import SafeShellTool

__all__ = [
    # 基类和接口
    "BaseTool",
    "ExecutionContext",
    "ToolResult",
    "ValidationResult",

    # 枚举
    "RiskLevel",

    # 异常
    "ToolExecutionError",

    # 注册表
    "ToolRegistry",
    "get_global_registry",
    "reset_global_registry",

    # 执行器
    "ActionExecutor",
    "ActionExecutionResult",

    # 文件工具
    "FileReadTool",
    "FileWriteTool",
    "FileSearchTool",

    # Git 工具
    "GitCloneTool",
    "GitBranchTool",
    "GitCommitTool",
    "GitPullRequestTool",

    # 测试工具
    "PytestRunnerTool",

    # Shell 工具
    "SafeShellTool",
]
