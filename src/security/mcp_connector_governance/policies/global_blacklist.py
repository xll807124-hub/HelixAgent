"""
Global Blacklist

Immutable platform-level blacklist for connectors and tools.
Cannot be overridden by organization policies.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class BlacklistEntry:
    """Entry in the global blacklist."""
    
    identifier: str  # connector_id, namespace, or tool_name
    entry_type: str  # "connector", "namespace", "tool"
    reason: str
    added_at: datetime
    added_by: str  # Platform admin user ID
    severity: str = "high"  # "critical", "high", "medium"
    
    def to_dict(self) -> dict:
        return {
            "identifier": self.identifier,
            "entry_type": self.entry_type,
            "reason": self.reason,
            "added_at": self.added_at.isoformat(),
            "added_by": self.added_by,
            "severity": self.severity,
        }


class GlobalBlacklist:
    """
    Immutable platform-level blacklist.
    
    Scope:
    - Block specific connectors by ID
    - Block entire namespaces (e.g., block all connectors from "malicious-publisher")
    - Block specific tools by name
    
    Priority: Highest - overrides all organization policies.
    """
    
    def __init__(self) -> None:
        self._blocked_connectors: dict[str, BlacklistEntry] = {}
        self._blocked_namespaces: dict[str, BlacklistEntry] = {}
        self._blocked_tools: dict[str, BlacklistEntry] = {}
    
    def add_connector(
        self,
        connector_id: str,
        reason: str,
        added_by: str,
        severity: str = "high",
    ) -> None:
        """
        Add connector to global blacklist.
        
        Args:
            connector_id: Connector ID to block
            reason: Reason for blocking
            added_by: Platform admin user ID
            severity: Severity level
        """
        entry = BlacklistEntry(
            identifier=connector_id,
            entry_type="connector",
            reason=reason,
            added_at=datetime.utcnow(),
            added_by=added_by,
            severity=severity,
        )
        
        self._blocked_connectors[connector_id] = entry
        
        logger.warning(
            f"Added connector to global blacklist: {connector_id} "
            f"(reason: {reason}, severity: {severity})"
        )
    
    def add_namespace(
        self,
        namespace: str,
        reason: str,
        added_by: str,
        severity: str = "critical",
    ) -> None:
        """
        Add entire namespace to global blacklist.
        
        Args:
            namespace: Namespace to block
            reason: Reason for blocking
            added_by: Platform admin user ID
            severity: Severity level
        """
        entry = BlacklistEntry(
            identifier=namespace,
            entry_type="namespace",
            reason=reason,
            added_at=datetime.utcnow(),
            added_by=added_by,
            severity=severity,
        )
        
        self._blocked_namespaces[namespace] = entry
        
        logger.critical(
            f"Added namespace to global blacklist: {namespace} "
            f"(reason: {reason})"
        )
    
    def add_tool(
        self,
        tool_name: str,
        reason: str,
        added_by: str,
        severity: str = "high",
    ) -> None:
        """
        Add tool to global blacklist.
        
        Args:
            tool_name: Tool name to block
            reason: Reason for blocking
            added_by: Platform admin user ID
            severity: Severity level
        """
        entry = BlacklistEntry(
            identifier=tool_name,
            entry_type="tool",
            reason=reason,
            added_at=datetime.utcnow(),
            added_by=added_by,
            severity=severity,
        )
        
        self._blocked_tools[tool_name] = entry
        
        logger.warning(
            f"Added tool to global blacklist: {tool_name} "
            f"(reason: {reason}, severity: {severity})"
        )
    
    def is_connector_blocked(self, connector_id: str) -> bool:
        """Check if connector is blocked."""
        return connector_id in self._blocked_connectors
    
    def is_namespace_blocked(self, namespace: str) -> bool:
        """Check if namespace is blocked."""
        return namespace in self._blocked_namespaces
    
    def is_tool_blocked(self, tool_name: str) -> bool:
        """Check if tool is blocked."""
        return tool_name in self._blocked_tools
    
    def get_block_reason(
        self,
        identifier: str,
        entry_type: str,
    ) -> str | None:
        """
        Get reason for blocking.
        
        Args:
            identifier: Connector ID, namespace, or tool name
            entry_type: "connector", "namespace", or "tool"
            
        Returns:
            Block reason or None if not blocked
        """
        if entry_type == "connector":
            entry = self._blocked_connectors.get(identifier)
        elif entry_type == "namespace":
            entry = self._blocked_namespaces.get(identifier)
        elif entry_type == "tool":
            entry = self._blocked_tools.get(identifier)
        else:
            return None
        
        return entry.reason if entry else None
    
    def remove_connector(self, connector_id: str) -> bool:
        """
        Remove connector from blacklist.
        
        Args:
            connector_id: Connector ID to unblock
            
        Returns:
            True if removed, False if not found
        """
        if connector_id in self._blocked_connectors:
            self._blocked_connectors.pop(connector_id)
            logger.info(f"Removed connector from global blacklist: {connector_id}")
            return True
        return False
    
    def remove_namespace(self, namespace: str) -> bool:
        """
        Remove namespace from blacklist.
        
        Args:
            namespace: Namespace to unblock
            
        Returns:
            True if removed, False if not found
        """
        if namespace in self._blocked_namespaces:
            self._blocked_namespaces.pop(namespace)
            logger.info(f"Removed namespace from global blacklist: {namespace}")
            return True
        return False
    
    def remove_tool(self, tool_name: str) -> bool:
        """
        Remove tool from blacklist.
        
        Args:
            tool_name: Tool name to unblock
            
        Returns:
            True if removed, False if not found
        """
        if tool_name in self._blocked_tools:
            self._blocked_tools.pop(tool_name)
            logger.info(f"Removed tool from global blacklist: {tool_name}")
            return True
        return False
    
    def list_blocked_connectors(self) -> list[BlacklistEntry]:
        """List all blocked connectors."""
        return list(self._blocked_connectors.values())
    
    def list_blocked_namespaces(self) -> list[BlacklistEntry]:
        """List all blocked namespaces."""
        return list(self._blocked_namespaces.values())
    
    def list_blocked_tools(self) -> list[BlacklistEntry]:
        """List all blocked tools."""
        return list(self._blocked_tools.values())
    
    def export(self) -> dict[str, list[dict]]:
        """Export blacklist for backup or auditing."""
        return {
            "connectors": [e.to_dict() for e in self._blocked_connectors.values()],
            "namespaces": [e.to_dict() for e in self._blocked_namespaces.values()],
            "tools": [e.to_dict() for e in self._blocked_tools.values()],
        }
    
    def get_stats(self) -> dict[str, int]:
        """Get blacklist statistics."""
        return {
            "blocked_connectors": len(self._blocked_connectors),
            "blocked_namespaces": len(self._blocked_namespaces),
            "blocked_tools": len(self._blocked_tools),
        }
