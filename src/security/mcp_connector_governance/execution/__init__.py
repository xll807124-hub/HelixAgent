"""
Execution Module

Tool execution with governance checks and monitoring.

The package exports the v2 executor (real STDIO/HTTP transports, signature
gate, policy check, quota refund, audit). The legacy `tool_executor.py`
simulated calls with asyncio.sleep and is no longer exported.
"""

from .tool_executor_v2 import ToolExecutionResult, ToolExecutor

__all__ = [
    "ToolExecutor",
    "ToolExecutionResult",
]
