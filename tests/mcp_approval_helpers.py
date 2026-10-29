"""Explicit definition approvals for pre-existing tests of other MCP gates.

No autouse fixture and no gate monkeypatch: each caller establishes a real scoped grant.
New approval/governance tests deliberately do not use these helpers.
"""

from src.security.mcp_connector_governance.registry import ConnectorRegistry, ToolRegistry


def trusted_fixture_authorizer(request):
    return request.actor == "fixture-reviewer" and request.approval_ref == "fixture-reviewed"


def approve_registered(tools, connectors, connector_id):
    governance = tools.bind_governance(connectors, authorizer=trusted_fixture_authorizer)
    connector = connectors.get(connector_id)
    org = connector.config.identity.organization_id
    for name in tools.list_tools_for_connector(connector_id):
        tool = tools.get_tool_for_connector(connector_id, name)
        governance.approve(
            governance.snapshot(org, connector_id),
            name,
            tool.compute_definition_digest(),
            actor="fixture-reviewer",
            approval_ref="fixture-reviewed",
        )


async def execute_approved_fixture(executor, org_id, user_id, connector, tool, parameters):
    """Arrange an explicit grant, then exercise the unchanged production execution path."""
    if executor.tool_registry is None:
        tools, connectors = ToolRegistry(), ConnectorRegistry()
        connectors.register(connector)
        tools.register_tool(tool, connector.connector_id)
        approve_registered(tools, connectors, connector.connector_id)
        executor.tool_registry = tools
    return await executor.execute_tool(org_id, user_id, connector, tool, parameters)
