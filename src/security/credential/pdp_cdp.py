"""
凭据代理 - PDP/CDP 分离架构 - REQ-SEC-005

策略决策点 (PDP)：无凭据访问权，仅负责授权决策
凭据传递点 (CDP)：无策略制定权，仅负责凭据铸造和分发

核心设计原则：
1. Agent 从不持有长期凭据
2. 每个 Capability Token 限定到单资源、单操作
3. 租约不可续期，TTL 到期必须重新请求
4. CDP 不可用时 fail-secure（拒绝所有新请求）
5. 所有操作完整审计
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CapabilityTokenType(str, Enum):
    """凭据令牌类型"""
    GITHUB_APP_TOKEN = "github_app_token"
    AWS_STS_TOKEN = "aws_sts_token"
    GCP_TOKEN = "gcp_token"
    OAUTH_TOKEN = "oauth_token"
    PROXY_TOKEN = "proxy_token"


class CredentialAuditAction(str, Enum):
    """凭据审计动作"""
    REQUESTED = "requested"
    ISSUED = "issued"
    REJECTED = "rejected"
    REVOKED = "revoked"
    EXPIRED = "expired"


class CapabilityTokenRequest(BaseModel):
    """Capability Token 请求"""
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    
    # 调用身份
    agent_svid: str = Field(..., description="SPIFFE SVID 身份")
    task_id: str = Field(..., description="关联的任务 ID")
    worker_id: str = Field(..., description="关联的 Worker ID")
    
    # 目标凭据信息
    target_service: str = Field(
        ...,
        description="目标服务（github/aws/gcp/azure/generic_oauth）"
    )
    target_resource: str = Field(..., description="目标资源标识")
    requested_action: str = Field(..., description="操作类型（read/write/admin）")
    requested_scope: list[str] = Field(default_factory=list, description="请求的作用域")
    
    # 策略审批引用
    policy_approval_ref: str = Field(
        ...,
        description="SEC-003 Policy Gateway 审批引用"
    )
    
    # TTL 请求
    max_ttl_seconds: int | None = Field(
        default=None,
        description="请求的最大 TTL（可选）"
    )
    
    # DPoP 支持（MVP 预留）
    dpop_public_key: str | None = Field(
        default=None,
        description="DPoP 公钥（PEM/SPKI 格式）"
    )
    
    # 审计信息
    justification: str = Field(..., description="操作理由（仅用于审计）")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CapabilityTokenResponse(BaseModel):
    """Capability Token 响应"""
    token_id: str = Field(default_factory=lambda: str(uuid4()), description="令牌 ID")
    
    # 凭据内容
    issued_token: str | None = Field(
        default=None,
        description="实际短期凭据（Model B）或为空（Model A 代理模式）"
    )
    
    # 令牌类型与范围
    token_type: CapabilityTokenType = Field(..., description="令牌类型")
    scope: list[str] = Field(..., description="最终授予的精确作用域")
    
    # 过期时间
    expires_at: datetime = Field(..., description="绝对过期时间")
    issued_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Model A 代理模式
    service_endpoint: str | None = Field(
        default=None,
        description="Model A 代理模式时的代理地址"
    )
    
    # 审计引用
    audit_ref: str = Field(..., description="本次签发的审计记录引用")
    
    # DPoP 支持（MVP 预留）
    dpop_fingerprint: str | None = Field(
        default=None,
        description="DPoP 公钥指纹"
    )


@dataclass
class CredentialRental:
    """凭据租约"""
    token_id: str                          # 令牌 ID
    task_id: str                           # 关联任务
    service: str                           # 目标服务
    scope: list[str]                       # 权限范围
    issued_at: datetime                    # 签发时间
    expires_at: datetime                   # 过期时间
    vault_lease_id: str | None = None   # Vault 租约 ID
    
    def is_expired(self) -> bool:
        """检查是否已过期"""
        return datetime.utcnow() > self.expires_at
    
    def remaining_ttl_seconds(self) -> int:
        """获取剩余 TTL（秒）"""
        remaining = (self.expires_at - datetime.utcnow()).total_seconds()
        return max(0, int(remaining))


@dataclass
class CredentialAuditEvent:
    """凭据审计事件"""
    audit_id: str = field(default_factory=lambda: str(uuid4()))
    action: CredentialAuditAction = field(default=CredentialAuditAction.REQUESTED)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # 请求信息（不包含凭据内容）
    token_id: str = ""
    request_id: str = ""
    task_id: str = ""
    agent_svid: str = ""
    
    # 决策信息
    service: str = ""
    action_type: str = ""
    requested_scope: list[str] = field(default_factory=list)
    granted_scope: list[str] = field(default_factory=list)
    
    # 结果
    decision: str = ""  # ALLOWED / DENIED / REJECTED
    reason: str = ""
    
    # 审计不包含令牌内容（fail-secure 原则）


class CredentialPDP:
    """
    凭据策略决策点 (Policy Decision Point)
    
    职责：
    1. 验证 Agent 身份（SPIRE SVID）
    2. 调用 SEC-003 Policy Gateway 验证审批
    3. 调用 SEC-002 RBAC 验证授权
    4. 生成签名的审批决策
    
    关键约束：
    - 无凭据材料访问权
    - 输出带签名的审批决策给 CDP
    """

    def __init__(self) -> None:
        """初始化 PDP"""
        self._audit_events: list[CredentialAuditEvent] = []
        self._revoked_tokens: set[str] = set()

    def verify_and_approve(
        self,
        request: CapabilityTokenRequest,
        policy_gateway_result: bool,
        rbac_result: bool,
        rbac_scope: list[str],
    ) -> tuple[bool, str, list[str]]:
        """
        验证并生成审批决策
        
        Args:
            request: 令牌请求
            policy_gateway_result: Policy Gateway 审批结果
            rbac_result: RBAC 授权结果
            rbac_scope: RBAC 允许的作用域
            
        Returns:
            (approved, reason, final_scope): 是否批准、理由、最终作用域
        """
        # 步骤 1：检查策略门禁
        if not policy_gateway_result:
            reason = "Policy Gateway rejected the request"
            self._record_audit(request, False, reason, [])
            return False, reason, []
        
        # 步骤 2：检查 RBAC 授权
        if not rbac_result:
            reason = "RBAC authorization denied"
            self._record_audit(request, False, reason, [])
            return False, reason, []
        
        # 步骤 3：协商最终作用域（RBAC 范围与请求的交集）
        requested_scope = (
            set(request.requested_scope)
            if request.requested_scope
            else {request.requested_action}
        )
        rbac_scope_set = set(rbac_scope)
        final_scope = list(requested_scope & rbac_scope_set)
        
        if not final_scope:
            reason = "Requested scope outside of RBAC authorization"
            self._record_audit(request, False, reason, [])
            return False, reason, []
        
        # 步骤 4：批准
        reason = f"Approved by PDP (RBAC scope: {final_scope})"
        self._record_audit(request, True, reason, final_scope)
        return True, reason, final_scope

    def is_token_revoked(self, token_id: str) -> bool:
        """检查令牌是否被撤销"""
        return token_id in self._revoked_tokens

    def revoke_token(self, token_id: str, task_id: str, reason: str = "") -> None:
        """撤销令牌"""
        self._revoked_tokens.add(token_id)
        
        audit = CredentialAuditEvent(
            action=CredentialAuditAction.REVOKED,
            token_id=token_id,
            task_id=task_id,
            decision="REVOKED",
            reason=reason,
        )
        self._audit_events.append(audit)
        logger.info(f"Token revoked: {token_id} (reason: {reason})")

    def _record_audit(
        self,
        request: CapabilityTokenRequest,
        approved: bool,
        reason: str,
        final_scope: list[str],
    ) -> None:
        """记录审计事件"""
        action = CredentialAuditAction.ISSUED if approved else CredentialAuditAction.REJECTED
        
        audit = CredentialAuditEvent(
            action=action,
            request_id=request.request_id,
            task_id=request.task_id,
            agent_svid=request.agent_svid,
            service=request.target_service,
            action_type=request.requested_action,
            requested_scope=request.requested_scope,
            granted_scope=final_scope,
            decision="ALLOWED" if approved else "DENIED",
            reason=reason,
        )
        
        self._audit_events.append(audit)

    def get_audit_events(self, limit: int = 100) -> list[CredentialAuditEvent]:
        """获取审计事件"""
        return self._audit_events[-limit:]


class CredentialCDP:
    """
    凭据凭据传递点 (Credential Delivery Point)
    
    职责：
    1. 接收 PDP 的审批决策
    2. 从 Vault 获取根凭据
    3. 铸造短期派生令牌
    4. 管理租约和撤销
    
    关键约束：
    - 无策略制定权
    - 仅处理 PDP 批准的请求
    - CDP 不可用时 fail-secure
    """

    def __init__(self, vault_adapter: Any = None):
        """初始化 CDP"""
        self.vault_adapter = vault_adapter
        self._rentals: dict[str, CredentialRental] = {}
        self._audit_events: list[CredentialAuditEvent] = []
        self._is_healthy = True

    def issue_token(
        self,
        request: CapabilityTokenRequest,
        pdp_approval: tuple[bool, str, list[str]],
        requested_ttl_seconds: int | None = None,
    ) -> CapabilityTokenResponse:
        """
        签发 Capability Token
        
        Args:
            request: 令牌请求
            pdp_approval: PDP 审批结果 (approved, reason, final_scope)
            requested_ttl_seconds: 请求的 TTL
            
        Returns:
            CapabilityTokenResponse: 令牌响应
            
        Raises:
            RuntimeError: 如果 CDP 不健康或凭据签发失败
        """
        # fail-secure 检查
        if not self._is_healthy:
            raise RuntimeError("CDP is not healthy; rejecting all new token requests")
        
        approved, pdp_reason, final_scope = pdp_approval
        if not approved:
            raise ValueError(f"PDP rejected: {pdp_reason}")
        
        # 确定 TTL
        default_ttls = {
            "github": 3600,      # 1h
            "aws": 900,          # 15min
            "gcp": 3600,         # 1h
            "generic_oauth": 1800,  # 30min
        }
        default_ttl = default_ttls.get(request.target_service, 3600)
        ttl = min(requested_ttl_seconds or default_ttl, default_ttl)
        
        expires_at = datetime.utcnow() + timedelta(seconds=ttl)
        
        # 从 Vault 获取根凭据并铸造派生令牌
        issued_token = self._mint_token(request, final_scope, ttl)
        
        # 注册租约
        token_id = str(uuid4())
        rental = CredentialRental(
            token_id=token_id,
            task_id=request.task_id,
            service=request.target_service,
            scope=final_scope,
            issued_at=datetime.utcnow(),
            expires_at=expires_at,
        )
        self._rentals[token_id] = rental
        
        # 记录审计
        audit = CredentialAuditEvent(
            action=CredentialAuditAction.ISSUED,
            token_id=token_id,
            request_id=request.request_id,
            task_id=request.task_id,
            service=request.target_service,
            granted_scope=final_scope,
            decision="ISSUED",
            reason="Token issued successfully",
        )
        self._audit_events.append(audit)
        
        # DPoP 支持（MVP 预留）
        dpop_fingerprint = None
        if request.dpop_public_key:
            dpop_fingerprint = hashlib.sha256(
                request.dpop_public_key.encode()
            ).hexdigest()[:16]
        
        return CapabilityTokenResponse(
            token_id=token_id,
            issued_token=issued_token,
            token_type=self._get_token_type(request.target_service),
            scope=final_scope,
            expires_at=expires_at,
            audit_ref=audit.audit_id,
            dpop_fingerprint=dpop_fingerprint,
        )

    def revoke_token(self, token_id: str, reason: str = "") -> None:
        """撤销令牌"""
        if token_id in self._rentals:
            rental = self._rentals[token_id]
            
            # 通知 Vault 撤销租约
            if rental.vault_lease_id and self.vault_adapter:
                self.vault_adapter.revoke_lease(rental.vault_lease_id)
            
            del self._rentals[token_id]
            
            audit = CredentialAuditEvent(
                action=CredentialAuditAction.REVOKED,
                token_id=token_id,
                task_id=rental.task_id,
                service=rental.service,
                decision="REVOKED",
                reason=reason,
            )
            self._audit_events.append(audit)
            logger.info(f"Token revoked: {token_id}")

    def cleanup_expired_tokens(self) -> int:
        """清理过期令牌，返回清理数量"""
        expired_tokens = [
            token_id
            for token_id, rental in self._rentals.items()
            if rental.is_expired()
        ]
        
        for token_id in expired_tokens:
            rental = self._rentals[token_id]
            
            if rental.vault_lease_id and self.vault_adapter:
                self.vault_adapter.revoke_lease(rental.vault_lease_id)
            
            del self._rentals[token_id]
            
            audit = CredentialAuditEvent(
                action=CredentialAuditAction.EXPIRED,
                token_id=token_id,
                task_id=rental.task_id,
                service=rental.service,
                decision="EXPIRED",
                reason="Token TTL expired",
            )
            self._audit_events.append(audit)
        
        return len(expired_tokens)

    def set_health(self, is_healthy: bool) -> None:
        """设置 CDP 健康状态"""
        self._is_healthy = is_healthy
        if not is_healthy:
            logger.error("CDP marked as unhealthy; rejecting new requests")

    def _mint_token(self, request: CapabilityTokenRequest, scope: list[str], ttl: int) -> str:
        """铸造短期令牌"""
        # 这里应该调用具体的服务代理
        # 本实现为示例，返回示意令牌
        if request.target_service == "github":
            return f"ghu_{uuid4().hex[:20]}"
        elif request.target_service == "aws":
            return f"ASIATEMP{uuid4().hex[:32]}".upper()
        else:
            return f"token_{uuid4().hex[:24]}"

    def _get_token_type(self, service: str) -> CapabilityTokenType:
        """获取令牌类型"""
        type_mapping = {
            "github": CapabilityTokenType.GITHUB_APP_TOKEN,
            "aws": CapabilityTokenType.AWS_STS_TOKEN,
            "gcp": CapabilityTokenType.GCP_TOKEN,
            "generic_oauth": CapabilityTokenType.OAUTH_TOKEN,
        }
        return type_mapping.get(service, CapabilityTokenType.OAUTH_TOKEN)

    def get_audit_events(self, limit: int = 100) -> list[CredentialAuditEvent]:
        """获取审计事件"""
        return self._audit_events[-limit:]

    def get_rental_stats(self) -> dict[str, Any]:
        """获取租约统计"""
        total = len(self._rentals)
        by_service: dict[str, int] = {}
        for rental in self._rentals.values():
            by_service.setdefault(rental.service, 0)
            by_service[rental.service] += 1
        
        return {
            "total_active_rentals": total,
            "by_service": by_service,
            "healthy": self._is_healthy,
        }
