"""
MCP Connector Governance Models

Core data models for connector identity, tools, trust levels, and lifecycle.
"""

from .connector import (
    AuthConfig,
    AuthenticationMode,
    Connector,
    ConnectorConfig,
    ConnectorIdentity,
    ConnectorLifecycleState,
    ConnectorStatus,
    SignatureVerification,
    TransportConfig,
    TransportType,
)
from .tool_schema import (
    ToolApproval,
    ToolCapability,
    ToolInputSchema,
    ToolRiskProfile,
    ToolSchema,
)
from .trust_level import (
    TRUST_LEVEL_CONFIGS,
    ApprovalType,
    ExecutionEnvironment,
    TrustLevel,
    TrustLevelConfig,
    classify_trust_level,
    get_trust_level_config,
)

__all__ = [
    # Trust Level
    "TrustLevel",
    "ExecutionEnvironment",
    "ApprovalType",
    "TrustLevelConfig",
    "TRUST_LEVEL_CONFIGS",
    "get_trust_level_config",
    "classify_trust_level",
    # Tool Schema
    "ToolInputSchema",
    "ToolRiskProfile",
    "ToolCapability",
    "ToolSchema",
    "ToolApproval",
    # Connector
    "TransportType",
    "AuthenticationMode",
    "ConnectorLifecycleState",
    "ConnectorIdentity",
    "TransportConfig",
    "AuthConfig",
    "SignatureVerification",
    "ConnectorConfig",
    "ConnectorStatus",
    "Connector",
]
