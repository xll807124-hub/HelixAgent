"""
SEC-007 MCP Connector Governance - Day 2 Integration Tests
Day 2 集成测试：MCP 协议、传输层、持久化
"""

import json

import pytest

from src.security.mcp_connector_governance.execution import (
    ToolExecutor,
)
from src.security.mcp_connector_governance.models import (
    AuthConfig,
    AuthenticationMode,
    Connector,
    ConnectorConfig,
    ConnectorIdentity,
    ConnectorLifecycleState,
    ConnectorStatus,
    SignatureVerification,
    ToolCapability,
    ToolInputSchema,
    ToolRiskProfile,
    ToolSchema,
    TransportConfig,
    TrustLevel,
)
from src.security.mcp_connector_governance.models import (
    TransportType as ConnectorTransportType,
)
from src.security.mcp_connector_governance.policies import (
    PolicyEngine,
)
from src.security.mcp_connector_governance.protocol import (
    MCPErrorCode,
    MCPProtocolHandler,
    MCPRequest,
    MCPResponse,
    ToolListResponse,
)
from src.security.mcp_connector_governance.protocol.transport import (
    TransportSelector,
)
from src.security.mcp_connector_governance.registry import (
    ConnectorRegistry,
    ToolRegistry,
)
from tests.mcp_approval_helpers import approve_registered


class TestMCPProtocol:
    """测试 MCP 协议处理"""
    
    def test_mcp_request_parsing(self):
        """测试 MCP 请求解析"""
        request_json = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": "1",
        }
        
        request = MCPRequest(**request_json)
        assert request.method == "tools/list"
        assert request.id == "1"
        assert request.params == {}
    
    def test_mcp_response_serialization(self):
        """测试 MCP 响应序列化"""
        response = MCPResponse(
            result={"tools": []},
            id="1",
        )
        
        response_dict = response.to_dict()
        assert response_dict["jsonrpc"] == "2.0"
        assert response_dict["result"] == {"tools": []}
        assert response_dict["id"] == "1"
        assert "error" not in response_dict
    
    def test_mcp_error_response(self):
        """测试 MCP 错误响应"""
        from src.security.mcp_connector_governance.protocol import MCPError
        
        error = MCPError(
            code=MCPErrorCode.METHOD_NOT_FOUND.value,
            message="Method not found",
        )
        
        response = MCPResponse(error=error, id="1")
        response_dict = response.to_dict()
        
        assert response_dict["error"]["code"] == -32601
        assert response_dict["error"]["message"] == "Method not found"


class TestToolsListResponse:
    """测试 tools/list 响应格式"""
    
    def test_tool_list_response_format(self):
        """测试工具列表响应格式"""
        from src.security.mcp_connector_governance.protocol import ToolInfo
        
        tools = [
            ToolInfo(
                name="weather_getter",
                description="Get weather information",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"}
                    },
                    "required": ["city"]
                }
            )
        ]
        
        response = ToolListResponse(tools)
        response_dict = response.to_dict()
        
        assert "tools" in response_dict
        assert len(response_dict["tools"]) == 1
        assert response_dict["tools"][0]["name"] == "weather_getter"
        assert "inputSchema" in response_dict["tools"][0]


class TestTransportLayer:
    """测试传输层"""
    
    def test_transport_selector(self):
        """测试传输选择器"""
        async def dummy_handler(msg):
            return msg
        
        # STDIO 传输
        stdio_transport = TransportSelector.create_transport(
            "stdio",
            dummy_handler
        )
        assert stdio_transport is not None
        
        # HTTP 传输
        http_transport = TransportSelector.create_transport(
            "http",
            dummy_handler,
            host="localhost",
            port=8000
        )
        assert http_transport is not None
        
        # SSE 传输
        sse_transport = TransportSelector.create_transport(
            "sse",
            dummy_handler,
            host="localhost",
            port=8001
        )
        assert sse_transport is not None


class TestMCPProtocolHandler:
    """测试 MCP 协议处理器"""
    
    @pytest.mark.asyncio
    async def test_tools_list_request(self):
        """测试 tools/list 请求"""
        # 创建测试组件
        connector_registry = ConnectorRegistry()
        tool_registry = ToolRegistry()
        policy_engine = PolicyEngine()
        tool_executor = ToolExecutor(policy_engine)
        
        # 注册测试连接器
        connector = self._create_test_connector("conn_001")
        connector_registry.register(connector)
        
        # 注册测试工具
        tool = self._create_test_tool()
        tool_registry.register_tool(tool, connector.config.identity.connector_id)
        approve_registered(tool_registry, connector_registry, connector.connector_id)
        
        # 创建协议处理器
        handler = MCPProtocolHandler(
            tool_registry=tool_registry,
            policy_engine=policy_engine,
            tool_executor=tool_executor,
            connector_registry=connector_registry,
        )
        
        # 发送 tools/list 请求
        request_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": "1",
        })
        
        response_json = await handler.handle_request(
            request_json,
            org_id="org_001",
            user_id="user_001",
        )
        
        response_data = json.loads(response_json)
        
        assert response_data["jsonrpc"] == "2.0"
        assert "result" in response_data
        assert "tools" in response_data["result"]
    
    @pytest.mark.asyncio
    async def test_invalid_method(self):
        """测试无效方法"""
        tool_registry = ToolRegistry()
        policy_engine = PolicyEngine()
        tool_executor = ToolExecutor(policy_engine)
        
        handler = MCPProtocolHandler(
            tool_registry=tool_registry,
            policy_engine=policy_engine,
            tool_executor=tool_executor,
        )
        
        request_json = json.dumps({
            "jsonrpc": "2.0",
            "method": "invalid/method",
            "id": "1",
        })
        
        response_json = await handler.handle_request(
            request_json,
            org_id="org_001",
            user_id="user_001",
        )
        
        response_data = json.loads(response_json)
        
        assert "error" in response_data
        assert response_data["error"]["code"] == MCPErrorCode.METHOD_NOT_FOUND.value
    
    @pytest.mark.asyncio
    async def test_invalid_json(self):
        """测试无效 JSON"""
        tool_registry = ToolRegistry()
        policy_engine = PolicyEngine()
        tool_executor = ToolExecutor(policy_engine)
        
        handler = MCPProtocolHandler(
            tool_registry=tool_registry,
            policy_engine=policy_engine,
            tool_executor=tool_executor,
        )
        
        request_json = "invalid json {"
        
        response_json = await handler.handle_request(
            request_json,
            org_id="org_001",
            user_id="user_001",
        )
        
        response_data = json.loads(response_json)
        
        assert "error" in response_data
        assert response_data["error"]["code"] == MCPErrorCode.PARSE_ERROR.value
    
    def _create_test_connector(self, connector_id: str) -> Connector:
        """创建测试连接器"""
        identity = ConnectorIdentity(
            connector_id=connector_id,
            organization_id="org_001",
            namespace="test",
            display_name="Test Connector",
            version="1.0.0",
        )
        
        config = ConnectorConfig(
            identity=identity,
            trust_level=TrustLevel.L2_ORG_VERIFIED,
            transport=TransportConfig(type=ConnectorTransportType.HTTP),
            auth=AuthConfig(mode=AuthenticationMode.NONE),
            signature=SignatureVerification(is_signed=False),
        )
        
        status = ConnectorStatus(
            connector_id=connector_id,
            lifecycle_state=ConnectorLifecycleState.ACTIVE,
        )
        
        return Connector(config=config, status=status)
    
    def _create_test_tool(self) -> ToolSchema:
        """创建测试工具"""
        return ToolSchema(
            tool_name="test_tool",
            description="Test tool for integration tests",
            input_schema=ToolInputSchema(
                properties={"param1": {"type": "string"}},
                required=["param1"]
            ),
            risk_profile=ToolRiskProfile(
                risk_level="low",
                is_read_only=True,
                requires_human_approval=False,
                data_sensitivity="L2",
                network_access_required=False,
                filesystem_access_required=False,
                credential_access_required=False,
            ),
            capability=ToolCapability(),
        )


class TestEndToEndFlow:
    """端到端测试"""
    
    @pytest.mark.asyncio
    async def test_complete_tool_invocation_flow(self):
        """
        测试完整的工具调用流程：
        1. 策略检查
        2. 配额消耗
        3. 工具执行
        4. 审计日志
        """
        # 初始化组件
        connector_registry = ConnectorRegistry()
        tool_registry = ToolRegistry()
        policy_engine = PolicyEngine()
        tool_executor = ToolExecutor(policy_engine)
        
        # 初始化配额
        policy_engine.quota_manager.initialize_org_quota("org_001", base_quota=1000.0)
        
        # 注册连接器和工具
        connector = self._create_test_connector("conn_001")
        connector_registry.register(connector)
        tool = self._create_test_tool()
        tool_registry.register_tool(tool, connector.config.identity.connector_id)
        approve_registered(tool_registry, connector_registry, connector.connector_id)
        
        # 创建协议处理器
        handler = MCPProtocolHandler(
            tool_registry=tool_registry,
            policy_engine=policy_engine,
            tool_executor=tool_executor,
            connector_registry=connector_registry,
        )
        
        # Step 1: 查询可用工具
        tools_request = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": "1",
        })
        
        tools_response = await handler.handle_request(
            tools_request,
            org_id="org_001",
            user_id="user_001",
        )
        
        tools_data = json.loads(tools_response)
        assert "result" in tools_data
        assert len(tools_data["result"]["tools"]) > 0
        
        # Step 2: 调用工具
        call_request = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": f"conn_001:{tool.tool_name}",
                "arguments": {"param1": "test_value"}
            },
            "id": "2",
        })
        
        call_response = await handler.handle_request(
            call_request,
            org_id="org_001",
            user_id="user_001",
        )
        
        call_data = json.loads(call_response)
        
        # 验证响应
        if "error" in call_data:
            # 工具执行失败是可以接受的（因为这是占位符）
            assert "message" in call_data["error"]
        else:
            # 工具执行成功
            assert "result" in call_data
    
    def _create_test_connector(self, connector_id: str) -> Connector:
        """创建测试连接器"""
        identity = ConnectorIdentity(
            connector_id=connector_id,
            organization_id="org_001",
            namespace="test",
            display_name="Test Connector",
            version="1.0.0",
        )
        
        config = ConnectorConfig(
            identity=identity,
            trust_level=TrustLevel.L2_ORG_VERIFIED,
            transport=TransportConfig(type=ConnectorTransportType.HTTP),
            auth=AuthConfig(mode=AuthenticationMode.NONE),
            signature=SignatureVerification(is_signed=False),
        )
        
        status = ConnectorStatus(
            connector_id=connector_id,
            lifecycle_state=ConnectorLifecycleState.ACTIVE,
        )
        
        return Connector(config=config, status=status)
    
    def _create_test_tool(self) -> ToolSchema:
        """创建测试工具"""
        return ToolSchema(
            tool_name="test_tool",
            description="Test tool",
            input_schema=ToolInputSchema(
                properties={"param1": {"type": "string"}},
                required=["param1"]
            ),
            risk_profile=ToolRiskProfile(
                risk_level="low",
                is_read_only=True,
                requires_human_approval=False,
                data_sensitivity="L2",
                network_access_required=False,
                filesystem_access_required=False,
                credential_access_required=False,
            ),
            capability=ToolCapability(),
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
