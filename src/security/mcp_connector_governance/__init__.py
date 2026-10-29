"""
SEC-007: MCP Connector Governance Module

8层纵深防御架构：
1. 发现前过滤 (Pre-Discovery Filter)
2. 工具清单同步 (Tool Manifest Sync)
3. 能力裁剪 (Capability Trimming)
4. Policy 决策 (Policy Decision)
5. 凭据准备 (Credential Preparation)
6. 执行前复核 (Pre-Execution Review)
7. 工具执行 (Tool Execution)
8. 审计 (Audit)

信任等级体系 (L1-L4):
- L1: 平台托管/强验证 (0.5x quota weight)
- L2: 组织验证 (1.0x quota weight)
- L3: 受限/条件验证 (3.0x quota weight)
- L4: 未验证/不可信 (5.0x quota weight)
"""

from .audit import (
    AuditLogger,
)
from .authorization import (
    AuthorizationManager,
)
from .execution import (
    ToolExecutionResult,
    ToolExecutor,
)
from .lifecycle import (
    LifecycleManager,
)
from .models import (
    ApprovalType,
    AuthConfig,
    AuthenticationMode,
    Connector,
    ConnectorConfig,
    ConnectorIdentity,
    ConnectorLifecycleState,
    ConnectorStatus,
    SignatureVerification,
    ToolApproval,
    ToolCapability,
    # Tool Schema
    ToolInputSchema,
    ToolRiskProfile,
    ToolSchema,
    TransportConfig,
    # Connector
    TransportType,
    # Trust Level
    TrustLevel,
    TrustLevelConfig,
    classify_trust_level,
    get_trust_level_config,
)
from .persistence import (
    AuditRepository,
    ConnectorRepository,
    DatabaseSchema,
    QuotaRepository,
    ToolRepository,
)
from .policies import (
    BlacklistEntry,
    GlobalBlacklist,
    OrgCapabilityTrim,
    OrgWhitelistEntry,
    OrgWhitelistPolicy,
    PolicyDecision,
    PolicyEngine,
    QuotaConfig,
    QuotaManager,
    WhitelistScope,
)
from .protocol import (
    MCPProtocolHandler,
    MCPTransportHandler,
)
from .registry import (
    ConnectorRegistry,
    SignatureVerifier,
    ToolRegistry,
    compute_content_hash,
)
from .security import (
    GPGVerifier,
    InternalPKIVerifier,
    SignatureAlgorithm,
    SigstoreVerifier,
    UnifiedSignatureVerifier,
    VerificationResult,
)

__all__ = [
    # Models - Trust Level
    "TrustLevel",
    "ApprovalType",
    "TrustLevelConfig",
    "get_trust_level_config",
    "classify_trust_level",
    # Models - Tool Schema
    "ToolInputSchema",
    "ToolRiskProfile",
    "ToolCapability",
    "ToolSchema",
    "ToolApproval",
    # Models - Connector
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
    # Registry
    "ConnectorRegistry",
    "SignatureVerifier",
    "ToolRegistry",
    "compute_content_hash",
    # Authorization
    "AuthorizationManager",
    # Policies
    "GlobalBlacklist",
    "BlacklistEntry",
    "OrgWhitelistPolicy",
    "OrgWhitelistEntry",
    "OrgCapabilityTrim",
    "WhitelistScope",
    "QuotaManager",
    "QuotaConfig",
    "PolicyEngine",
    "PolicyDecision",
    # Lifecycle
    "LifecycleManager",
    # Execution
    "ToolExecutor",
    "ToolExecutionResult",
    # Audit
    "AuditLogger",
    # Protocol
    "MCPProtocolHandler",
    "MCPTransportHandler",
    # Persistence
    "ConnectorRepository",
    "ToolRepository",
    "QuotaRepository",
    "AuditRepository",
    "DatabaseSchema",
    # Security
    "SigstoreVerifier",
    "GPGVerifier",
    "InternalPKIVerifier",
    "UnifiedSignatureVerifier",
    "VerificationResult",
    "SignatureAlgorithm",
]

__version__ = "0.1.0-day1"
__status__ = "day1-implementation"
