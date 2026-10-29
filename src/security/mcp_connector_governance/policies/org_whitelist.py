"""
Org-level Whitelist Policy for MCP Connectors
Provides optional organizational allowlist with capability trimming
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class WhitelistScope(Enum):
    """Whitelist scope"""

    INCLUDE = "include"  # Only allow listed tools
    EXCLUDE = "exclude"  # Block listed tools


@dataclass
class OrgCapabilityTrim:
    """Capability trimming rules for an org"""

    tool_id: str
    allowed_methods: list[str] | None = None  # If None, all methods allowed
    parameter_restrictions: dict[str, list[str]] = field(
        default_factory=dict
    )  # param -> allowed values
    rate_limit: int | None = None  # Calls per hour
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OrgWhitelistEntry:
    """Single org whitelist entry"""

    org_id: str
    connector_id: str
    trust_level_min: int  # Minimum trust level required
    capability_trims: list[OrgCapabilityTrim] = field(default_factory=list)
    scope: WhitelistScope = WhitelistScope.INCLUDE
    expires_at: datetime | None = None
    reason: str = ""
    approved_by: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def is_expired(self) -> bool:
        """Check if entry is expired"""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at


class OrgWhitelistPolicy:
    """
    Organization-level whitelist policy.
    Optional override to global blacklist with capability trimming.
    """

    def __init__(self) -> None:
        self.whitelists: dict[
            str, dict[str, OrgWhitelistEntry]
        ] = {}  # org_id -> connector_id -> entry
        self.audit_log: list[dict] = []

    def add_whitelist_entry(
        self,
        org_id: str,
        connector_id: str,
        trust_level_min: int,
        scope: WhitelistScope = WhitelistScope.INCLUDE,
        expires_at: datetime | None = None,
        reason: str = "",
        approved_by: str = "",
    ) -> OrgWhitelistEntry:
        """Add org whitelist entry"""
        if org_id not in self.whitelists:
            self.whitelists[org_id] = {}

        entry = OrgWhitelistEntry(
            org_id=org_id,
            connector_id=connector_id,
            trust_level_min=trust_level_min,
            scope=scope,
            expires_at=expires_at,
            reason=reason,
            approved_by=approved_by,
        )

        self.whitelists[org_id][connector_id] = entry
        self._log_audit("whitelist_added", org_id, connector_id, approved_by)
        return entry

    def add_capability_trim(
        self,
        org_id: str,
        connector_id: str,
        tool_id: str,
        allowed_methods: list[str] | None = None,
        parameter_restrictions: dict[str, list[str]] | None = None,
        rate_limit: int | None = None,
    ) -> OrgCapabilityTrim | None:
        """Add capability trimming rule for a tool"""
        if org_id not in self.whitelists or connector_id not in self.whitelists[org_id]:
            return None

        trim = OrgCapabilityTrim(
            tool_id=tool_id,
            allowed_methods=allowed_methods,
            parameter_restrictions=parameter_restrictions or {},
            rate_limit=rate_limit,
        )

        self.whitelists[org_id][connector_id].capability_trims.append(trim)
        self._log_audit("capability_trim_added", org_id, connector_id, tool_id)
        return trim

    def get_whitelist_entry(self, org_id: str, connector_id: str) -> OrgWhitelistEntry | None:
        """Retrieve whitelist entry"""
        if org_id not in self.whitelists:
            return None
        entry = self.whitelists[org_id].get(connector_id)
        if entry and not entry.is_expired():
            return entry
        return None

    def is_connector_whitelisted(self, org_id: str, connector_id: str) -> bool:
        """Check if connector is whitelisted for org"""
        entry = self.get_whitelist_entry(org_id, connector_id)
        if entry is None:
            return False
        return entry.scope == WhitelistScope.INCLUDE

    def get_capability_trims(self, org_id: str, connector_id: str) -> list[OrgCapabilityTrim]:
        """Get all capability trims for connector in org"""
        entry = self.get_whitelist_entry(org_id, connector_id)
        if entry is None:
            return []
        return entry.capability_trims

    def remove_whitelist_entry(self, org_id: str, connector_id: str, removed_by: str = "") -> bool:
        """Remove whitelist entry"""
        if org_id not in self.whitelists or connector_id not in self.whitelists[org_id]:
            return False
        del self.whitelists[org_id][connector_id]
        self._log_audit("whitelist_removed", org_id, connector_id, removed_by)
        return True

    def list_org_whitelists(self, org_id: str) -> list[OrgWhitelistEntry]:
        """List all whitelist entries for an org"""
        if org_id not in self.whitelists:
            return []
        return [entry for entry in self.whitelists[org_id].values() if not entry.is_expired()]

    def get_audit_log(self) -> list[dict]:
        """Get audit log"""
        return self.audit_log.copy()

    def _log_audit(
        self, action: str, org_id: str, connector_id: str, actor: str = "", detail: str = ""
    ) -> None:
        """Log audit event"""
        self.audit_log.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "action": action,
                "org_id": org_id,
                "connector_id": connector_id,
                "actor": actor,
                "detail": detail,
            }
        )
