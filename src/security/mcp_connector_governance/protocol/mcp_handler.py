"""
SEC-007: MCP Protocol Implementation
MCP tools/list 和 tools/call 协议处理

参考：
- https://spec.modelcontextprotocol.io/latest/
- tools/list (发现工具)
- tools/call (调用工具)
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..audit import AuditLogger
from ..execution.tool_executor import ToolExecutor as LegacyToolExecutor
from ..execution.tool_executor_v2 import ToolExecutor
from ..models import Connector, ToolSchema
from ..policies.capability_trimmer import (
    resolve_trims,
    trim_tool_schema,
    validate_call,
)
from ..policies.policy_engine import PolicyEngine
from ..registry.connector_registry import ConnectorRegistry
from ..registry.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class MCPErrorCode(Enum):
    """MCP 错误代码"""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SERVER_ERROR = -32000
    TOOL_NOT_FOUND = -32050
    TOOL_EXECUTION_FAILED = -32051
    TOOL_EXECUTION_TIMEOUT = -32052


@dataclass
class MCPError:
    """MCP 错误响应"""

    code: int
    message: str
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.data:
            result["data"] = self.data
        return result


@dataclass
class MCPRequest:
    """MCP 请求"""

    jsonrpc: str = "2.0"
    method: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    id: str | int | None = None

    def __post_init__(self) -> None:
        if self.params is None:
            self.params = {}


@dataclass
class MCPResponse:
    """MCP 响应"""

    jsonrpc: str = "2.0"
    result: dict[str, Any] | None = None
    error: MCPError | None = None
    id: str | int | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
        }

        if self.error:
            result["error"] = self.error.to_dict()
        else:
            result["result"] = self.result or {}

        return result


class ToolInfo:
    """工具信息 (tools/list 响应)"""

    def __init__(
        self,
        name: str,
        description: str,
        inputSchema: dict[str, Any],
    ) -> None:
        self.name = name
        self.description = description
        self.inputSchema = inputSchema

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema,
        }


class ToolListResponse:
    """tools/list 响应"""

    def __init__(self, tools: list[ToolInfo]) -> None:
        self.tools = tools

    def to_dict(self) -> dict[str, Any]:
        return {"tools": [tool.to_dict() for tool in self.tools]}


class ToolCallResponse:
    """tools/call 响应"""

    def __init__(
        self,
        tool_name: str,
        result: Any = None,
        error: str | None = None,
        is_error: bool = False,
    ) -> None:
        self.tool_name = tool_name
        self.result = result
        self.error = error
        self.is_error = is_error

    def to_dict(self) -> dict[str, Any]:
        content = {
            "type": "text" if not self.is_error else "error",
        }

        if self.is_error:
            content["text"] = self.error or "Unknown error"
        else:
            content["text"] = (
                json.dumps(self.result) if not isinstance(self.result, str) else self.result
            )

        return {
            "type": "tool_result",
            "tool_use_id": self.tool_name,
            "content": [content],
            "is_error": self.is_error,
        }


class MCPProtocolHandler:
    """
    MCP 协议处理器

    处理 JSON-RPC 2.0 请求并返回响应
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        policy_engine: PolicyEngine,
        tool_executor: ToolExecutor | LegacyToolExecutor,
        connector_registry: ConnectorRegistry | None = None,
    ) -> None:
        """
        初始化协议处理器

        Args:
            tool_registry: 工具注册表
            policy_engine: 策略引擎
            tool_executor: 工具执行器
            connector_registry: 连接器注册表 (可选; 用于命名空间黑名单与 tools/call)
        """
        self.tool_registry = tool_registry
        self.policy_engine = policy_engine
        self.tool_executor = tool_executor
        self.connector_registry = connector_registry
        self.audit_logger = (
            tool_executor.audit_logger if isinstance(tool_executor, ToolExecutor) else AuditLogger()
        )
        if connector_registry is not None:
            tool_registry.bind_governance(connector_registry, audit_logger=self.audit_logger)
        if isinstance(tool_executor, ToolExecutor):
            if (tool_executor.tool_registry is not None
                    and tool_executor.tool_registry is not tool_registry):
                raise ValueError("Executor and protocol must share tool registry")
            tool_executor.tool_registry = tool_registry

    async def handle_request(
        self,
        request_json: str,
        org_id: str,
        user_id: str,
    ) -> str:
        """
        处理 MCP 请求

        Args:
            request_json: JSON-RPC 请求字符串
            org_id: 组织 ID
            user_id: 用户 ID

        Returns:
            JSON-RPC 响应字符串
        """
        try:
            # 解析请求
            request_data = json.loads(request_json)
        except json.JSONDecodeError:
            return json.dumps(
                MCPResponse(
                    error=MCPError(
                        code=MCPErrorCode.PARSE_ERROR.value,
                        message="Invalid JSON",
                    )
                ).to_dict()
            )

        if (
            not isinstance(request_data, dict)
            or request_data.get("jsonrpc") != "2.0"
            or not isinstance(request_data.get("method"), str)
            or not request_data["method"]
            or (request_data.get("id") is not None and type(request_data["id"]) not in (str, int))
        ):
            return json.dumps(
                MCPResponse(
                    error=MCPError(
                        code=MCPErrorCode.INVALID_REQUEST.value,
                        message="Invalid request",
                    )
                ).to_dict()
            )

        if not isinstance(request_data.get("params", {}), dict):
            return json.dumps(
                MCPResponse(
                    id=request_data.get("id"),
                    error=MCPError(
                        code=MCPErrorCode.INVALID_PARAMS.value,
                        message="params must be an object",
                    ),
                ).to_dict()
            )

        request = MCPRequest(
            method=request_data["method"],
            params=request_data.get("params", {}),
            id=request_data.get("id"),
        )
        try:
            # 路由处理
            if request.method == "tools/list":
                response = await self._handle_tools_list(org_id)
            elif request.method == "tools/call":
                response = await self._handle_tools_call(
                    request.params,
                    org_id,
                    user_id,
                )
            else:
                response = MCPResponse(
                    id=request.id,
                    error=MCPError(
                        code=MCPErrorCode.METHOD_NOT_FOUND.value,
                        message=f"Method not found: {request.method}",
                    ),
                )

            # 设置 request ID
            response.id = request.id

            return json.dumps(response.to_dict())

        except Exception as e:
            logger.error(f"Unexpected error in MCP handler: {str(e)}", exc_info=True)
            error_response = MCPResponse(
                id=request.id,
                error=MCPError(
                    code=MCPErrorCode.INTERNAL_ERROR.value,
                    message="Internal error",
                ),
            )
            return json.dumps(error_response.to_dict())

    async def _handle_tools_list(self, org_id: str) -> MCPResponse:
        """
        处理 tools/list 请求

        Returns:
            工具列表 (带能力裁剪)
        """
        try:
            if self.connector_registry is None:
                return MCPResponse(error=MCPError(
                    code=MCPErrorCode.INTERNAL_ERROR.value,
                    message="Connector registry not configured",
                ))
            # 获取所有可用工具
            all_tool_names = self.tool_registry.list_tools()

            # 应用组织策略 (能力裁剪)
            filtered_tools = []
            for tool_name in all_tool_names:
                # 全局黑名单: 工具名被封禁则不对外暴露
                blacklist = self.policy_engine.global_blacklist
                if blacklist.is_tool_blocked(tool_name):
                    continue

                # 应用组织白名单/裁剪
                trimmed_tool = self._apply_capability_trim(tool_name, org_id)
                if trimmed_tool:
                    filtered_tools.append(trimmed_tool)

            # 构建响应
            tool_infos = [
                ToolInfo(
                    name=tool.tool_name,
                    description=tool.description,
                    inputSchema=tool.input_schema.to_dict(),
                )
                for tool in filtered_tools
            ]

            response_data = ToolListResponse(tool_infos).to_dict()

            logger.info(
                f"tools/list returned {len(filtered_tools)} tools", extra={"org_id": org_id}
            )

            return MCPResponse(result=response_data)

        except Exception as e:
            # 注册表/策略错误可能含端点或凭据；只记录异常类型，拒绝全量回退。
            logger.error("Error in tools/list: %s", type(e).__name__)
            return MCPResponse(
                error=MCPError(
                    code=MCPErrorCode.INTERNAL_ERROR.value,
                    message="Failed to list tools",
                )
            )

    async def _handle_tools_call(
        self,
        params: dict[str, Any],
        org_id: str,
        user_id: str,
    ) -> MCPResponse:
        """
        处理 tools/call 请求

        Args:
            params: 请求参数 {"name": "tool_name", "arguments": {...}}
            org_id: 组织 ID
            user_id: 用户 ID

        Returns:
            工具执行结果
        """
        try:
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if not isinstance(tool_name, str) or not tool_name or not isinstance(arguments, dict):
                return MCPResponse(
                    error=MCPError(
                        code=MCPErrorCode.INVALID_PARAMS.value,
                        message="name must be a nonempty string and arguments must be an object",
                    )
                )

            # 解析工具标识 (格式: connector_id:tool_name)
            if ":" not in tool_name:
                return MCPResponse(
                    error=MCPError(
                        code=MCPErrorCode.TOOL_NOT_FOUND.value,
                        message=f"Invalid tool name format: {tool_name}",
                    )
                )

            connector_id, actual_tool_name = tool_name.split(":", 1)

            def unavailable() -> MCPResponse:
                # 提前拒绝也保留既有决策审计；外部错误仍不区分未知和禁用目标。
                self.audit_logger.log_policy_decision(
                    connector_id, actual_tool_name, user_id, org_id,
                    "denied", "Tool unavailable", "availability",
                )
                return self._tool_unavailable()

            # 查找连接器和工具
            if self.connector_registry is None:
                return MCPResponse(
                    error=MCPError(
                        code=MCPErrorCode.INTERNAL_ERROR.value,
                        message="Connector registry not configured",
                    )
                )

            # 发现结果不是授权事实。旧名称和自定义执行器也必须经过入口门禁。
            if self.policy_engine.global_blacklist.is_tool_blocked(actual_tool_name):
                return unavailable()
            connector = self._available_connector(connector_id, org_id)
            if connector is None:
                return unavailable()

            # 只允许调用该连接器自己提供的工具
            tool = self.tool_registry.get_tool_for_connector(connector_id, actual_tool_name)
            if tool is None:
                return unavailable()
            governance = self.tool_registry.governance
            if governance is None or governance.check_call(org_id, connector, tool) is None:
                return unavailable()

            # 组织能力裁剪: 方法与参数取值限制 (不依赖具体执行器实现, 纵深防御)
            violation = validate_call(
                resolve_trims(
                    self.policy_engine.org_whitelist.get_capability_trims(org_id, connector_id),
                    actual_tool_name,
                ),
                arguments,
            )
            if violation:
                return unavailable()

            # 执行工具
            execution_result = await self.tool_executor.execute_tool(
                org_id=org_id,
                user_id=user_id,
                connector=connector,
                tool=tool,
                parameters=arguments,
            )

            if not execution_result.success:
                return MCPResponse(
                    error=MCPError(
                        code=MCPErrorCode.TOOL_EXECUTION_FAILED.value,
                        message=execution_result.error or "Tool execution failed",
                    )
                )

            # 构建成功响应
            tool_call_response = ToolCallResponse(
                tool_name=tool_name,
                result=execution_result.result,
                is_error=False,
            )

            logger.info(
                f"Tool executed successfully: {tool_name}",
                extra={
                    "org_id": org_id,
                    "user_id": user_id,
                    "execution_time_ms": execution_result.execution_time_ms,
                },
            )

            return MCPResponse(result=tool_call_response.to_dict())

        except Exception as e:
            logger.error("Error in tools/call: %s", type(e).__name__)
            return MCPResponse(
                error=MCPError(
                    code=MCPErrorCode.INTERNAL_ERROR.value,
                    message="Tool execution error",
                )
            )

    @staticmethod
    def _tool_unavailable() -> MCPResponse:
        """Do not distinguish unknown, disabled and unauthorized targets externally."""
        return MCPResponse(error=MCPError(
            code=MCPErrorCode.TOOL_NOT_FOUND.value,
            message="Tool unavailable",
        ))

    def _available_connector(self, connector_id: str, org_id: str) -> Connector | None:
        """发现与调用共用的无副作用门禁；不取凭据、不扣配额。"""
        blacklist = self.policy_engine.global_blacklist
        if blacklist.is_connector_blocked(connector_id):
            return None
        # 调用入口均已验证装配；此断言也避免内部调用误用无注册表的处理器。
        assert self.connector_registry is not None
        connector = self.connector_registry.get(connector_id)
        if connector is None or blacklist.is_namespace_blocked(connector.config.identity.namespace):
            return None
        if not connector.status.is_callable():
            return None
        if connector.config.identity.organization_id != org_id:
            return None
        org_whitelist = self.policy_engine.org_whitelist
        if org_whitelist.get_whitelist_entry(
            org_id, connector_id
        ) is not None and not org_whitelist.is_connector_whitelisted(org_id, connector_id):
            return None
        return connector

    def _apply_capability_trim(self, tool_name: str, org_id: str) -> ToolSchema | None:
        """只合并当前可用提供方的同一定义，歧义工具安全隐藏。"""
        org_whitelist = self.policy_engine.org_whitelist
        selected: ToolSchema | None = None
        effectives = []
        for connector_id in sorted(self.tool_registry.list_connectors_for_tool(tool_name)):
            connector = self._available_connector(connector_id, org_id)
            if connector is None:
                continue
            tool = self.tool_registry.get_tool_for_connector(connector_id, tool_name)
            if tool is None:
                continue
            governance = self.tool_registry.governance
            if governance is None or governance.check_call(org_id, connector, tool) is None:
                continue
            effective = resolve_trims(
                org_whitelist.get_capability_trims(org_id, connector_id), tool_name,
            )
            # 方法禁止/必填参数无允许值的提供方也不能贡献定义或扩大参数并集。
            if trim_tool_schema(tool, [effective]) is None:
                continue
            if selected is not None and selected.compute_full_hash() != tool.compute_full_hash():
                logger.warning("Hiding ambiguous tool definition", extra={"org_id": org_id})
                return None
            selected = tool
            effectives.append(effective)
        return trim_tool_schema(selected, effectives) if selected is not None else None


class MCPTransportHandler:
    """
    MCP 传输层处理器
    支持 STDIO 和 HTTP
    """

    def __init__(self, protocol_handler: MCPProtocolHandler) -> None:
        self.protocol_handler = protocol_handler

    async def handle_stdio_message(
        self,
        message: str,
        org_id: str,
        user_id: str,
    ) -> str:
        """
        处理 STDIO 消息

        Args:
            message: STDIO 行消息
            org_id: 组织 ID
            user_id: 用户 ID

        Returns:
            响应消息
        """
        response = await self.protocol_handler.handle_request(
            message,
            org_id,
            user_id,
        )
        return response

    async def handle_http_request(
        self,
        request_body: str,
        org_id: str,
        user_id: str,
    ) -> str:
        """
        处理 HTTP 请求

        Args:
            request_body: HTTP 请求体
            org_id: 组织 ID
            user_id: 用户 ID

        Returns:
            HTTP 响应体
        """
        response = await self.protocol_handler.handle_request(
            request_body,
            org_id,
            user_id,
        )
        return response
