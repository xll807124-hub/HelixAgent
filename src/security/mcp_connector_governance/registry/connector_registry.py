"""
Connector Registry

Manages connector registration, discovery, and version tracking.
"""

import logging
from datetime import datetime
from threading import RLock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..authorization.auth_manager import AuthorizationManager
    from .tool_governance import ToolGovernance

from ..models import (
    Connector,
    ConnectorLifecycleState,
    TrustLevel,
)

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """
    Central registry for all MCP connectors.
    
    Responsibilities:
    - Register new connectors
    - Track connector versions
    - Query connectors by ID, namespace, trust level
    - Maintain connector lifecycle state
    """
    
    def __init__(self) -> None:
        self.lifecycle_lock = RLock()
        self.authorization_manager: AuthorizationManager | None = None
        self.tool_governance: ToolGovernance | None = None
        self._connectors: dict[str, Connector] = {}
        self._namespace_index: dict[str, list[str]] = {}  # namespace -> [connector_ids]
        self._trust_level_index: dict[TrustLevel, list[str]] = {}  # trust_level -> [connector_ids]
        
    def register(self, connector: Connector) -> None:
        if self.tool_governance is not None and self.get(connector.connector_id) is not None:
            self.tool_governance.replace_connector(connector)
        else:
            with self.lifecycle_lock:
                self._register_local(connector)

    def _register_local(self, connector: Connector) -> None:
        """
        Register a new connector or update existing.
        
        Args:
            connector: Connector to register
            
        Raises:
            ValueError: If connector validation fails
        """
        connector_id = connector.connector_id
        
        # Validate connector
        if not connector_id:
            raise ValueError("Connector ID is required")
        
        if not connector.config.identity.namespace:
            raise ValueError("Connector namespace is required")
        
        # Register connector
        self._connectors[connector_id] = connector
        
        # Update namespace index
        namespace = connector.config.identity.namespace
        if namespace not in self._namespace_index:
            self._namespace_index[namespace] = []
        if connector_id not in self._namespace_index[namespace]:
            self._namespace_index[namespace].append(connector_id)
        
        # Update trust level index
        trust_level = connector.trust_level
        if trust_level not in self._trust_level_index:
            self._trust_level_index[trust_level] = []
        if connector_id not in self._trust_level_index[trust_level]:
            self._trust_level_index[trust_level].append(connector_id)
        
        logger.info(
            f"Registered connector {connector_id} "
            f"(namespace={namespace}, trust_level={trust_level.value})"
        )
    
    def get(self, connector_id: str) -> Connector | None:
        """Get connector by ID."""
        return self._connectors.get(connector_id)
    
    def list_all(self) -> list[Connector]:
        """List all registered connectors."""
        return list(self._connectors.values())
    
    def list_by_namespace(self, namespace: str) -> list[Connector]:
        """List connectors by namespace."""
        connector_ids = self._namespace_index.get(namespace, [])
        return [self._connectors[cid] for cid in connector_ids if cid in self._connectors]
    
    def list_by_trust_level(self, trust_level: TrustLevel) -> list[Connector]:
        """List connectors by trust level."""
        connector_ids = self._trust_level_index.get(trust_level, [])
        return [self._connectors[cid] for cid in connector_ids if cid in self._connectors]
    
    def list_by_state(self, state: ConnectorLifecycleState) -> list[Connector]:
        """List connectors by lifecycle state."""
        return [
            conn for conn in self._connectors.values()
            if conn.lifecycle_state == state
        ]
    
    def list_active(self) -> list[Connector]:
        """List all active connectors."""
        return self.list_by_state(ConnectorLifecycleState.ACTIVE)
    
    def update_status(
        self,
        connector_id: str,
        new_state: ConnectorLifecycleState,
        reason: str = "",
        changed_by: str = "system",
    ) -> None:
        """
        Update connector lifecycle state.
        
        Args:
            connector_id: Connector ID
            new_state: New lifecycle state
            reason: Reason for state change
            changed_by: User/system that triggered change
        """
        connector = self.get(connector_id)
        if not connector:
            raise ValueError(f"Connector {connector_id} not found")
        
        old_state = connector.lifecycle_state
        
        # Every stop gets a monotonically increasing fence, even a rapid pause/resume.
        if new_state not in (ConnectorLifecycleState.ACTIVE, ConnectorLifecycleState.RESTRICTED):
            connector.status.credential_generation += 1
        connector.status.lifecycle_state = new_state
        connector.status.last_state_change = datetime.utcnow()
        connector.status.state_change_reason = reason
        connector.status.state_changed_by = changed_by
        
        logger.info(
            f"Connector {connector_id} state transition: "
            f"{old_state.value} -> {new_state.value} (reason: {reason})"
        )
    
    def update_health(
        self,
        connector_id: str,
        health_status: str,
        consecutive_failures: int = 0,
    ) -> None:
        """
        Update connector health status.
        
        Args:
            connector_id: Connector ID
            health_status: Health status ("healthy", "degraded", "unhealthy")
            consecutive_failures: Number of consecutive failures
        """
        connector = self.get(connector_id)
        if not connector:
            raise ValueError(f"Connector {connector_id} not found")
        
        connector.status.last_health_check = datetime.utcnow()
        connector.status.health_status = health_status
        connector.status.consecutive_failures = consecutive_failures
        
        # Auto-transition to HEALTH_ANOMALY if unhealthy
        if health_status == "unhealthy" and consecutive_failures >= 3:
            if connector.lifecycle_state == ConnectorLifecycleState.ACTIVE:
                self.update_status(
                    connector_id,
                    ConnectorLifecycleState.HEALTH_ANOMALY,
                    reason=f"Health check failed {consecutive_failures} times",
                    changed_by="health_monitor",
                )
        
        logger.debug(
            f"Connector {connector_id} health updated: "
            f"{health_status} (failures={consecutive_failures})"
        )
    
    def remove(self, connector_id: str) -> None:
        if self.tool_governance is not None:
            self.tool_governance.remove_connector(connector_id)
        else:
            with self.lifecycle_lock:
                self._remove_local(connector_id)

    def _remove_local(self, connector_id: str) -> None:
        """
        Remove connector from registry.
        
        Args:
            connector_id: Connector ID to remove
        """
        connector = self._connectors.pop(connector_id, None)
        if not connector:
            logger.warning(f"Attempted to remove non-existent connector {connector_id}")
            return
        
        # Clean up indexes
        namespace = connector.config.identity.namespace
        if namespace in self._namespace_index:
            self._namespace_index[namespace] = [
                cid for cid in self._namespace_index[namespace] if cid != connector_id
            ]
        
        trust_level = connector.trust_level
        if trust_level in self._trust_level_index:
            self._trust_level_index[trust_level] = [
                cid for cid in self._trust_level_index[trust_level] if cid != connector_id
            ]
        
        logger.info(f"Removed connector {connector_id} from registry")
    
    def count(self) -> int:
        """Return total number of registered connectors."""
        return len(self._connectors)
    
    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        stats: dict[str, Any] = {
            "total_connectors": self.count(),
            "by_trust_level": {},
            "by_state": {},
            "by_namespace": {},
        }
        
        # Count by trust level
        for level in TrustLevel:
            stats["by_trust_level"][level.value] = len(self.list_by_trust_level(level))
        
        # Count by state
        for state in ConnectorLifecycleState:
            stats["by_state"][state.value] = len(self.list_by_state(state))
        
        # Count by namespace
        for namespace, connector_ids in self._namespace_index.items():
            stats["by_namespace"][namespace] = len(connector_ids)
        
        return stats
