"""
Audit Logger

Non-sensitive audit logging for MCP connector governance (RT-008 compliant).
"""

import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AuditEventType(Enum):
    """Audit event types."""
    
    # Connector lifecycle
    CONNECTOR_REGISTERED = "connector_registered"
    CONNECTOR_ACTIVATED = "connector_activated"
    CONNECTOR_PAUSED = "connector_paused"
    CONNECTOR_REVOKED = "connector_revoked"
    CONNECTOR_STATE_CHANGED = "connector_state_changed"
    
    # Tool events
    TOOL_REGISTERED = "tool_registered"
    TOOL_APPROVED = "tool_approved"
    TOOL_INVOKED = "tool_invoked"
    TOOL_FAILED = "tool_failed"
    
    # Policy events
    POLICY_DECISION = "policy_decision"
    QUOTA_EXCEEDED = "quota_exceeded"
    BLACKLIST_ADDED = "blacklist_added"
    WHITELIST_ADDED = "whitelist_added"
    
    # Authorization events
    AUTH_GRANTED = "auth_granted"
    AUTH_DENIED = "auth_denied"
    TOKEN_REFRESHED = "token_refreshed"
    
    # Security events
    SIGNATURE_VERIFIED = "signature_verified"
    SIGNATURE_INVALID = "signature_invalid"
    SCHEMA_CHANGE_DETECTED = "schema_change_detected"


class AuditLogger:
    """
    Audit logger for MCP connector governance.
    
    RT-008 Compliance:
    - Non-sensitive logging only
    - Structured JSON format
    - Immutable append-only logs
    - Retention policy support
    """
    
    def __init__(self, log_file: str | None = None) -> None:
        """
        Initialize audit logger.
        
        Args:
            log_file: Optional file path for audit logs
        """
        self.log_file = log_file
        self._audit_events: list[dict[str, Any]] = []
    
    def log_event(
        self,
        event_type: AuditEventType,
        actor: str,
        resource_type: str,
        resource_id: str,
        action: str,
        result: str,
        metadata: dict[str, Any] | None = None,
        org_id: str | None = None,
    ) -> None:
        """
        Log an audit event.
        
        Args:
            event_type: Type of event
            actor: User/system performing action
            resource_type: Type of resource (connector, tool, policy)
            resource_id: Resource identifier
            action: Action performed
            result: Result (success, denied, failed)
            metadata: Additional non-sensitive metadata
            org_id: Organization ID
        """
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type.value,
            "actor": actor,
            "org_id": org_id,
            "resource": {
                "type": resource_type,
                "id": resource_id,
            },
            "action": action,
            "result": result,
            "metadata": self._sanitize_metadata(metadata or {}),
        }
        
        self._audit_events.append(event)
        
        # Log to file if configured
        if self.log_file:
            self._write_to_file(event)
        
        # Also log via standard logger
        logger.info(
            f"Audit: {event_type.value}",
            extra=event,
        )
    
    def log_connector_registered(
        self,
        connector_id: str,
        namespace: str,
        trust_level: str,
        registered_by: str,
        org_id: str,
    ) -> None:
        """Log connector registration."""
        self.log_event(
            event_type=AuditEventType.CONNECTOR_REGISTERED,
            actor=registered_by,
            resource_type="connector",
            resource_id=connector_id,
            action="register",
            result="success",
            metadata={
                "namespace": namespace,
                "trust_level": trust_level,
            },
            org_id=org_id,
        )
    
    def log_tool_invocation(
        self,
        connector_id: str,
        tool_name: str,
        user_id: str,
        org_id: str,
        result: str,
        execution_time_ms: float,
        quota_cost: float,
    ) -> None:
        """Log tool invocation."""
        self.log_event(
            event_type=AuditEventType.TOOL_INVOKED,
            actor=user_id,
            resource_type="tool",
            resource_id=f"{connector_id}:{tool_name}",
            action="invoke",
            result=result,
            metadata={
                "connector_id": connector_id,
                "tool_name": tool_name,
                "execution_time_ms": execution_time_ms,
                "quota_cost": quota_cost,
            },
            org_id=org_id,
        )
    
    def log_policy_decision(
        self,
        connector_id: str,
        tool_name: str | None,
        user_id: str,
        org_id: str,
        decision: str,
        reason: str,
        blocked_by: str | None = None,
    ) -> None:
        """Log policy decision."""
        resource_id = f"{connector_id}:{tool_name}" if tool_name else connector_id
        
        self.log_event(
            event_type=AuditEventType.POLICY_DECISION,
            actor=user_id,
            resource_type="policy",
            resource_id=resource_id,
            action="evaluate",
            result=decision,
            metadata={
                "reason": reason,
                "blocked_by": blocked_by,
            },
            org_id=org_id,
        )
    
    def log_quota_exceeded(
        self,
        org_id: str,
        connector_id: str,
        user_id: str,
        quota_cost: float,
        quota_remaining: float,
    ) -> None:
        """Log quota exceeded event."""
        self.log_event(
            event_type=AuditEventType.QUOTA_EXCEEDED,
            actor=user_id,
            resource_type="quota",
            resource_id=org_id,
            action="check",
            result="exceeded",
            metadata={
                "connector_id": connector_id,
                "quota_cost": quota_cost,
                "quota_remaining": quota_remaining,
            },
            org_id=org_id,
        )
    
    def log_schema_change(
        self,
        connector_id: str,
        tool_name: str,
        is_breaking: bool,
        old_digest: str,
        new_digest: str,
    ) -> None:
        """Log schema change detection."""
        self.log_event(
            event_type=AuditEventType.SCHEMA_CHANGE_DETECTED,
            actor="system",
            resource_type="tool_schema",
            resource_id=f"{connector_id}:{tool_name}",
            action="detect_change",
            result="breaking" if is_breaking else "safe",
            metadata={
                "old_digest": old_digest,
                "new_digest": new_digest,
            },
        )
    
    def log_signature_verification(
        self,
        connector_id: str,
        verification_result: str,
        signature_format: str,
        signer_identity: str | None = None,
    ) -> None:
        """Log signature verification."""
        event_type = (
            AuditEventType.SIGNATURE_VERIFIED
            if verification_result == "valid"
            else AuditEventType.SIGNATURE_INVALID
        )
        
        self.log_event(
            event_type=event_type,
            actor="system",
            resource_type="signature",
            resource_id=connector_id,
            action="verify",
            result=verification_result,
            metadata={
                "signature_format": signature_format,
                "signer_identity": signer_identity,
            },
        )
    
    def log_lifecycle_transition(
        self,
        connector_id: str,
        old_state: str,
        new_state: str,
        actor: str,
        reason: str,
        result: str = "success",
        org_id: str | None = None,
    ) -> None:
        """Log a connector lifecycle transition (or a denied attempt)."""
        event_type = {
            "active": AuditEventType.CONNECTOR_ACTIVATED,
            "paused": AuditEventType.CONNECTOR_PAUSED,
            "revoked": AuditEventType.CONNECTOR_REVOKED,
        }.get(new_state, AuditEventType.CONNECTOR_STATE_CHANGED)
        if result != "success":
            # 被拒绝的尝试不能记成"已激活/已撤销"，统一归为状态变更事件
            event_type = AuditEventType.CONNECTOR_STATE_CHANGED

        self.log_event(
            event_type=event_type,
            actor=actor,
            resource_type="connector",
            resource_id=connector_id,
            action="transition",
            result=result,
            metadata={
                "from_state": old_state,
                "to_state": new_state,
                "reason": reason,
            },
            org_id=org_id,
        )

    def log_authorization(
        self,
        connector_id: str,
        user_id: str,
        org_id: str,
        auth_mode: str,
        granted: bool,
        reason: str = "",
    ) -> None:
        """Log whether credentials could be prepared for a connector call."""
        self.log_event(
            event_type=AuditEventType.AUTH_GRANTED if granted else AuditEventType.AUTH_DENIED,
            actor=user_id,
            resource_type="connector",
            resource_id=connector_id,
            action="prepare_credentials",
            result="granted" if granted else "denied",
            metadata={"auth_mode": auth_mode, "reason": reason},
            org_id=org_id,
        )

    def log_token_refresh(
        self,
        connector_id: str,
        user_id: str,
        org_id: str,
        success: bool,
    ) -> None:
        """Log an OAuth refresh attempt. Never records token values."""
        self.log_event(
            event_type=AuditEventType.TOKEN_REFRESHED,
            actor=user_id,
            resource_type="connector",
            resource_id=connector_id,
            action="refresh",
            result="success" if success else "failed",
            org_id=org_id,
        )

    def _sanitize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Remove sensitive information from metadata.
        
        Args:
            metadata: Raw metadata
            
        Returns:
            Sanitized metadata
        """
        # List of sensitive keys to remove
        sensitive_keys = [
            "password",
            "secret",
            "token",
            "api_key",
            "access_token",
            "refresh_token",
            "private_key",
            "credential",
        ]
        
        sanitized = {}
        for key, value in metadata.items():
            # Check if key contains sensitive terms
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _write_to_file(self, event: dict[str, Any]) -> None:
        """Write audit event to file."""
        if self.log_file is None:
            return
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log to file: {e}")
    
    def get_events(
        self,
        event_type: AuditEventType | None = None,
        actor: str | None = None,
        org_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Query audit events.
        
        Args:
            event_type: Filter by event type
            actor: Filter by actor
            org_id: Filter by organization
            limit: Maximum number of events to return
            
        Returns:
            List of audit events
        """
        filtered = self._audit_events
        
        if event_type:
            filtered = [e for e in filtered if e["event_type"] == event_type.value]
        
        if actor:
            filtered = [e for e in filtered if e["actor"] == actor]
        
        if org_id:
            filtered = [e for e in filtered if e.get("org_id") == org_id]
        
        # Return most recent first
        return list(reversed(filtered))[:limit]
    
    def get_stats(self) -> dict[str, Any]:
        """Get audit statistics."""
        total_events = len(self._audit_events)
        
        # Count by event type
        by_type: dict[str, int] = {}
        for event in self._audit_events:
            event_type = event["event_type"]
            by_type[event_type] = by_type.get(event_type, 0) + 1
        
        # Count by result
        by_result: dict[str, int] = {}
        for event in self._audit_events:
            result = event["result"]
            by_result[result] = by_result.get(result, 0) + 1
        
        return {
            "total_events": total_events,
            "by_type": by_type,
            "by_result": by_result,
        }
