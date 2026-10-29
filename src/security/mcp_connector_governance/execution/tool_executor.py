"""
Tool Executor

Executes MCP tool invocations with isolation and monitoring.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from ..models import Connector, ToolSchema
from ..policies import PolicyEngine

logger = logging.getLogger(__name__)


class ToolExecutionResult:
    """Result of a tool execution."""
    
    def __init__(
        self,
        success: bool,
        result: Any = None,
        error: str | None = None,
        execution_time_ms: float = 0.0,
        metadata: dict | None = None,
    ) -> None:
        self.success = success
        self.result = result
        self.error = error
        self.execution_time_ms = execution_time_ms
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


class ToolExecutor:
    """
    Executes MCP tool invocations.
    
    Responsibilities:
    - Pre-execution policy check
    - Tool invocation with timeout
    - Result validation
    - Error handling and quota refund
    """
    
    def __init__(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        self.policy_engine = policy_engine
    
    async def execute_tool(
        self,
        org_id: str,
        user_id: str,
        connector: Connector,
        tool: ToolSchema,
        parameters: dict[str, Any],
    ) -> ToolExecutionResult:
        """
        Execute a tool with full governance checks.
        
        Args:
            org_id: Organization ID
            user_id: User ID
            connector: Connector providing the tool
            tool: Tool to execute
            parameters: Tool parameters
            
        Returns:
            ToolExecutionResult
        """
        start_time = datetime.utcnow()
        
        # Step 1: Pre-execution policy check
        policy_decision = self.policy_engine.evaluate_tool_invocation(
            org_id=org_id,
            connector=connector,
            tool=tool,
            parameters=parameters,
        )
        
        if not policy_decision.allowed:
            logger.warning(
                f"Tool execution blocked by policy: {policy_decision.reason}",
                extra={
                    "org_id": org_id,
                    "connector_id": connector.connector_id,
                    "tool_name": tool.tool_name,
                }
            )
            return ToolExecutionResult(
                success=False,
                error=f"Policy check failed: {policy_decision.reason}",
                metadata={
                    "policy_decision": policy_decision.to_dict(),
                }
            )
        
        # Step 2: Consume quota
        quota_consumed = self.policy_engine.consume_quota_for_invocation(
            org_id=org_id,
            connector=connector,
            tool=tool,
        )
        
        if not quota_consumed:
            return ToolExecutionResult(
                success=False,
                error="Failed to consume quota",
            )
        
        # Step 3: Execute tool with timeout
        try:
            result = await self._execute_with_timeout(
                connector=connector,
                tool=tool,
                parameters=parameters,
            )
            
            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            return ToolExecutionResult(
                success=True,
                result=result,
                execution_time_ms=execution_time,
                metadata={
                    "policy_decision": policy_decision.to_dict(),
                    "quota_cost": policy_decision.quota_cost,
                }
            )
        
        except TimeoutError:
            logger.error(
                f"Tool execution timeout: {tool.tool_name}",
                extra={"connector_id": connector.connector_id}
            )
            
            # Refund quota on failure
            self.policy_engine.refund_quota_for_failed_invocation(
                org_id=org_id,
                connector=connector,
                tool=tool,
            )
            
            return ToolExecutionResult(
                success=False,
                error="Execution timeout",
            )
        
        except Exception as e:
            logger.error(
                f"Tool execution failed: {tool.tool_name}",
                extra={
                    "connector_id": connector.connector_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            
            # Refund quota on failure
            self.policy_engine.refund_quota_for_failed_invocation(
                org_id=org_id,
                connector=connector,
                tool=tool,
            )
            
            return ToolExecutionResult(
                success=False,
                error=f"Execution error: {str(e)}",
            )
    
    async def _execute_with_timeout(
        self,
        connector: Connector,
        tool: ToolSchema,
        parameters: dict[str, Any],
    ) -> Any:
        """
        Execute tool with timeout.
        
        Args:
            connector: Connector
            tool: Tool
            parameters: Tool parameters
            
        Returns:
            Tool execution result
        """
        timeout = tool.capability.max_execution_time_seconds
        
        # Create execution task
        task = self._invoke_tool(connector, tool, parameters)
        
        # Execute with timeout
        result = await asyncio.wait_for(task, timeout=timeout)
        
        return result
    
    async def _invoke_tool(
        self,
        connector: Connector,
        tool: ToolSchema,
        parameters: dict[str, Any],
    ) -> Any:
        """
        Actual tool invocation logic.
        
        This is where the MCP protocol communication happens.
        
        Args:
            connector: Connector
            tool: Tool
            parameters: Tool parameters
            
        Returns:
            Tool result
        """
        # TODO: Implement actual MCP protocol invocation
        # This would:
        # 1. Prepare MCP tools/call request
        # 2. Send to connector via transport (HTTP/STDIO)
        # 3. Parse and validate response
        # 4. Return result
        
        logger.info(
            f"Invoking tool {tool.tool_name} on connector {connector.connector_id}",
            extra={"parameters": parameters}
        )
        
        # Placeholder implementation
        await asyncio.sleep(0.1)  # Simulate network call
        
        return {
            "status": "success",
            "tool": tool.tool_name,
            "connector": connector.connector_id,
        }
