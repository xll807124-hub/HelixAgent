"""
Shell 工具集

对齐设计文档：REQ-HAR-003 Tool Adapter / REQ-SEC-004 沙箱隔离
"""
from .safe_shell import SafeShellTool

__all__ = ["SafeShellTool"]
