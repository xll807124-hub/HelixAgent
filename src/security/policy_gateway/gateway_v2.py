"""
Policy Gateway 完整实现 (Phase 2)。

集成 RBAC 评估结果，实现完整的策略决策流程。
- PDP (Policy Decision Point): 策略决策
- PEP (Policy Execution Point): 策略执行点
- 审批矩阵和升级逻辑
- 决策缓存
- 审计记录
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.security.rbac.models import (
    AuthorizationDecision as RBACDecision,
)
from src.security.rbac.models import (
    AuthorizationResult,
    Operation,
)


class PolicyDecision(str, Enum):
    """策略决策。
    
    基于 RBAC 评估和风险等级的最终决策。
    """
    
    ALLOW = "ALLOW"                    # 允许执行
    DENY = "DENY"                      # 拒绝执行
    ESCALATE_TO_APPROVAL = "ESCALATE_TO_APPROVAL"  # 需要人工审批


class RiskLevel(str, Enum):
    """动作风险等级。
    
    决定是否需要审批。
    """
    
    LOW = "LOW"                        # 低风险 (允许)
    MEDIUM = "MEDIUM"                 # 中风险 (可能需要审批)
    HIGH = "HIGH"                      # 高风险 (通常需要审批)
    CRITICAL = "CRITICAL"             # 极端风险 (总是需要审批)


class PolicyRequest(BaseModel):
    """策略评估请求。
    
    包含 RBAC 评估结果和动作信息。
    """
    
    model_config = ConfigDict(frozen=True)
    
    request_id: str                    # 请求 ID
    action_id: str                     # 动作 ID (来自 Task/Workflow)
    action_name: str                   # 动作名称
    operation: Operation               # 操作类型
    rbac_result: AuthorizationResult   # RBAC 评估结果
    risk_level: RiskLevel              # 动作风险等级
    resource_id: str                   # 资源 ID
    parameters: dict[str, Any] | None = None  # 动作参数摘要
    timestamp: datetime = None  # type: ignore
    
    def __init__(self, **data: Any) -> None:
        """初始化请求."""
        if data.get("timestamp") is None:
            data["timestamp"] = datetime.now(UTC)
        super().__init__(**data)


class PolicyResult(BaseModel):
    """策略评估结果。
    
    包含决策、原因和审计信息。
    """
    
    model_config = ConfigDict(frozen=True)
    
    request_id: str                    # 对应请求 ID
    decision: PolicyDecision           # 策略决策
    reason: str                        # 决策原因
    rbac_decision: RBACDecision        # 原始 RBAC 决策
    risk_level: RiskLevel              # 风险等级
    requires_approval: bool            # 是否需要审批
    approval_reason: str | None = None  # 审批原因
    effective_until: datetime | None = None  # 决策有效期
    timestamp: datetime = None  # type: ignore
    
    def __init__(self, **data: Any) -> None:
        """初始化结果."""
        if data.get("timestamp") is None:
            data["timestamp"] = datetime.now(UTC)
        super().__init__(**data)


class ApprovalMatrix(BaseModel):
    """审批矩阵。
    
    根据风险等级和动作确定是否需要审批。
    """
    
    # 风险等级 → 是否需要审批
    # 高风险需要显式审批
    approval_required: dict[RiskLevel, bool] = {
        RiskLevel.LOW: False,
        RiskLevel.MEDIUM: False,  # MVP 中风险暂不需要审批
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    }
    
    # 特定操作的审批要求 (覆盖风险等级规则)
    operation_overrides: dict[Operation, bool] = {
        Operation.MANAGE_POLICIES: True,  # 总是需要审批
        Operation.MANAGE_MEMBERS: True,   # 总是需要审批
        Operation.CREATE_BRANCH: False,   # 通常允许
        Operation.CREATE_COMMIT: False,   # 通常允许
    }
    
    def requires_approval(self, operation: Operation, risk_level: RiskLevel) -> bool:
        """判断是否需要审批。
        
        Args:
            operation: 操作类型
            risk_level: 风险等级
            
        Returns:
            是否需要审批
        """
        # 操作级覆盖优先
        if operation in self.operation_overrides:
            return self.operation_overrides[operation]
        
        # 使用风险等级规则
        return self.approval_required.get(risk_level, False)


class PolicyDecisionCache:
    """决策缓存。
    
    缓存最近的策略决策，避免重复评估。
    """
    
    def __init__(self, ttl_seconds: int = 300):
        """初始化缓存。
        
        Args:
            ttl_seconds: 缓存 TTL (默认 5 分钟)
        """
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[PolicyResult, datetime]] = {}
    
    def _make_key(self, request: PolicyRequest) -> str:
        """生成缓存 key。
        
        基于请求的重要字段生成 hash。
        """
        key_data = {
            "action_id": request.action_id,
            "operation": request.operation.value,
            "subject_id": request.rbac_result.subject.subject_id,
            "resource_id": request.rbac_result.resource.resource_id,
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]
    
    def get(self, request: PolicyRequest) -> PolicyResult | None:
        """从缓存获取决策。
        
        Args:
            request: 策略请求
            
        Returns:
            缓存的决策，如果不存在或已过期返回 None
        """
        key = self._make_key(request)
        if key not in self._cache:
            return None
        
        result, cached_at = self._cache[key]
        age = (datetime.now(UTC) - cached_at).total_seconds()
        
        if age > self.ttl_seconds:
            del self._cache[key]
            return None
        
        return result
    
    def set(self, request: PolicyRequest, result: PolicyResult) -> None:
        """缓存决策。
        
        Args:
            request: 策略请求
            result: 策略结果
        """
        key = self._make_key(request)
        self._cache[key] = (result, datetime.now(UTC))
    
    def clear(self) -> None:
        """清空缓存."""
        self._cache.clear()


class PolicyAuditEvent(BaseModel):
    """审计事件。
    
    记录所有策略决策和审批。
    """
    
    model_config = ConfigDict(
        frozen=True,
        json_encoders={
            datetime: lambda v: v.isoformat(),
        },
    )
    
    event_id: str                      # 事件 ID
    request_id: str                    # 对应请求 ID
    decision: PolicyDecision           # 决策
    reason: str                        # 原因
    subject_id: str                    # 发起主体
    resource_id: str                   # 目标资源
    operation: str                     # 操作
    risk_level: str                    # 风险等级
    timestamp: datetime


class PolicyGateway:
    """完整的策略网关实现。
    
    核心职责:
    1. 接收 RBAC 评估结果
    2. 根据风险等级进行策略评估
    3. 决定是否允许、拒绝或升级到审批
    4. 缓存决策避免重复评估
    5. 记录所有审计事件
    """
    
    def __init__(
        self,
        approval_matrix: ApprovalMatrix | None = None,
        cache_ttl_seconds: int = 300,
    ):
        """初始化策略网关。
        
        Args:
            approval_matrix: 审批矩阵 (使用默认)
            cache_ttl_seconds: 缓存 TTL
        """
        self.approval_matrix = approval_matrix or ApprovalMatrix()
        self.cache = PolicyDecisionCache(ttl_seconds=cache_ttl_seconds)
        self.audit_log: list[PolicyAuditEvent] = []
    
    async def evaluate(self, request: PolicyRequest) -> PolicyResult:
        """评估策略请求。
        
        Args:
            request: 策略请求
            
        Returns:
            策略结果
        """
        # 1. 检查缓存
        cached_result = self.cache.get(request)
        if cached_result is not None:
            return cached_result
        
        # 2. 评估策略
        result = await self._evaluate_policy(request)
        
        # 3. 缓存结果
        self.cache.set(request, result)
        
        # 4. 记录审计事件
        await self._record_audit_event(request, result)
        
        return result
    
    async def _evaluate_policy(self, request: PolicyRequest) -> PolicyResult:
        """执行策略评估逻辑。
        
        Args:
            request: 策略请求
            
        Returns:
            策略结果
        """
        # 1. 检查 RBAC 结果
        if request.rbac_result.decision == RBACDecision.DENY:
            return PolicyResult(
                request_id=request.request_id,
                decision=PolicyDecision.DENY,
                reason="RBAC evaluation denied the request",
                rbac_decision=request.rbac_result.decision,
                risk_level=request.risk_level,
                requires_approval=False,
            )
        
        # 2. 检查是否需要审批
        requires_approval = self.approval_matrix.requires_approval(
            request.operation,
            request.risk_level,
        )
        
        if requires_approval:
            return PolicyResult(
                request_id=request.request_id,
                decision=PolicyDecision.ESCALATE_TO_APPROVAL,
                reason=f"Operation requires approval (risk: {request.risk_level})",
                rbac_decision=request.rbac_result.decision,
                risk_level=request.risk_level,
                requires_approval=True,
                approval_reason=f"High-risk operation: {request.action_name}",
                effective_until=datetime.now(UTC) + timedelta(hours=1),
            )
        
        # 3. 允许执行
        return PolicyResult(
            request_id=request.request_id,
            decision=PolicyDecision.ALLOW,
            reason="RBAC approved and no approval required",
            rbac_decision=request.rbac_result.decision,
            risk_level=request.risk_level,
            requires_approval=False,
        )
    
    async def _record_audit_event(
        self,
        request: PolicyRequest,
        result: PolicyResult,
    ) -> None:
        """记录审计事件。
        
        Args:
            request: 策略请求
            result: 策略结果
        """
        import uuid
        
        event = PolicyAuditEvent(
            event_id=str(uuid.uuid4()),
            request_id=request.request_id,
            decision=result.decision,
            reason=result.reason,
            subject_id=request.rbac_result.subject.subject_id,
            resource_id=request.resource_id,
            operation=request.operation.value,
            risk_level=request.risk_level.value,
            timestamp=datetime.now(UTC),
        )
        
        self.audit_log.append(event)
    
    def get_audit_log(self) -> list[PolicyAuditEvent]:
        """获取审计日志。
        
        Returns:
            所有审计事件
        """
        return self.audit_log.copy()
    
    def clear_cache(self) -> None:
        """清空决策缓存."""
        self.cache.clear()
