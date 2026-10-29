"""
Policy Engine

Orchestrates global blacklist, org whitelist, and quota decisions.
"""

import logging
from dataclasses import dataclass, field

from ..models import (
    AuthenticationMode,
    Connector,
    ConnectorLifecycleState,
    ExecutionEnvironment,
    ToolSchema,
    TrustLevel,
)
from .capability_trimmer import resolve_trims, validate_call
from .global_blacklist import GlobalBlacklist
from .org_whitelist import OrgWhitelistPolicy
from .quota_manager import QuotaManager

logger = logging.getLogger(__name__)


@dataclass
class PolicyDecision:
    """Result of a policy evaluation."""
    
    allowed: bool
    reason: str
    blocked_by: str | None = None  # "global_blacklist", "org_policy", "quota"
    quota_cost: float = 0.0
    warnings: list[str] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []
    
    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "blocked_by": self.blocked_by,
            "quota_cost": self.quota_cost,
            "warnings": self.warnings,
        }


class PolicyEngine:
    """
    Central policy decision point for MCP connector governance.
    
    Evaluation order:
    1. Global Blacklist (highest priority - cannot be overridden)
    1b. Lifecycle gate (only ACTIVE / RESTRICTED connectors are callable)
    2. Organization Whitelist (optional org-level policy)
    3. Quota Check (weighted quota based on trust level)
    """
    
    def __init__(
        self,
        global_blacklist: GlobalBlacklist | None = None,
        org_whitelist: OrgWhitelistPolicy | None = None,
        quota_manager: QuotaManager | None = None,
        environment: ExecutionEnvironment = ExecutionEnvironment.PRODUCTION,
    ) -> None:
        # 环境是部署属性, 不是单次调用参数, 调用方无法按次声明"这是评估环境"。
        # 默认 PRODUCTION (fail-closed)。
        self.environment = environment
        self.global_blacklist = global_blacklist or GlobalBlacklist()
        self.org_whitelist = org_whitelist or OrgWhitelistPolicy()
        self.quota_manager = quota_manager or QuotaManager()
    
    @staticmethod
    def _effective_trust_level(connector: Connector) -> TrustLevel:
        """无法确认等级时按 L4 处理 (需求 4.4)。"""
        level = getattr(connector.config, "trust_level", None)
        return level if isinstance(level, TrustLevel) else TrustLevel.L4_UNVERIFIED_UNTRUSTED

    @staticmethod
    def _is_sensitive(data_sensitivity: object) -> bool:
        """数据分级 L1 公开 / L2 内部 / L3 敏感 / L4 机密; 无法解析按敏感处理。"""
        return str(data_sensitivity).strip().upper() not in ("L1", "L2")

    def evaluate_connector_access(
        self,
        org_id: str,
        connector: Connector,
    ) -> PolicyDecision:
        """
        Evaluate if organization can access a connector.
        
        Args:
            org_id: Organization ID
            connector: Connector to evaluate
            
        Returns:
            PolicyDecision
        """
        connector_id = connector.connector_id
        namespace = connector.config.identity.namespace
        
        # Step 1: Check global blacklist (highest priority)
        if self.global_blacklist.is_connector_blocked(connector_id):
            reason = self.global_blacklist.get_block_reason(connector_id, "connector")
            return PolicyDecision(
                allowed=False,
                reason=f"Connector blocked by global policy: {reason}",
                blocked_by="global_blacklist",
            )
        
        if self.global_blacklist.is_namespace_blocked(namespace):
            reason = self.global_blacklist.get_block_reason(namespace, "namespace")
            return PolicyDecision(
                allowed=False,
                reason=f"Namespace blocked by global policy: {reason}",
                blocked_by="global_blacklist",
            )
        
        # Step 1b: Lifecycle gate (fail-closed). Only ACTIVE / RESTRICTED connectors
        # may be invoked; paused, revoked, expired, pending, etc. are all denied.
        if not connector.status.is_callable():
            # 未知状态也要返回明确拒绝，不能因格式化 .value 再抛异常。
            state = connector.lifecycle_state
            state_label = state.value if isinstance(state, ConnectorLifecycleState) else "unknown"
            return PolicyDecision(
                allowed=False,
                reason=(
                    "Connector is not callable in lifecycle state "
                    f"'{state_label}'"
                ),
                blocked_by="lifecycle",
            )
        
        # Step 1c: Trust-level environment gate (AC16). Unknown level is treated as L4.
        if self._effective_trust_level(connector) == TrustLevel.L4_UNVERIFIED_UNTRUSTED:
            if self.environment != ExecutionEnvironment.ISOLATED_EVALUATION:
                return PolicyDecision(
                    allowed=False,
                    reason="L4 (unverified) connectors cannot run outside isolated evaluation",
                    blocked_by="trust_level",
                )
            # 评估环境内也不放行凭据: 目前没有"测试凭据"概念, 无法区分生产凭据, 一律拒绝
            if connector.config.auth.mode != AuthenticationMode.NONE:
                return PolicyDecision(
                    allowed=False,
                    reason="L4 connectors must not use credentials",
                    blocked_by="trust_level",
                )
        
        # Step 2: Check org whitelist (if exists)
        whitelist_entry = self.org_whitelist.get_whitelist_entry(org_id, connector_id)
        if whitelist_entry:
            # Org has explicit whitelist entry
            if not self.org_whitelist.is_connector_whitelisted(org_id, connector_id):
                return PolicyDecision(
                    allowed=False,
                    reason="Connector not in organization whitelist",
                    blocked_by="org_policy",
                )
        
        # Step 3: Check quota
        quota_cost = self._calculate_connector_quota_cost(connector)
        if not self.quota_manager.check_quota(org_id, quota_cost):
            return PolicyDecision(
                allowed=False,
                reason="Organization quota exceeded",
                blocked_by="quota",
                quota_cost=quota_cost,
            )
        
        # All checks passed
        warnings = []
        
        # Add warnings for trust level
        if connector.trust_level == TrustLevel.L4_UNVERIFIED_UNTRUSTED:
            warnings.append("Connector is unverified (L4) - sandbox only")
        elif connector.trust_level == TrustLevel.L3_RESTRICTED_CONDITIONAL:
            warnings.append("Connector has restricted access (L3)")
        
        return PolicyDecision(
            allowed=True,
            reason="Access granted",
            quota_cost=quota_cost,
            warnings=warnings,
        )
    
    def evaluate_tool_invocation(
        self,
        org_id: str,
        connector: Connector,
        tool: ToolSchema,
        parameters: dict | None = None,
    ) -> PolicyDecision:
        """
        Evaluate if organization can invoke a specific tool.
        
        Args:
            org_id: Organization ID
            connector: Connector providing the tool
            tool: Tool to invoke
            parameters: Call arguments; checked against org parameter restrictions.
                None means "no arguments" (restricted parameters then are simply absent).
            
        Returns:
            PolicyDecision
        """
        # First check connector access
        connector_decision = self.evaluate_connector_access(org_id, connector)
        if not connector_decision.allowed:
            return connector_decision
        
        # L4 only handles synthetic / non-sensitive data (AC16); unknown sensitivity = sensitive
        if (
            self._effective_trust_level(connector) == TrustLevel.L4_UNVERIFIED_UNTRUSTED
            and self._is_sensitive(tool.risk_profile.data_sensitivity)
        ):
            return PolicyDecision(
                allowed=False,
                reason="L4 connectors cannot access sensitive data",
                blocked_by="trust_level",
            )
        
        # Check if tool is globally blocked
        if self.global_blacklist.is_tool_blocked(tool.tool_name):
            reason = self.global_blacklist.get_block_reason(tool.tool_name, "tool")
            return PolicyDecision(
                allowed=False,
                reason=f"Tool blocked by global policy: {reason}",
                blocked_by="global_blacklist",
            )
        
        # Check org-level capability trims
        capability_trims = self.org_whitelist.get_capability_trims(
            org_id,
            connector.connector_id,
        )
        
        # Apply capability trimming (method + parameter restrictions, fail-closed)
        effective = resolve_trims(capability_trims, tool.tool_name)
        violation = validate_call(effective, parameters)
        if violation:
            logger.warning(
                f"Capability trim denied tool {tool.tool_name} in org {org_id}: {violation}"
            )
            return PolicyDecision(
                allowed=False,
                reason=violation,
                blocked_by="org_policy",
            )
        
        # Calculate tool-specific quota cost
        quota_cost = self._calculate_tool_quota_cost(connector, tool)
        
        if not self.quota_manager.check_quota(org_id, quota_cost):
            return PolicyDecision(
                allowed=False,
                reason="Organization quota exceeded for tool invocation",
                blocked_by="quota",
                quota_cost=quota_cost,
            )
        
        # Generate warnings (keep connector-level ones, e.g. "unverified L4")
        warnings = list(connector_decision.warnings)
        if tool.risk_profile.requires_human_approval:
            warnings.append("Tool requires human approval before execution")
        
        if tool.risk_profile.risk_level in ["high", "critical"]:
            warnings.append(f"Tool has {tool.risk_profile.risk_level} risk level")
        
        return PolicyDecision(
            allowed=True,
            reason="Tool invocation allowed",
            quota_cost=quota_cost,
            warnings=warnings,
        )
    
    def consume_quota_for_invocation(
        self,
        org_id: str,
        connector: Connector,
        tool: ToolSchema,
    ) -> bool:
        """
        Consume quota for a tool invocation.
        
        Args:
            org_id: Organization ID
            connector: Connector
            tool: Tool being invoked
            
        Returns:
            True if quota consumed successfully
        """
        quota_cost = self._calculate_tool_quota_cost(connector, tool)
        return self.quota_manager.consume_quota(org_id, quota_cost)
    
    def refund_quota_for_failed_invocation(
        self,
        org_id: str,
        connector: Connector,
        tool: ToolSchema,
    ) -> None:
        """
        Refund quota for a failed tool invocation.
        
        Args:
            org_id: Organization ID
            connector: Connector
            tool: Tool that failed
        """
        quota_cost = self._calculate_tool_quota_cost(connector, tool)
        self.quota_manager.refund_quota(org_id, quota_cost)
    
    def _calculate_connector_quota_cost(self, connector: Connector) -> float:
        """Calculate quota cost for connector access."""
        tool_count = len(connector.config.tools)
        
        # Calculate average risk level
        risk_levels = [t.risk_profile.risk_level for t in connector.config.tools]
        avg_risk = "medium"  # Default
        if risk_levels:
            if "critical" in risk_levels:
                avg_risk = "critical"
            elif "high" in risk_levels:
                avg_risk = "high"
            elif all(r == "low" for r in risk_levels):
                avg_risk = "low"
        
        # Check if any tool requires network
        requires_network = any(
            t.risk_profile.network_access_required
            for t in connector.config.tools
        )
        
        # Check if any tool requires credentials
        requires_credentials = any(
            t.risk_profile.credential_access_required
            for t in connector.config.tools
        )
        
        return self.quota_manager.calculate_cost(
            trust_level=connector.trust_level,
            tool_count=tool_count,
            risk_level=avg_risk,
            requires_network=requires_network,
            requires_credentials=requires_credentials,
        )
    
    def _calculate_tool_quota_cost(
        self,
        connector: Connector,
        tool: ToolSchema,
    ) -> float:
        """Calculate quota cost for a specific tool invocation."""
        return self.quota_manager.calculate_cost(
            trust_level=connector.trust_level,
            tool_count=1,
            risk_level=tool.risk_profile.risk_level,
            requires_network=tool.risk_profile.network_access_required,
            requires_credentials=tool.risk_profile.credential_access_required,
        )
