"""
Trust Level Models for MCP Connector Governance

Implements the 4-tier trust classification system:
- L1: Platform Managed (0.5x weight)
- L2: Org Verified (1.0x weight)
- L3: Restricted Conditional (3.0x weight)
- L4: Unverified/Untrusted (5.0x weight)
"""

from dataclasses import dataclass
from enum import Enum, auto


class TrustLevel(Enum):
    """Four-tier trust classification for MCP connectors."""
    
    L1_PLATFORM_MANAGED = 1          # Platform-curated, fully verified
    L2_ORG_VERIFIED = 2              # Organization verified connectors
    L3_RESTRICTED_CONDITIONAL = 3    # Restricted with conditional access
    L4_UNVERIFIED_UNTRUSTED = 4      # Untrusted/unverified - test sandbox only


class ExecutionEnvironment(Enum):
    """Where tool calls run. Fail-closed default is PRODUCTION."""

    PRODUCTION = "production"
    ISOLATED_EVALUATION = "isolated_evaluation"  # dedicated sandbox, synthetic data only


class ApprovalType(Enum):
    """Types of approval required for trust levels."""
    
    NONE = auto()                    # No approval needed
    TWO_PERSON = auto()              # 2-person approval
    SECURITY_LEAD = auto()           # Org Security Lead approval
    TASK_SPECIFIC = auto()           # Task-specific exception approval


@dataclass
class TrustLevelConfig:
    """Configuration for each trust level."""
    
    level: TrustLevel
    quota_weight: float              # Relative quota weight
    approval_type: ApprovalType
    requires_version_pin: bool       # Must version-pin connectors
    audit_frequency: str             # Annual, quarterly, per-task, etc.
    allowed_sandbox: bool            # Can run in sandbox
    allowed_production: bool         # Can run in production
    requires_signature: bool         # Must be cryptographically signed
    signature_algo: str | None    # SHA256, GPG, Sigstore, etc.
    max_task_ttl: int | None     # Max TTL in seconds (None = unlimited)
    isolation_level: str             # process, container, vm
    
    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.quota_weight <= 0:
            raise ValueError(f"quota_weight must be positive, got {self.quota_weight}")
        
        if not self.allowed_sandbox and not self.allowed_production:
            raise ValueError(f"Trust level {self.level} must allow at least sandbox or production")


# Default configurations for each trust level
TRUST_LEVEL_CONFIGS = {
    TrustLevel.L1_PLATFORM_MANAGED: TrustLevelConfig(
        level=TrustLevel.L1_PLATFORM_MANAGED,
        quota_weight=0.5,
        approval_type=ApprovalType.TWO_PERSON,
        requires_version_pin=True,
        audit_frequency="annual",
        allowed_sandbox=True,
        allowed_production=True,
        requires_signature=True,
        signature_algo="SHA256",  # Primary with GPG/Sigstore fallback
        max_task_ttl=None,
        isolation_level="process",
    ),
    TrustLevel.L2_ORG_VERIFIED: TrustLevelConfig(
        level=TrustLevel.L2_ORG_VERIFIED,
        quota_weight=1.0,
        approval_type=ApprovalType.SECURITY_LEAD,
        requires_version_pin=True,
        audit_frequency="quarterly",
        allowed_sandbox=True,
        allowed_production=True,
        requires_signature=True,
        signature_algo="SHA256",
        max_task_ttl=None,
        isolation_level="process",
    ),
    TrustLevel.L3_RESTRICTED_CONDITIONAL: TrustLevelConfig(
        level=TrustLevel.L3_RESTRICTED_CONDITIONAL,
        quota_weight=3.0,
        approval_type=ApprovalType.TASK_SPECIFIC,
        requires_version_pin=False,
        audit_frequency="per_task",
        allowed_sandbox=True,
        allowed_production=False,  # No production use
        requires_signature=False,
        signature_algo=None,
        max_task_ttl=3600,  # 1 hour
        isolation_level="container",
    ),
    TrustLevel.L4_UNVERIFIED_UNTRUSTED: TrustLevelConfig(
        level=TrustLevel.L4_UNVERIFIED_UNTRUSTED,
        quota_weight=5.0,
        approval_type=ApprovalType.NONE,
        requires_version_pin=False,
        audit_frequency="per_task",
        allowed_sandbox=True,
        allowed_production=False,
        requires_signature=False,
        signature_algo=None,
        max_task_ttl=600,  # 10 minutes
        isolation_level="vm",  # Strongest isolation for untrusted
    ),
}


def get_trust_level_config(level: TrustLevel) -> TrustLevelConfig:
    """Retrieve configuration for a trust level."""
    config = TRUST_LEVEL_CONFIGS.get(level)
    if not config:
        raise ValueError(f"Unknown trust level: {level}")
    return config


def classify_trust_level(
    is_platform_managed: bool = False,
    is_org_verified: bool = False,
    has_signature: bool = False,
    has_version_pin: bool = False,
) -> TrustLevel:
    """
    Classify connector into trust level based on attributes.
    
    Priority: Platform > Org > Restricted > Untrusted
    """
    if is_platform_managed:
        return TrustLevel.L1_PLATFORM_MANAGED
    
    if is_org_verified:
        return TrustLevel.L2_ORG_VERIFIED
    
    if has_signature and has_version_pin:
        return TrustLevel.L3_RESTRICTED_CONDITIONAL
    
    return TrustLevel.L4_UNVERIFIED_UNTRUSTED
