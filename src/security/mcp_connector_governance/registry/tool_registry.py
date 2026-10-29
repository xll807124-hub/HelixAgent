"""
Tool Registry

Manages tool discovery, schema versioning, and approval tracking.
"""

import logging
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .tool_governance import ApprovalRequest, ToolGovernance

if TYPE_CHECKING:
    from ..audit import AuditLogger
    from .connector_registry import ConnectorRegistry

from ..models import (
    ToolApproval,
    ToolSchema,
)

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Registry for MCP tools across all connectors.
    
    Responsibilities:
    - Track tool schemas and versions
    - Manage tool approvals (bound to schema digest)
    - Detect schema changes (breaking vs safe)
    - Track tool-to-connector mappings
    """
    
    def __init__(self) -> None:
        self.governance: ToolGovernance | None = None
        # tool_name -> list of ToolSchema (versioned)
        self._tools: dict[str, list[ToolSchema]] = {}
        
        # schema_digest -> ToolApproval
        self._approvals: dict[str, ToolApproval] = {}
        
        # tool_name -> set of connector_ids
        self._tool_to_connectors: dict[str, set[str]] = {}
        
        # connector_id -> set of tool_names
        self._connector_to_tools: dict[str, set[str]] = {}
        # 当前定义属于提供方，不能用全局同名工具的“最新版本”代替。
        self._provider_tools: dict[str, dict[str, ToolSchema]] = {}

    def bind_governance(
        self, connectors: "ConnectorRegistry", *,
        authorizer: Callable[[ApprovalRequest], bool] | None = None,
        audit_logger: "AuditLogger | None" = None, authorization_timeout: float = 1.0,
    ) -> ToolGovernance:
        with connectors.lifecycle_lock:
            if self.governance is not None:
                if self.governance.connectors is not connectors:
                    raise ValueError("Tool registry already bound")
                if authorizer is not None and self.governance.authorizer is None:
                    self.governance.authorizer = authorizer
                elif authorizer is not None and self.governance.authorizer is not authorizer:
                    raise ValueError("Approval authority already bound")
                return self.governance
            if connectors.tool_governance is not None:
                raise ValueError("Connector registry already bound")
            self.governance = ToolGovernance(
                self, connectors, authorizer=authorizer, audit_logger=audit_logger,
                authorization_timeout=authorization_timeout,
            )
            connectors.tool_governance = self.governance
            return self.governance

    def _replace_local(self, connector_id: str, definitions: dict[str, ToolSchema]) -> None:
        # Retain version history for names still provided; remove only withdrawn associations.
        removed = self._connector_to_tools.get(connector_id, set()) - definitions.keys()
        for name in removed:
            self._tool_to_connectors[name].discard(connector_id)
            if not self._tool_to_connectors[name]:
                self._tool_to_connectors.pop(name)
                self._tools.pop(name, None)
        self._connector_to_tools[connector_id] = set()
        self._provider_tools[connector_id] = {}
        for tool in definitions.values():
            self._register_local(tool, connector_id)
    
    def register_tool(
        self,
        tool: ToolSchema,
        connector_id: str,
    ) -> None:
        if self.governance is not None:
            self.governance.upsert(connector_id, [tool])
        else:
            self._register_local(tool, connector_id)

    def _register_local(self, tool: ToolSchema, connector_id: str) -> None:
        """
        Register a tool from a connector.
        
        Args:
            tool: Tool schema to register
            connector_id: Connector providing this tool
        """
        tool_name = tool.tool_name
        
        # Store tool schema
        if tool_name not in self._tools:
            self._tools[tool_name] = []
        
        # Check if this exact schema already exists
        schema_digest = tool.compute_schema_digest()
        existing = any(version.compute_definition_digest() == tool.compute_definition_digest()
                       for version in self._tools[tool_name])
        
        if not existing:
            self._tools[tool_name].append(deepcopy(tool))
            logger.info(
                f"Registered new tool schema: {tool_name} "
                f"(digest={schema_digest[:8]}...)"
            )
        
        # Update mappings
        if tool_name not in self._tool_to_connectors:
            self._tool_to_connectors[tool_name] = set()
        self._tool_to_connectors[tool_name].add(connector_id)
        
        if connector_id not in self._connector_to_tools:
            self._connector_to_tools[connector_id] = set()
        self._connector_to_tools[connector_id].add(tool_name)
        # 同 Schema 可有不同描述/风险；保存本次登记快照，不复用全局去重对象。
        self._provider_tools.setdefault(connector_id, {})[tool_name] = deepcopy(tool)
    
    def register_tools_batch(
        self,
        tools: list[ToolSchema],
        connector_id: str,
    ) -> None:
        """
        Register multiple tools from a connector.
        
        Args:
            tools: List of tool schemas
            connector_id: Connector providing these tools
        """
        if self.governance is not None:
            self.governance.upsert(connector_id, tools)
        else:
            for tool in tools:
                self._register_local(tool, connector_id)
    
    def get_tool(
        self,
        tool_name: str,
        schema_digest: str | None = None,
    ) -> ToolSchema | None:
        """
        Get tool schema by name and optional digest.
        
        Args:
            tool_name: Tool name
            schema_digest: Optional schema digest for specific version
            
        Returns:
            ToolSchema or None if not found
        """
        if tool_name not in self._tools:
            return None
        
        if schema_digest:
            return deepcopy(self._find_tool_by_digest(tool_name, schema_digest))
        
        # Return latest version
        return deepcopy(self._tools[tool_name][-1]) if self._tools[tool_name] else None
    
    def get_tool_for_connector(self, connector_id: str, tool_name: str) -> ToolSchema | None:
        """Read a provider's current definition without exposing its mutable snapshot."""
        tool = self._provider_tools.get(connector_id, {}).get(tool_name)
        return deepcopy(tool) if tool is not None else None

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())
    
    def list_tools_for_connector(self, connector_id: str) -> list[str]:
        """List tool names provided by a connector."""
        return list(self._connector_to_tools.get(connector_id, set()))
    
    def list_connectors_for_tool(self, tool_name: str) -> list[str]:
        """List connector IDs providing a specific tool."""
        return list(self._tool_to_connectors.get(tool_name, set()))
    
    def get_tool_versions(self, tool_name: str) -> list[ToolSchema]:
        """Get all versions of a tool schema."""
        return deepcopy(self._tools.get(tool_name, []))
    
    def approve_tool(
        self,
        tool_name: str,
        schema_digest: str,
        approved_by: str,
        approval_type: str,
        valid_until: datetime | None = None,
        notes: str = "",
    ) -> ToolApproval:
        """
        Approve a specific tool schema version.
        
        Args:
            tool_name: Tool name
            schema_digest: Schema digest to approve
            approved_by: User ID of approver
            approval_type: Type of approval
            valid_until: Optional expiry
            notes: Approval notes
            
        Returns:
            ToolApproval record
        """
        approval = ToolApproval(
            tool_name=tool_name,
            schema_digest=schema_digest,
            approved_by=approved_by,
            approved_at=datetime.utcnow(),
            approval_type=approval_type,
            valid_until=valid_until,
            approval_notes=notes,
        )
        
        self._approvals[schema_digest] = approval
        
        logger.info(
            f"Approved tool {tool_name} "
            f"(digest={schema_digest[:8]}..., type={approval_type})"
        )
        
        return approval
    
    def get_approval(self, schema_digest: str) -> ToolApproval | None:
        """Get approval for a schema digest."""
        return self._approvals.get(schema_digest)
    
    def is_approved(
        self,
        tool_name: str,
        schema_digest: str,
        now: datetime | None = None,
    ) -> bool:
        """
        Check if a tool schema is approved and valid.
        
        Args:
            tool_name: Tool name
            schema_digest: Schema digest
            now: Optional current time for testing
            
        Returns:
            True if approved and valid
        """
        approval = self._approvals.get(schema_digest)
        if not approval:
            return False
        
        if approval.tool_name != tool_name:
            return False
        
        return approval.is_valid(now)
    
    def revoke_approval(self, schema_digest: str) -> None:
        """
        Revoke approval for a schema digest.
        
        Args:
            schema_digest: Schema digest to revoke
        """
        if schema_digest in self._approvals:
            approval = self._approvals.pop(schema_digest)
            logger.warning(
                f"Revoked approval for tool {approval.tool_name} "
                f"(digest={schema_digest[:8]}...)"
            )
    
    def detect_schema_change(
        self,
        tool_name: str,
        new_schema: ToolSchema,
    ) -> dict[str, Any] | None:
        """
        Detect schema changes and classify as breaking or safe.
        
        Args:
            tool_name: Tool name
            new_schema: New schema to compare
            
        Returns:
            Change detection result or None if no previous schema
        """
        versions = self._tools.get(tool_name, [])
        if not versions:
            return None
        
        latest = versions[-1]
        new_digest = new_schema.compute_definition_digest()
        latest_digest = latest.compute_definition_digest()
        
        if new_digest == latest_digest:
            return {
                "changed": False,
                "is_breaking": False,
                "message": "No schema change detected",
            }
        
        is_breaking = new_schema.is_breaking_change(latest)
        
        return {
            "changed": True,
            "is_breaking": is_breaking,
            "old_digest": latest_digest,
            "new_digest": new_digest,
            "message": (
                "Breaking schema change detected" if is_breaking
                else "Safe schema change detected"
            ),
        }
    
    def unregister_connector(self, connector_id: str) -> None:
        if self.governance is not None:
            connector = self.governance.connectors.get(connector_id)
            if connector is None:
                return
            snapshot = self.governance.snapshot(
                connector.config.identity.organization_id, connector_id,
            )
            self.governance.synchronize(snapshot.org_id, connector_id, [],
                                       expected_generation=snapshot.generation, actor="registry")
        else:
            self._unregister_local(connector_id)

    def _unregister_local(self, connector_id: str) -> None:
        """
        Unregister all tools from a connector.
        
        Args:
            connector_id: Connector ID to unregister
        """
        tool_names = self._connector_to_tools.pop(connector_id, set())
        self._provider_tools.pop(connector_id, None)
        
        for tool_name in tool_names:
            if tool_name in self._tool_to_connectors:
                self._tool_to_connectors[tool_name].discard(connector_id)
                
                # Remove tool entirely if no connectors provide it
                if not self._tool_to_connectors[tool_name]:
                    self._tool_to_connectors.pop(tool_name)
                    self._tools.pop(tool_name, None)
        
        logger.info(
            f"Unregistered {len(tool_names)} tools from connector {connector_id}"
        )
    
    def _find_tool_by_digest(
        self,
        tool_name: str,
        schema_digest: str,
    ) -> ToolSchema | None:
        """Find tool schema by digest."""
        versions = self._tools.get(tool_name, [])
        for tool in versions:
            if tool.compute_schema_digest() == schema_digest:
                return tool
        return None
    
    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        total_tools = len(self._tools)
        total_versions = sum(len(versions) for versions in self._tools.values())
        total_approvals = len(self._approvals)
        
        # Count approvals by type
        approvals_by_type: dict[str, int] = {}
        for approval in self._approvals.values():
            approval_type = approval.approval_type
            approvals_by_type[approval_type] = approvals_by_type.get(approval_type, 0) + 1
        
        return {
            "total_tools": total_tools,
            "total_versions": total_versions,
            "total_approvals": total_approvals,
            "approvals_by_type": approvals_by_type,
            "tools_by_connector_count": len(self._connector_to_tools),
        }
