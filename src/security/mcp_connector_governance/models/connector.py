"""
MCP Connector Models

Core connector identity, configuration, and lifecycle state.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .tool_schema import ToolSchema
from .trust_level import TrustLevel


class TransportType(Enum):
    """MCP transport protocol."""

    HTTP = "http"
    STDIO = "stdio"
    SSE = "sse"


class AuthenticationMode(Enum):
    """Authentication mode for connector."""

    OAUTH2_PKCE = "oauth2_pkce"  # OAuth 2.1 with PKCE (mandatory)
    API_KEY = "api_key"  # @deprecated - sunset 2027-12-31
    BEARER_TOKEN = "bearer_token"
    MTLS = "mtls"
    NONE = "none"


class ConnectorLifecycleState(Enum):
    """
    Connector lifecycle states.

    State transitions:
    DRAFT -> PENDING_VERIFICATION -> PENDING_APPROVAL -> APPROVED_INACTIVE -> ACTIVE
    ACTIVE -> PENDING_REVIEW (on schema change)
    ACTIVE -> RESTRICTED (on policy violation)
    ACTIVE -> HEALTH_ANOMALY (on health check failure)
    ACTIVE -> PAUSED (manual pause)
    * -> REVOKED (security incident)
    * -> EXPIRED (approval/cert expiry)
    """

    DRAFT = "draft"
    PENDING_VERIFICATION = "pending_verification"
    PENDING_APPROVAL = "pending_approval"
    APPROVED_INACTIVE = "approved_inactive"
    ACTIVE = "active"
    PENDING_REVIEW = "pending_review"
    RESTRICTED = "restricted"
    HEALTH_ANOMALY = "health_anomaly"
    PAUSED = "paused"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass
class ConnectorIdentity:
    """Stable identity for an MCP connector."""

    connector_id: str  # Platform-assigned stable ID: conn_<uuid>
    organization_id: str
    namespace: str  # Publisher namespace: "github", "anthropic", etc.
    display_name: str
    version: str  # Connector version: "1.0.0"
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str = ""  # User ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "organization_id": self.organization_id,
            "namespace": self.namespace,
            "display_name": self.display_name,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }


@dataclass
class TransportConfig:
    """Transport configuration for connector."""

    type: TransportType
    endpoint: str | None = None  # HTTP/SSE endpoint
    command: str | None = None  # STDIO command
    args: list[str] = field(default_factory=list)  # STDIO args
    env: dict[str, str] = field(default_factory=dict)  # Environment variables
    timeout_seconds: int = 30

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "endpoint": self.endpoint,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass
class AuthConfig:
    """Authentication configuration (credentials excluded)."""

    mode: AuthenticationMode

    # OAuth 2.1 with PKCE
    oauth_client_id: str | None = None
    oauth_authorization_endpoint: str | None = None
    oauth_token_endpoint: str | None = None
    oauth_revocation_endpoint: str | None = None
    oauth_audience: str | None = None  # Audience binding to prevent token passthrough
    oauth_scopes: list[str] = field(default_factory=list)

    # API Key (@deprecated)
    api_key_ref: str | None = None  # Reference to credential vault (not the key itself)
    api_key_deprecation_date: str = "2027-12-31"

    # mTLS
    certificate_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return sanitized config (no secrets)."""
        return {
            "mode": self.mode.value,
            "oauth_client_id": self.oauth_client_id,
            "oauth_authorization_endpoint": self.oauth_authorization_endpoint,
            "oauth_token_endpoint": self.oauth_token_endpoint,
            "oauth_revocation_endpoint": self.oauth_revocation_endpoint,
            "oauth_audience": self.oauth_audience,
            "oauth_scopes": self.oauth_scopes,
            "api_key_ref": self.api_key_ref,
            "api_key_deprecation_date": self.api_key_deprecation_date,
            "certificate_fingerprint": self.certificate_fingerprint,
        }


@dataclass
class SignatureVerification:
    """Cryptographic signature verification result."""

    is_signed: bool
    signature_format: str | None = None  # "sigstore_oidc", "gpg", "pkcs7"
    signer_identity: str | None = None  # Email, org name, GitHub Actions OIDC
    signed_at: datetime | None = None
    valid_until: datetime | None = None
    verification_status: str = "unknown"  # "valid", "invalid", "expired", "revoked"
    signature_digest: str | None = None  # SHA256 of signed content

    def is_valid(self, now: datetime | None = None) -> bool:
        """Check if signature is currently valid."""
        if not self.is_signed:
            return False
        if self.verification_status != "valid":
            return False
        if self.valid_until:
            now = now or datetime.utcnow()
            if now > self.valid_until:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_signed": self.is_signed,
            "signature_format": self.signature_format,
            "signer_identity": self.signer_identity,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "verification_status": self.verification_status,
            "signature_digest": self.signature_digest,
        }


@dataclass
class ConnectorConfig:
    """Complete connector configuration."""

    identity: ConnectorIdentity
    trust_level: TrustLevel
    transport: TransportConfig
    auth: AuthConfig
    signature: SignatureVerification
    tools: list[ToolSchema] = field(default_factory=list)

    # Metadata
    description: str = ""
    documentation_url: str | None = None
    support_email: str | None = None
    tags: list[str] = field(default_factory=list)

    def compute_tools_digest(self) -> str:
        """Compute aggregate digest of all tool schemas."""
        import hashlib
        import json

        tool_digests = sorted([t.compute_schema_digest() for t in self.tools])
        combined = json.dumps(tool_digests, sort_keys=True)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def get_tool(self, tool_name: str) -> ToolSchema | None:
        """Get tool by name."""
        for tool in self.tools:
            if tool.tool_name == tool_name:
                return tool
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "trust_level": self.trust_level.value,
            "transport": self.transport.to_dict(),
            "auth": self.auth.to_dict(),
            "signature": self.signature.to_dict(),
            "tools": [t.to_dict() for t in self.tools],
            "tools_digest": self.compute_tools_digest(),
            "description": self.description,
            "documentation_url": self.documentation_url,
            "support_email": self.support_email,
            "tags": self.tags,
        }


@dataclass
class ConnectorStatus:
    """Runtime status of a connector."""

    connector_id: str
    lifecycle_state: ConnectorLifecycleState

    # Health monitoring
    last_health_check: datetime | None = None
    health_status: str = "unknown"  # "healthy", "degraded", "unhealthy"
    consecutive_failures: int = 0

    # State transitions
    last_state_change: datetime = field(default_factory=datetime.utcnow)
    state_change_reason: str = ""
    state_changed_by: str = ""

    # Quota tracking
    quota_weight: float = 1.0
    current_quota_usage: float = 0.0

    # Append local fields to preserve existing positional constructor arguments.
    # This fence is not a distributed Runtime/Event schema.
    credential_generation: int = 0
    credential_invalidation: dict[str, Any] | None = None

    def is_callable(self) -> bool:
        """Check if connector can be invoked."""
        return self.lifecycle_state in [
            ConnectorLifecycleState.ACTIVE,
            ConnectorLifecycleState.RESTRICTED,  # Limited calls allowed
        ]

    def is_healthy(self) -> bool:
        """Check if connector is healthy."""
        return self.health_status == "healthy"

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "lifecycle_state": self.lifecycle_state.value,
            "last_health_check": self.last_health_check.isoformat()
            if self.last_health_check
            else None,
            "health_status": self.health_status,
            "consecutive_failures": self.consecutive_failures,
            "last_state_change": self.last_state_change.isoformat(),
            "state_change_reason": self.state_change_reason,
            "state_changed_by": self.state_changed_by,
            "quota_weight": self.quota_weight,
            "current_quota_usage": self.current_quota_usage,
            "credential_generation": self.credential_generation,
            "is_callable": self.is_callable(),
            "is_healthy": self.is_healthy(),
        }


@dataclass
class Connector:
    """Complete MCP Connector with config and runtime status."""

    config: ConnectorConfig
    status: ConnectorStatus

    def __post_init__(self) -> None:
        """Ensure connector_id matches between config and status."""
        if self.config.identity.connector_id != self.status.connector_id:
            raise ValueError(
                f"Connector ID mismatch: config={self.config.identity.connector_id}, "
                f"status={self.status.connector_id}"
            )

    @property
    def connector_id(self) -> str:
        return self.config.identity.connector_id

    @property
    def trust_level(self) -> TrustLevel:
        return self.config.trust_level

    @property
    def lifecycle_state(self) -> ConnectorLifecycleState:
        return self.status.lifecycle_state

    def get_available_tools(self) -> list[ToolSchema]:
        """Get tools available in current state."""
        if not self.status.is_callable():
            return []
        return self.config.tools

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "status": self.status.to_dict(),
        }
