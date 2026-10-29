"""Malformed protocol input must fail before dispatch and hide internal errors."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.security.mcp_connector_governance.protocol.mcp_handler import MCPProtocolHandler


@pytest.fixture
def handler():
    return MCPProtocolHandler(MagicMock(), MagicMock(), AsyncMock(), MagicMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("request_json, code", [
    ("{", -32700), ("null", -32600), ("[]", -32600), ("1", -32600),
    ('{"method":"tools/list"}', -32600),
    ('{"jsonrpc":"1.0","method":"tools/list"}', -32600),
    ('{"jsonrpc":"2.0","method":5}', -32600),
    ('{"jsonrpc":"2.0","method":""}', -32600),
    ('{"jsonrpc":"2.0","method":"tools/list","id":true}', -32600),
    ('{"jsonrpc":"2.0","method":"tools/list","id":{}}', -32600),
    ('{"jsonrpc":"2.0","method":"tools/call","params":null}', -32602),
    ('{"jsonrpc":"2.0","method":"tools/call","params":[]}', -32602),
])
async def test_invalid_request_does_not_reach_registry_or_executor(handler, request_json, code):
    response = json.loads(await handler.handle_request(request_json, "org", "user"))
    assert response["error"]["code"] == code
    handler.tool_registry.list_tools.assert_not_called()
    handler.tool_executor.execute_tool.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{}, {"name": 7}, {"name": "c:t", "arguments": []}])
async def test_invalid_call_parameters_are_rejected(handler, params):
    response = json.loads(await handler.handle_request(json.dumps({
        "jsonrpc": "2.0", "method": "tools/call", "params": params, "id": 19,
    }), "org", "user"))
    assert response["error"]["code"] == -32602
    assert response["id"] == 19
    handler.tool_executor.execute_tool.assert_not_called()


@pytest.mark.asyncio
async def test_internal_error_does_not_expose_exception_contents(handler):
    handler.tool_registry.list_tools.side_effect = RuntimeError("private-token-123")
    raw = await handler.handle_request(
        '{"jsonrpc":"2.0","method":"tools/list","id":"request"}', "org", "user",
    )
    assert "private-token-123" not in raw
    response = json.loads(raw)
    assert response["error"]["code"] == -32603
    assert response["id"] == "request"
