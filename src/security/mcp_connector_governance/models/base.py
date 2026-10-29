"""
SEC-007: MCP 连接器治理 - 核心数据模型

包含：
- ConnectorIdentity: 连接器的稳定身份
- ConnectorVersion: 连接器版本与签名
- ToolSchema: 工具定义与权限
- TrustLevel: L1-L4 信任等级
- ConnectorLifecycle: 生命周期状态
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TransportType(str, Enum):
    """连接器传输类型"""

    HTTP = "http"
    STDIO = "stdio"
    SSE = "sse"


class AuthenticationMode(str, Enum):
    """认证模式"""

    OAUTH2_PKCE = "oauth2_pkce"  # OAuth 2.1 PKCE flow
    API_KEY = "api_key"  # @deprecated
    BEARER_TOKEN = "bearer_token"
    MTLS = "mtls"
    NONE = "none"


class TrustLevel(str, Enum):
    """信任等级 L1-L4"""

    L1 = "L1"  # 平台托管/强验证
    L2 = "L2"  # 组织验证
    L3 = "L3"  # 受限/条件验证
    L4 = "L4"  # 未验证/不可信


class ConnectorState(str, Enum):
    """连接器生命周期状态"""

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


class ToolState(str, Enum):
    """工具状态"""

    PENDING_DISCOVERY = "pending_discovery"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    RESTRICTED = "restricted"
    DISABLED = "disabled"


@dataclass
class ConnectorIdentity:
    """连接器稳定身份"""

    connector_id: str  # 平台分配的稳定 ID，格式: conn_<uuid>
    organization_id: str
    display_name: str
    namespace: str  # 发布者命名空间，如 "github", "anthropic", "openai"
    version: str  # 连接器版本，如 "1.0.0"
    created_at: datetime
    created_by: str  # 创建者用户 ID

    def to_dict(self) -> dict:
        return {
            "connector_id": self.connector_id,
            "organization_id": self.organization_id,
            "display_name": self.display_name,
            "namespace": self.namespace,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }


@dataclass
class TransportConfig:
    """传输配置"""

    type: TransportType
    endpoint: str | None = None  # HTTP 端点
    command: str | None = None  # STDIO 命令
    args: list[str] = field(default_factory=list)  # STDIO 参数
    env_vars: dict[str, str] = field(default_factory=dict)  # 环境变量

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "endpoint": self.endpoint,
            "command": self.command,
            "args": self.args,
            "env_vars": self.env_vars,
        }


@dataclass
class AuthConfig:
    """认证配置"""

    mode: AuthenticationMode
    oauth_client_id: str | None = None
    oauth_authorization_endpoint: str | None = None
    oauth_token_endpoint: str | None = None
    oauth_revocation_endpoint: str | None = None
    oauth_audience: str | None = None  # 目标受众，防 token passthrough
    api_key_ref: str | None = None  # 密钥托管引用（不含密钥值）
    certificate_fingerprint: str | None = None  # 证书指纹

    def to_dict(self) -> dict:
        """返回脱敏配置（不含密钥）"""
        return {
            "mode": self.mode.value,
            "oauth_client_id": self.oauth_client_id,
            "oauth_authorization_endpoint": self.oauth_authorization_endpoint,
            "oauth_token_endpoint": self.oauth_token_endpoint,
            "oauth_revocation_endpoint": self.oauth_revocation_endpoint,
            "oauth_audience": self.oauth_audience,
            "api_key_ref": self.api_key_ref,
            "certificate_fingerprint": self.certificate_fingerprint,
        }


@dataclass
class SignatureInfo:
    """签名信息"""

    signature_format: str  # "sigstore_oidc", "pkcs7", 等
    signature_key_id: str  # 签名密钥标识
    signature_value: str  # 签名值（hex）
    signer_identity: str  # 签名者身份，如邮箱或组织名
    signed_at: datetime
    valid_until: datetime | None = None
    signature_status: str = "valid"  # valid, expired, revoked

    def is_valid(self, now: datetime | None = None) -> bool:
        now = now or datetime.utcnow()
        if self.signature_status != "valid":
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True


@dataclass
class ToolSchemaVersion:
    """工具 Schema 版本"""

    tool_name: str
    schema_digest: str  # SHA256(tool_name + schema_json)
    schema_hash: str  # 完整 Schema 的 SHA256
    description: str
    input_schema: dict  # JSON Schema
    is_read_only: bool
    requires_approval: bool  # 是否需要人工审批
    risk_level: str  # "low", "medium", "high", "critical"
    data_sensitivity: str  # 访问数据级别 "L1" ~ "L4"
    network_access: list[str] = field(default_factory=list)  # FQDN/IP 白名单
    resource_scopes: list[str] = field(
        default_factory=list
    )  # 资源范围，如 ["org:read", "repo:write"]
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "schema_digest": self.schema_digest,
            "schema_hash": self.schema_hash,
            "description": self.description,
            "input_schema": self.input_schema,
            "is_read_only": self.is_read_only,
            "requires_approval": self.requires_approval,
            "risk_level": self.risk_level,
            "data_sensitivity": self.data_sensitivity,
            "network_access": self.network_access,
            "resource_scopes": self.resource_scopes,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ConnectorVersion:
    """连接器版本与签名"""

    connector_id: str
    version: str
    transport: TransportConfig
    auth: AuthConfig
    signature: SignatureInfo | None
    tools: list[ToolSchemaVersion]  # 发现时的工具清单
    published_at: datetime
    published_by: str  # 发布者身份
    changelog: str

    def compute_tools_digest(self) -> str:
        """计算工具清单摘要"""
        tool_list = sorted([t.schema_digest for t in self.tools])
        combined = json.dumps(tool_list)
        return hashlib.sha256(combined.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "connector_id": self.connector_id,
            "version": self.version,
            "transport": self.transport.to_dict(),
            "auth": self.auth.to_dict(),
            "signature": {
                "key_id": self.signature.signature_key_id,
                "status": self.signature.signature_status,
                "signed_at": self.signature.signed_at.isoformat(),
            }
            if self.signature
            else None,
            "tools_count": len(self.tools),
            "tools_digest": self.compute_tools_digest(),
            "published_at": self.published_at.isoformat(),
            "published_by": self.published_by,
        }


@dataclass
class ConnectorTrustEvidence:
    """信任等级证据"""

    level: TrustLevel
    assessed_at: datetime
    assessed_by: str  # 评估者
    evidence_items: dict[
        str, Any
    ]  # 证据项，如 {"signature_valid": true, "publisher_verified": true}
    next_review_date: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "assessed_at": self.assessed_at.isoformat(),
            "assessed_by": self.assessed_by,
            "evidence_items": self.evidence_items,
            "next_review_date": self.next_review_date.isoformat()
            if self.next_review_date
            else None,
        }


@dataclass
class Connector:
    """MCP 连接器对象（全量）"""

    identity: ConnectorIdentity
    current_version: ConnectorVersion
    trust_evidence: ConnectorTrustEvidence
    state: ConnectorState
    quota_weight: float  # 按信任等级计权
    last_health_check: datetime | None = None
    health_status: str = "unknown"  # "healthy", "degraded", "unhealthy"
    last_state_change: datetime = field(default_factory=datetime.utcnow)
    state_change_reason: str = ""

    def get_available_tools(
        self, approved_tool_names: set[str] | None = None
    ) -> list[ToolSchemaVersion]:
        """获取当前可用工具"""
        if self.state not in [ConnectorState.ACTIVE, ConnectorState.RESTRICTED]:
            return []

        available = self.current_version.tools
        if approved_tool_names:
            available = [t for t in available if t.tool_name in approved_tool_names]
        return available

    def is_callable(self) -> bool:
        """是否可被调用"""
        return self.state in [ConnectorState.ACTIVE, ConnectorState.RESTRICTED]
