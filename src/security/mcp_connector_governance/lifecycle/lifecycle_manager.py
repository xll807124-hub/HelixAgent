"""
Lifecycle Manager

Manages connector lifecycle state transitions and health monitoring.
"""

import logging
from contextlib import nullcontext
from datetime import datetime

from ..audit.audit_logger import AuditLogger
from ..authorization.auth_manager import AuthorizationManager
from ..models import (
    AuthenticationMode,
    Connector,
    ConnectorLifecycleState,
)
from ..registry import ConnectorRegistry
from ..registry.signature_verifier import check_signature_gate

logger = logging.getLogger(__name__)

# 进入这些状态前必须通过签名闸门
_SIGNATURE_GATED_STATES = frozenset({
    ConnectorLifecycleState.APPROVED_INACTIVE,
    ConnectorLifecycleState.ACTIVE,
})


class LifecycleManager:
    """
    Manages MCP connector lifecycle states.
    
    State flow:
    DRAFT -> PENDING_VERIFICATION -> PENDING_APPROVAL -> APPROVED_INACTIVE -> ACTIVE
    
    Transitions from ACTIVE:
    - PENDING_REVIEW (schema change detected)
    - RESTRICTED (policy violation)
    - HEALTH_ANOMALY (health check failure)
    - PAUSED (manual pause)
    - REVOKED (security incident)
    - EXPIRED (approval/certificate expiry)
    """
    
    def __init__(
        self,
        registry: ConnectorRegistry,
        audit_logger: AuditLogger | None = None,
        authorization_manager: AuthorizationManager | None = None,
    ) -> None:
        """
        Args:
            registry: Connector registry
            audit_logger: 提供时，所有状态转换（含被拒绝的尝试）都会写入审计
        """
        self.registry = registry
        with registry.lifecycle_lock:
            if authorization_manager is not None:
                if (registry.authorization_manager is not None
                        and registry.authorization_manager is not authorization_manager):
                    raise ValueError("Registry already has an authorization manager")
                registry.authorization_manager = authorization_manager
        self.audit_logger = audit_logger
        self._state_transition_log: list[dict] = []

    def _audit(
        self,
        connector: Connector,
        old_state: ConnectorLifecycleState,
        new_state: ConnectorLifecycleState,
        actor: str,
        reason: str,
        result: str,
    ) -> None:
        """Write a lifecycle audit event; audit failures never block the transition."""
        if self.audit_logger is None:
            return
        try:
            self.audit_logger.log_lifecycle_transition(
                connector_id=connector.connector_id,
                old_state=old_state.value,
                new_state=new_state.value,
                actor=actor,
                reason=reason,
                result=result,
                org_id=connector.config.identity.organization_id,
            )
        except Exception as exc:
            logger.error(f"Audit logging failed: {type(exc).__name__}")
    
    def transition_to(
        self, connector_id: str, new_state: ConnectorLifecycleState, reason: str,
        triggered_by: str = "system",
        *, _defer_credential_cleanup: bool = False,
    ) -> bool:
        """Apply local stop before revocation IO. A True result only confirms state change."""
        if not isinstance(new_state, ConnectorLifecycleState) or not reason or not triggered_by:
            return False
        manager = self.registry.authorization_manager
        callable_target = new_state in (
            ConnectorLifecycleState.ACTIVE, ConnectorLifecycleState.RESTRICTED,
        )
        # Refresh provider acknowledgement outside the lifecycle/cache critical section.
        candidate = self.registry.get(connector_id)
        if callable_target and candidate is not None:
            self.get_credential_invalidation_status(
                connector_id, org_id=candidate.config.identity.organization_id,
            )
        with self.registry.lifecycle_lock, manager._lock if manager else nullcontext():
            connector = self.registry.get(connector_id)
            if connector is None:
                return False
            org_id = connector.config.identity.organization_id
            old_state = connector.lifecycle_state
            if (callable_target and self.registry.tool_governance is not None
                    and not self.registry.tool_governance.can_activate(connector)):
                return False
            if callable_target and connector.status.credential_invalidation is not None:
                outcome = connector.status.credential_invalidation
                if not outcome["local_invalidated"]:
                    return False
                if outcome["credential_revocation_status"] not in ("not_required", "complete"):
                    return False
            repeated_stop = (not callable_target and connector.lifecycle_state == new_state
                             and connector.status.credential_invalidation is not None)
            if not repeated_stop and not self._transition_state(
                connector_id, new_state, reason, triggered_by,
            ):
                return False
            if callable_target:
                return True
            # Initial registration/approval has not enabled the connector yet.
            # It must not be treated as a stop of an externally authorized connector.
            if (old_state in (ConnectorLifecycleState.DRAFT,
                              ConnectorLifecycleState.PENDING_VERIFICATION,
                              ConnectorLifecycleState.PENDING_APPROVAL)
                    and new_state in (ConnectorLifecycleState.PENDING_VERIFICATION,
                                      ConnectorLifecycleState.PENDING_APPROVAL,
                                      ConnectorLifecycleState.APPROVED_INACTIVE)
                    and connector.status.credential_invalidation is None):
                return True
            if repeated_stop:
                connector.status.credential_generation += 1
            if manager is None:
                no_credentials = connector.config.auth.mode == AuthenticationMode.NONE
                connector.status.credential_invalidation = {
                    "connector_id": connector_id, "org_id": org_id,
                    "generation": connector.status.credential_generation,
                    "local_invalidated": no_credentials, "cleared_count": 0,
                    "credential_revocation_status": "not_required" if no_credentials
                    else "unconfigured", "pending_count": 0, "retryable": False,
                    "audit_recorded": False, "error_code": None if no_credentials
                    else "authorization_manager_unconfigured",
                }
                return True
            try:
                prior = connector.status.credential_invalidation or {}
                connector.status.credential_invalidation = manager.begin_invalidation(
                    connector_id, org_id, connector.config.auth.mode,
                    prior_unconfigured=prior.get("credential_revocation_status") == "unconfigured",
                )
            except Exception:
                connector.status.credential_invalidation = {
                    "connector_id": connector_id, "org_id": org_id,
                    "generation": connector.status.credential_generation,
                    "local_invalidated": False, "cleared_count": 0,
                    "credential_revocation_status": "partial", "pending_count": 1,
                    "retryable": True, "audit_recorded": False,
                    "error_code": "local_invalidation_failed",
                }
                return True  # Never undo the already-applied local stop.
        # No lifecycle/cache lock is held while a provider is contacted.
        if not _defer_credential_cleanup:
            self.complete_credential_invalidation(connector_id, triggered_by)
        return True

    def complete_credential_invalidation(self, connector_id: str, actor: str) -> None:
        """Finish a deferred local stop outside lifecycle/cache locks."""
        with self.registry.lifecycle_lock:
            connector = self.registry.get(connector_id)
            manager = self.registry.authorization_manager
            if (connector is None or manager is None
                    or connector.status.credential_invalidation is None):
                return
            org_id = connector.config.identity.organization_id
            if not connector.status.credential_invalidation["local_invalidated"]:
                return
        outcome = manager.finish_invalidation(connector_id, org_id, actor, retry=True)
        with self.registry.lifecycle_lock:
            if outcome["generation"] == manager.get_credential_generation(connector_id, org_id):
                connector.status.credential_invalidation = outcome

    def get_credential_invalidation_status(
        self, connector_id: str, *, org_id: str,
    ) -> dict | None:
        with self.registry.lifecycle_lock:
            connector = self.registry.get(connector_id)
            if connector is None or connector.config.identity.organization_id != org_id:
                return None
            result = connector.status.credential_invalidation
            if result is None:
                return None
            manager = self.registry.authorization_manager
        if manager is not None and result["local_invalidated"]:
            with manager._lock:
                owned = (org_id, connector_id) in manager._invalidations
            if owned:
                result = manager.finish_invalidation(connector_id, org_id, "system")
                with self.registry.lifecycle_lock:
                    if result["generation"] == manager.get_credential_generation(
                        connector_id, org_id,
                    ):
                        connector.status.credential_invalidation = result
        return dict(result)

    def _transition_state(
        self,
        connector_id: str,
        new_state: ConnectorLifecycleState,
        reason: str,
        triggered_by: str = "system",
    ) -> bool:
        """
        Transition connector to new state.
        
        Args:
            connector_id: Connector ID
            new_state: Target state
            reason: Reason for transition
            triggered_by: User/system triggering transition
            
        Returns:
            True if transition succeeded
        """
        connector = self.registry.get(connector_id)
        if not connector:
            logger.error(f"Cannot transition unknown connector {connector_id}")
            return False
        
        old_state = connector.lifecycle_state
        
        # Validate transition
        if not self._is_valid_transition(old_state, new_state):
            logger.warning(
                f"Invalid state transition for {connector_id}: "
                f"{old_state.value} -> {new_state.value}"
            )
            self._audit(
                connector, old_state, new_state, triggered_by,
                "Invalid state transition", "denied",
            )
            return False
        
        # Signature gate: 要求签名的信任等级，必须有有效且与当前配置一致的签名，
        # 才能进入可调用/待激活状态（fail-closed）。
        if new_state in _SIGNATURE_GATED_STATES:
            gate_error = check_signature_gate(connector)
            if gate_error:
                logger.warning(
                    f"Transition blocked by signature gate for {connector_id}: "
                    f"{old_state.value} -> {new_state.value} ({gate_error})"
                )
                self._log_transition(
                    connector_id=connector_id,
                    old_state=old_state,
                    new_state=old_state,
                    reason=f"Blocked by signature gate: {gate_error}",
                    triggered_by=triggered_by,
                )
                self._audit(
                    connector, old_state, new_state, triggered_by,
                    f"Blocked by signature gate: {gate_error}", "denied",
                )
                return False
        
        # Only unblock credentials after the transition and signature gates have passed.
        manager = self.registry.authorization_manager
        if new_state in (ConnectorLifecycleState.ACTIVE, ConnectorLifecycleState.RESTRICTED):
            if manager is not None and not manager.resume_credentials(
                connector_id, connector.config.identity.organization_id,
            ):
                return False
        # Perform transition
        self.registry.update_status(
            connector_id=connector_id,
            new_state=new_state,
            reason=reason,
            changed_by=triggered_by,
        )
        
        # Log transition
        self._log_transition(
            connector_id=connector_id,
            old_state=old_state,
            new_state=new_state,
            reason=reason,
            triggered_by=triggered_by,
        )
        self._audit(connector, old_state, new_state, triggered_by, reason, "success")
        
        logger.info(
            f"Connector {connector_id} transitioned: "
            f"{old_state.value} -> {new_state.value} (reason: {reason})"
        )
        
        return True
    
    def activate(
        self,
        connector_id: str,
        activated_by: str,
    ) -> bool:
        """
        Activate a connector (transition to ACTIVE state).
        
        Args:
            connector_id: Connector ID
            activated_by: User activating the connector
            
        Returns:
            True if activation succeeded
        """
        connector = self.registry.get(connector_id)
        if not connector:
            return False
        
        # Only activate from APPROVED_INACTIVE
        if connector.lifecycle_state != ConnectorLifecycleState.APPROVED_INACTIVE:
            logger.warning(
                f"Cannot activate connector {connector_id} from state "
                f"{connector.lifecycle_state.value}"
            )
            return False
        
        return self.transition_to(
            connector_id=connector_id,
            new_state=ConnectorLifecycleState.ACTIVE,
            reason="Connector activated",
            triggered_by=activated_by,
        )
    
    def pause(
        self,
        connector_id: str,
        reason: str,
        paused_by: str,
    ) -> bool:
        """
        Pause an active connector.
        
        Args:
            connector_id: Connector ID
            reason: Reason for pausing
            paused_by: User pausing the connector
            
        Returns:
            True if pause succeeded
        """
        return self.transition_to(
            connector_id=connector_id,
            new_state=ConnectorLifecycleState.PAUSED,
            reason=reason,
            triggered_by=paused_by,
        )
    
    def resume(
        self,
        connector_id: str,
        resumed_by: str,
    ) -> bool:
        """
        Resume a paused connector.
        
        Args:
            connector_id: Connector ID
            resumed_by: User resuming the connector
            
        Returns:
            True if resume succeeded
        """
        connector = self.registry.get(connector_id)
        if not connector:
            return False
        
        if connector.lifecycle_state != ConnectorLifecycleState.PAUSED:
            logger.warning(
                f"Cannot resume connector {connector_id} from state "
                f"{connector.lifecycle_state.value}"
            )
            return False
        
        return self.transition_to(
            connector_id=connector_id,
            new_state=ConnectorLifecycleState.ACTIVE,
            reason="Connector resumed",
            triggered_by=resumed_by,
        )
    
    def revoke(
        self,
        connector_id: str,
        reason: str,
        revoked_by: str,
    ) -> bool:
        """
        Revoke a connector (security incident, policy violation).
        
        Args:
            connector_id: Connector ID
            reason: Reason for revocation
            revoked_by: User/system revoking the connector
            
        Returns:
            True if revocation succeeded
        """
        return self.transition_to(
            connector_id=connector_id,
            new_state=ConnectorLifecycleState.REVOKED,
            reason=reason,
            triggered_by=revoked_by,
        )
    
    def mark_for_review(
        self,
        connector_id: str,
        reason: str,
    ) -> bool:
        """
        Mark connector for review (e.g., schema change detected).
        
        Args:
            connector_id: Connector ID
            reason: Reason for review
            
        Returns:
            True if marking succeeded
        """
        return self.transition_to(
            connector_id=connector_id,
            new_state=ConnectorLifecycleState.PENDING_REVIEW,
            reason=reason,
            triggered_by="lifecycle_manager",
        )
    
    def handle_health_anomaly(
        self,
        connector_id: str,
        health_issue: str,
    ) -> bool:
        """
        Handle health check failure.
        
        Args:
            connector_id: Connector ID
            health_issue: Description of health issue
            
        Returns:
            True if handled successfully
        """
        connector = self.registry.get(connector_id)
        if not connector:
            return False
        
        # Only transition if currently ACTIVE
        if connector.lifecycle_state != ConnectorLifecycleState.ACTIVE:
            return False
        
        return self.transition_to(
            connector_id=connector_id,
            new_state=ConnectorLifecycleState.HEALTH_ANOMALY,
            reason=f"Health check failed: {health_issue}",
            triggered_by="health_monitor",
        )
    
    def check_expiry(self, connector_id: str) -> bool:
        """
        Check if connector approvals or certificates have expired.
        
        Args:
            connector_id: Connector ID
            
        Returns:
            True if connector expired and transitioned to EXPIRED state
        """
        connector = self.registry.get(connector_id)
        if not connector:
            return False
        
        # Check signature expiry
        signature = connector.config.signature
        if signature and not signature.is_valid():
            self.transition_to(
                connector_id=connector_id,
                new_state=ConnectorLifecycleState.EXPIRED,
                reason=f"Signature expired: {signature.verification_status}",
                triggered_by="lifecycle_manager",
            )
            return True
        
        return False
    
    def _is_valid_transition(
        self,
        from_state: ConnectorLifecycleState,
        to_state: ConnectorLifecycleState,
    ) -> bool:
        """
        Check if state transition is valid.
        
        Args:
            from_state: Current state
            to_state: Target state
            
        Returns:
            True if transition is valid
        """
        # Define valid transitions
        valid_transitions = {
            ConnectorLifecycleState.DRAFT: [
                ConnectorLifecycleState.PENDING_VERIFICATION,
            ],
            ConnectorLifecycleState.PENDING_VERIFICATION: [
                ConnectorLifecycleState.PENDING_APPROVAL,
                ConnectorLifecycleState.DRAFT,
                ConnectorLifecycleState.REVOKED,
            ],
            ConnectorLifecycleState.PENDING_APPROVAL: [
                ConnectorLifecycleState.APPROVED_INACTIVE,
                ConnectorLifecycleState.PENDING_VERIFICATION,
                ConnectorLifecycleState.REVOKED,
            ],
            ConnectorLifecycleState.APPROVED_INACTIVE: [
                ConnectorLifecycleState.ACTIVE,
                ConnectorLifecycleState.REVOKED,
                ConnectorLifecycleState.EXPIRED,
            ],
            ConnectorLifecycleState.ACTIVE: [
                ConnectorLifecycleState.PENDING_REVIEW,
                ConnectorLifecycleState.RESTRICTED,
                ConnectorLifecycleState.HEALTH_ANOMALY,
                ConnectorLifecycleState.PAUSED,
                ConnectorLifecycleState.REVOKED,
                ConnectorLifecycleState.EXPIRED,
            ],
            ConnectorLifecycleState.PENDING_REVIEW: [
                ConnectorLifecycleState.ACTIVE,
                ConnectorLifecycleState.RESTRICTED,
                ConnectorLifecycleState.REVOKED,
            ],
            ConnectorLifecycleState.RESTRICTED: [
                ConnectorLifecycleState.PENDING_REVIEW,
                ConnectorLifecycleState.ACTIVE,
                ConnectorLifecycleState.REVOKED,
                ConnectorLifecycleState.PAUSED,
            ],
            ConnectorLifecycleState.HEALTH_ANOMALY: [
                ConnectorLifecycleState.ACTIVE,
                ConnectorLifecycleState.PAUSED,
                ConnectorLifecycleState.REVOKED,
            ],
            ConnectorLifecycleState.PAUSED: [
                ConnectorLifecycleState.ACTIVE,
                ConnectorLifecycleState.REVOKED,
            ],
            ConnectorLifecycleState.REVOKED: [],  # Terminal state
            ConnectorLifecycleState.EXPIRED: [
                ConnectorLifecycleState.PENDING_VERIFICATION,  # Can re-verify
            ],
        }
        
        allowed_states = valid_transitions.get(from_state, [])
        return to_state in allowed_states
    
    def _log_transition(
        self,
        connector_id: str,
        old_state: ConnectorLifecycleState,
        new_state: ConnectorLifecycleState,
        reason: str,
        triggered_by: str,
    ) -> None:
        """Log state transition for auditing."""
        self._state_transition_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "connector_id": connector_id,
            "old_state": old_state.value,
            "new_state": new_state.value,
            "reason": reason,
            "triggered_by": triggered_by,
        })
    
    def get_transition_history(
        self,
        connector_id: str | None = None,
    ) -> list[dict]:
        """
        Get state transition history.
        
        Args:
            connector_id: Optional connector ID to filter by
            
        Returns:
            List of transition records
        """
        if connector_id:
            return [
                log for log in self._state_transition_log
                if log["connector_id"] == connector_id
            ]
        return self._state_transition_log.copy()
