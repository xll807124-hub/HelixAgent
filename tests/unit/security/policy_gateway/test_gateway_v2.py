"""
Policy Gateway Phase 2 单元测试。

测试完整的策略决策流程。
"""

import pytest
from pydantic import ValidationError

from src.security.policy_gateway.gateway_v2 import (
    ApprovalMatrix,
    PolicyDecision,
    PolicyDecisionCache,
    PolicyGateway,
    PolicyRequest,
    PolicyResult,
    RiskLevel,
)
from src.security.rbac.models import (
    AuthorizationDecision,
    AuthorizationResult,
    Operation,
    Resource,
    ResourceType,
    RoleType,
    Subject,
    SubjectType,
)


@pytest.fixture
def subject() -> Subject:
    """创建测试主体."""
    return Subject(
        subject_id="user_001",
        subject_type=SubjectType.USER,
        organization_id="org_001",
        roles=frozenset([RoleType.DEVELOPER]),
    )


@pytest.fixture
def resource() -> Resource:
    """创建测试资源."""
    return Resource(
        resource_id="repo_001",
        resource_type=ResourceType.REPOSITORY,
        organization_id="org_001",
    )


@pytest.fixture
def allow_rbac_result(subject, resource) -> AuthorizationResult:
    """创建允许的 RBAC 结果."""
    return AuthorizationResult(
        request_id="rbac_001",
        decision=AuthorizationDecision.ALLOW,
        subject=subject,
        resource=resource,
        operation=Operation.READ,
    )


@pytest.fixture
def deny_rbac_result(subject, resource) -> AuthorizationResult:
    """创建拒绝的 RBAC 结果."""
    return AuthorizationResult(
        request_id="rbac_002",
        decision=AuthorizationDecision.DENY,
        subject=subject,
        resource=resource,
        operation=Operation.MANAGE_POLICIES,
        reason="Access denied",
    )


@pytest.fixture
def policy_gateway() -> PolicyGateway:
    """创建策略网关."""
    return PolicyGateway()


class TestApprovalMatrix:
    """测试审批矩阵."""
    
    def test_low_risk_no_approval(self):
        """低风险不需要审批."""
        matrix = ApprovalMatrix()
        result = matrix.requires_approval(Operation.READ, RiskLevel.LOW)
        assert result is False
    
    def test_high_risk_requires_approval(self):
        """高风险需要审批."""
        matrix = ApprovalMatrix()
        result = matrix.requires_approval(Operation.READ, RiskLevel.HIGH)
        assert result is True
    
    def test_critical_risk_requires_approval(self):
        """极端风险需要审批."""
        matrix = ApprovalMatrix()
        result = matrix.requires_approval(Operation.READ, RiskLevel.CRITICAL)
        assert result is True
    
    def test_operation_override(self):
        """操作级覆盖优先."""
        matrix = ApprovalMatrix()
        # MANAGE_POLICIES 总是需要审批，即使风险等级低
        result = matrix.requires_approval(Operation.MANAGE_POLICIES, RiskLevel.LOW)
        assert result is True
    
    def test_custom_approval_matrix(self):
        """自定义审批矩阵."""
        custom_matrix = ApprovalMatrix(
            approval_required={
                RiskLevel.LOW: False,
                RiskLevel.MEDIUM: True,
                RiskLevel.HIGH: True,
                RiskLevel.CRITICAL: True,
            }
        )
        assert custom_matrix.requires_approval(Operation.READ, RiskLevel.MEDIUM) is True


class TestPolicyDecisionCache:
    """测试决策缓存."""
    
    def test_cache_set_get(self, allow_rbac_result):
        """测试缓存设置和获取."""
        cache = PolicyDecisionCache()
        
        request = PolicyRequest(
            request_id="req_001",
            action_id="action_001",
            action_name="read_file",
            operation=Operation.READ,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        result = PolicyResult(
            request_id="req_001",
            decision=PolicyDecision.ALLOW,
            reason="Cached",
            rbac_decision=AuthorizationDecision.ALLOW,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
        )
        
        cache.set(request, result)
        cached = cache.get(request)
        
        assert cached is not None
        assert cached.decision == PolicyDecision.ALLOW
    
    def test_cache_expiration(self, allow_rbac_result):
        """测试缓存过期."""
        cache = PolicyDecisionCache(ttl_seconds=0)  # 立即过期
        
        request = PolicyRequest(
            request_id="req_001",
            action_id="action_001",
            action_name="read_file",
            operation=Operation.READ,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        result = PolicyResult(
            request_id="req_001",
            decision=PolicyDecision.ALLOW,
            reason="Test",
            rbac_decision=AuthorizationDecision.ALLOW,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
        )
        
        cache.set(request, result)
        # 缓存应该过期
        cached = cache.get(request)
        assert cached is None
    
    def test_cache_clear(self, allow_rbac_result):
        """测试清空缓存."""
        cache = PolicyDecisionCache()
        
        request = PolicyRequest(
            request_id="req_001",
            action_id="action_001",
            action_name="read_file",
            operation=Operation.READ,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        result = PolicyResult(
            request_id="req_001",
            decision=PolicyDecision.ALLOW,
            reason="Test",
            rbac_decision=AuthorizationDecision.ALLOW,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
        )
        
        cache.set(request, result)
        cache.clear()
        
        cached = cache.get(request)
        assert cached is None


class TestPolicyGateway:
    """测试策略网关."""
    
    @pytest.mark.asyncio
    async def test_allow_low_risk(self, policy_gateway, allow_rbac_result):
        """测试允许低风险操作."""
        request = PolicyRequest(
            request_id="req_001",
            action_id="action_001",
            action_name="read_file",
            operation=Operation.READ,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        result = await policy_gateway.evaluate(request)
        
        assert result.decision == PolicyDecision.ALLOW
        assert result.requires_approval is False
    
    @pytest.mark.asyncio
    async def test_deny_rbac_denied(self, policy_gateway, deny_rbac_result):
        """测试 RBAC 拒绝时的策略决策."""
        request = PolicyRequest(
            request_id="req_002",
            action_id="action_002",
            action_name="manage_policy",
            operation=Operation.MANAGE_POLICIES,
            rbac_result=deny_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        result = await policy_gateway.evaluate(request)
        
        assert result.decision == PolicyDecision.DENY
        assert "RBAC" in result.reason
    
    @pytest.mark.asyncio
    async def test_escalate_high_risk(self, policy_gateway, allow_rbac_result):
        """测试高风险操作升级到审批."""
        request = PolicyRequest(
            request_id="req_003",
            action_id="action_003",
            action_name="manage_members",
            operation=Operation.MANAGE_MEMBERS,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.HIGH,
            resource_id="repo_001",
        )
        
        result = await policy_gateway.evaluate(request)
        
        assert result.decision == PolicyDecision.ESCALATE_TO_APPROVAL
        assert result.requires_approval is True
        assert result.approval_reason is not None
    
    @pytest.mark.asyncio
    async def test_escalate_critical_risk(self, policy_gateway, allow_rbac_result):
        """测试极端风险操作升级到审批."""
        request = PolicyRequest(
            request_id="req_004",
            action_id="action_004",
            action_name="manage_policies",
            operation=Operation.MANAGE_POLICIES,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.LOW,  # 风险等级低，但操作需要审批
            resource_id="repo_001",
        )
        
        result = await policy_gateway.evaluate(request)
        
        assert result.decision == PolicyDecision.ESCALATE_TO_APPROVAL
        assert result.requires_approval is True
    
    @pytest.mark.asyncio
    async def test_cache_hit(self, policy_gateway, allow_rbac_result):
        """测试缓存命中."""
        request = PolicyRequest(
            request_id="req_005",
            action_id="action_005",
            action_name="read_file",
            operation=Operation.READ,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        # 第一次评估
        result1 = await policy_gateway.evaluate(request)
        assert result1.decision == PolicyDecision.ALLOW
        
        # 第二次应该命中缓存
        result2 = await policy_gateway.evaluate(request)
        assert result2.decision == PolicyDecision.ALLOW
        assert len(policy_gateway.audit_log) == 1  # 只有一条审计记录
    
    @pytest.mark.asyncio
    async def test_audit_logging(self, policy_gateway, allow_rbac_result):
        """测试审计记录."""
        request = PolicyRequest(
            request_id="req_006",
            action_id="action_006",
            action_name="read_file",
            operation=Operation.READ,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        await policy_gateway.evaluate(request)
        
        audit_log = policy_gateway.get_audit_log()
        assert len(audit_log) == 1
        
        event = audit_log[0]
        assert event.request_id == "req_006"
        assert event.decision == PolicyDecision.ALLOW
        assert event.subject_id == "user_001"
        assert event.resource_id == "repo_001"
    
    @pytest.mark.asyncio
    async def test_multiple_decisions(self, policy_gateway, allow_rbac_result, deny_rbac_result):
        """测试多个决策."""
        # 允许的请求
        allow_request = PolicyRequest(
            request_id="req_007",
            action_id="action_007",
            action_name="read_file",
            operation=Operation.READ,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        # 拒绝的请求
        deny_request = PolicyRequest(
            request_id="req_008",
            action_id="action_008",
            action_name="manage_policy",
            operation=Operation.MANAGE_POLICIES,
            rbac_result=deny_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        allow_result = await policy_gateway.evaluate(allow_request)
        deny_result = await policy_gateway.evaluate(deny_request)
        
        assert allow_result.decision == PolicyDecision.ALLOW
        assert deny_result.decision == PolicyDecision.DENY
        
        audit_log = policy_gateway.get_audit_log()
        assert len(audit_log) == 2


class TestPolicyRequest:
    """测试策略请求模型."""
    
    def test_policy_request_creation(self, allow_rbac_result):
        """测试创建策略请求."""
        request = PolicyRequest(
            request_id="req_001",
            action_id="action_001",
            action_name="read_file",
            operation=Operation.READ,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        assert request.request_id == "req_001"
        assert request.action_name == "read_file"
        assert request.risk_level == RiskLevel.LOW
        assert request.timestamp is not None
    
    def test_policy_request_immutability(self, allow_rbac_result):
        """测试策略请求不可变性."""
        request = PolicyRequest(
            request_id="req_001",
            action_id="action_001",
            action_name="read_file",
            operation=Operation.READ,
            rbac_result=allow_rbac_result,
            risk_level=RiskLevel.LOW,
            resource_id="repo_001",
        )
        
        with pytest.raises(ValidationError):  # frozen=True
            request.request_id = "req_002"


class TestPolicyResult:
    """测试策略结果模型."""
    
    def test_policy_result_creation(self):
        """测试创建策略结果."""
        result = PolicyResult(
            request_id="req_001",
            decision=PolicyDecision.ALLOW,
            reason="Test",
            rbac_decision=AuthorizationDecision.ALLOW,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
        )
        
        assert result.request_id == "req_001"
        assert result.decision == PolicyDecision.ALLOW
        assert result.timestamp is not None
    
    def test_policy_result_with_approval(self):
        """测试带审批的策略结果."""
        result = PolicyResult(
            request_id="req_002",
            decision=PolicyDecision.ESCALATE_TO_APPROVAL,
            reason="Needs approval",
            rbac_decision=AuthorizationDecision.ALLOW,
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            approval_reason="High-risk operation",
        )
        
        assert result.decision == PolicyDecision.ESCALATE_TO_APPROVAL
        assert result.requires_approval is True
        assert result.approval_reason == "High-risk operation"
