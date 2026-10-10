"""
凭据代理 PDP/CDP 测试 - REQ-SEC-005

测试覆盖：
1. PDP 授权决策
2. CDP 令牌签发
3. 撤销机制
4. Fail-secure 语义
5. 租约管理
"""
import pytest
from datetime import datetime, timedelta
from src.security.credential.pdp_cdp import (
    CapabilityTokenRequest,
    CapabilityTokenType,
    CredentialAuditAction,
    CredentialCDP,
    CredentialPDP,
)


@pytest.fixture
def pdp():
    """创建 PDP"""
    return CredentialPDP()


@pytest.fixture
def cdp():
    """创建 CDP"""
    return CredentialCDP()


@pytest.fixture
def token_request():
    """创建令牌请求"""
    return CapabilityTokenRequest(
        agent_svid="spiffe://example.com/agent/worker-001",
        task_id="task-001",
        worker_id="worker-001",
        target_service="github",
        target_resource="org/repo",
        requested_action="write",
        requested_scope=["contents:write", "pull_requests:write"],
        policy_approval_ref="approval-123",
        justification="Deploy new feature to main branch",
    )


# 测试：PDP 授权决策
def test_pdp_approve_valid_request(pdp, token_request):
    """测试 PDP 批准有效请求"""
    approved, reason, scope = pdp.verify_and_approve(
        request=token_request,
        policy_gateway_result=True,
        rbac_result=True,
        rbac_scope=["contents:write", "pull_requests:write"],
    )
    
    assert approved
    assert "contents:write" in scope
    assert "pull_requests:write" in scope


def test_pdp_deny_policy_gateway_rejects(pdp, token_request):
    """测试 PDP 在 Policy Gateway 拒绝时拒绝"""
    approved, reason, scope = pdp.verify_and_approve(
        request=token_request,
        policy_gateway_result=False,
        rbac_result=True,
        rbac_scope=["contents:write"],
    )
    
    assert not approved
    assert "Policy Gateway" in reason


def test_pdp_deny_rbac_rejects(pdp, token_request):
    """测试 PDP 在 RBAC 拒绝时拒绝"""
    approved, reason, scope = pdp.verify_and_approve(
        request=token_request,
        policy_gateway_result=True,
        rbac_result=False,
        rbac_scope=[],
    )
    
    assert not approved
    assert "RBAC" in reason


def test_pdp_narrow_scope_by_rbac(pdp, token_request):
    """测试 PDP 通过 RBAC 缩小权限范围"""
    # 请求是 ["contents:write", "pull_requests:write"]
    # RBAC 允许 ["contents:read", "contents:write"]
    # 交集应该是 ["contents:write"]
    approved, reason, scope = pdp.verify_and_approve(
        request=token_request,
        policy_gateway_result=True,
        rbac_result=True,
        rbac_scope=["contents:read", "contents:write"],  # 包含请求中的 contents:write
    )
    
    assert approved
    assert "contents:write" in scope  # 请求的 write 权限被授予
    assert "pull_requests:write" not in scope  # pull_requests:write 被RBAC拒绝


def test_pdp_no_scope_intersection(pdp, token_request):
    """测试 PDP 在没有权限交集时拒绝"""
    token_request.requested_scope = ["admin:write"]
    
    approved, reason, scope = pdp.verify_and_approve(
        request=token_request,
        policy_gateway_result=True,
        rbac_result=True,
        rbac_scope=["contents:read"],  # 与请求无交集
    )
    
    assert not approved
    assert "outside of RBAC" in reason


def test_pdp_audit_log(pdp, token_request):
    """测试 PDP 审计记录"""
    pdp.verify_and_approve(
        request=token_request,
        policy_gateway_result=True,
        rbac_result=True,
        rbac_scope=["contents:write"],
    )
    
    events = pdp.get_audit_events()
    assert len(events) > 0
    assert events[-1].action == CredentialAuditAction.ISSUED
    assert events[-1].granted_scope == ["contents:write"]


# 测试：CDP 令牌签发
def test_cdp_issue_token(cdp, token_request):
    """测试 CDP 签发令牌"""
    pdp_approval = (True, "Approved", ["contents:write"])
    
    response = cdp.issue_token(
        request=token_request,
        pdp_approval=pdp_approval,
        requested_ttl_seconds=3600,
    )
    
    assert response.token_id
    assert response.issued_token
    assert response.token_type == CapabilityTokenType.GITHUB_APP_TOKEN
    assert response.scope == ["contents:write"]
    assert response.expires_at > datetime.utcnow()


def test_cdp_ttl_limit_github(cdp, token_request):
    """测试 CDP GitHub 的 TTL 限制"""
    pdp_approval = (True, "Approved", ["contents:write"])
    
    response = cdp.issue_token(
        request=token_request,
        pdp_approval=pdp_approval,
        requested_ttl_seconds=7200,  # 请求 2 小时
    )
    
    # GitHub 最大 1 小时
    ttl = (response.expires_at - response.issued_at).total_seconds()
    assert ttl <= 3600


def test_cdp_ttl_limit_aws(cdp):
    """测试 CDP AWS 的 TTL 限制"""
    request = CapabilityTokenRequest(
        agent_svid="spiffe://example.com/agent/worker-001",
        task_id="task-001",
        worker_id="worker-001",
        target_service="aws",
        target_resource="arn:aws:iam::123456789:role/AgentRole",
        requested_action="assume",
        policy_approval_ref="approval-123",
        justification="Assume role for S3 access",
    )
    
    pdp_approval = (True, "Approved", ["sts:AssumeRole"])
    
    response = cdp.issue_token(
        request=request,
        pdp_approval=pdp_approval,
        requested_ttl_seconds=1800,  # 请求 30 分钟
    )
    
    # AWS STS 最大 15 分钟
    ttl = (response.expires_at - response.issued_at).total_seconds()
    assert ttl <= 900


def test_cdp_reject_pdp_denied(cdp, token_request):
    """测试 CDP 拒绝 PDP 拒绝的请求"""
    pdp_approval = (False, "Policy denied", [])
    
    with pytest.raises(ValueError, match="PDP rejected"):
        cdp.issue_token(
            request=token_request,
            pdp_approval=pdp_approval,
        )


def test_cdp_fail_secure_when_unhealthy(cdp, token_request):
    """测试 CDP 不健康时 fail-secure"""
    cdp.set_health(False)
    
    pdp_approval = (True, "Approved", ["contents:write"])
    
    with pytest.raises(RuntimeError, match="CDP is not healthy"):
        cdp.issue_token(
            request=token_request,
            pdp_approval=pdp_approval,
        )


# 测试：撤销
def test_cdp_revoke_token(cdp, token_request):
    """测试 CDP 撤销令牌"""
    pdp_approval = (True, "Approved", ["contents:write"])
    response = cdp.issue_token(token_request, pdp_approval)
    
    cdp.revoke_token(response.token_id, "Manual revocation")
    
    events = cdp.get_audit_events()
    revoke_event = [e for e in events if e.action == CredentialAuditAction.REVOKED]
    assert len(revoke_event) > 0


# 测试：租约管理
def test_cdp_rental_stats(cdp, token_request):
    """测试 CDP 租约统计"""
    pdp_approval = (True, "Approved", ["contents:write"])
    
    response1 = cdp.issue_token(token_request, pdp_approval)
    
    request2 = CapabilityTokenRequest(
        agent_svid="spiffe://example.com/agent/worker-001",
        task_id="task-002",
        worker_id="worker-001",
        target_service="aws",
        target_resource="arn:aws:iam::123456789:role/Role",
        requested_action="assume",
        policy_approval_ref="approval-456",
        justification="AWS access",
    )
    response2 = cdp.issue_token(request2, pdp_approval)
    
    stats = cdp.get_rental_stats()
    assert stats["total_active_rentals"] == 2
    assert stats["by_service"]["github"] == 1
    assert stats["by_service"]["aws"] == 1


def test_cdp_cleanup_expired_tokens(cdp, token_request):
    """测试 CDP 清理过期令牌"""
    pdp_approval = (True, "Approved", ["contents:write"])
    response = cdp.issue_token(
        token_request,
        pdp_approval,
        requested_ttl_seconds=1,  # 1 秒后过期
    )
    
    import time
    time.sleep(2)  # 等待过期
    
    cleaned = cdp.cleanup_expired_tokens()
    assert cleaned >= 1
    
    stats = cdp.get_rental_stats()
    assert stats["total_active_rentals"] == 0


# 测试：Token 类型映射
def test_token_type_mapping(cdp):
    """测试不同服务的令牌类型映射"""
    test_cases = [
        ("github", CapabilityTokenType.GITHUB_APP_TOKEN),
        ("aws", CapabilityTokenType.AWS_STS_TOKEN),
        ("gcp", CapabilityTokenType.GCP_TOKEN),
        ("generic_oauth", CapabilityTokenType.OAUTH_TOKEN),
    ]
    
    for service, expected_type in test_cases:
        token_type = cdp._get_token_type(service)
        assert token_type == expected_type


# 测试：审计不包含令牌内容
def test_audit_no_token_content(cdp, token_request):
    """测试审计日志不包含令牌内容"""
    pdp_approval = (True, "Approved", ["contents:write"])
    response = cdp.issue_token(token_request, pdp_approval)
    
    events = cdp.get_audit_events()
    issued_events = [e for e in events if e.action == CredentialAuditAction.ISSUED]
    
    for event in issued_events:
        # 审计事件应该包含 token_id 但不包含实际的凭据内容
        assert event.token_id  # 有 token_id 用于追踪
        # 不应该存储实际的 token 值（这由 issued_token 字段负责，但不在审计中）
        assert not hasattr(event, "issued_token") or event.issued_token is None


# 集成测试：PDP + CDP 完整流程
def test_pdp_cdp_integration(pdp, cdp, token_request):
    """测试 PDP + CDP 完整流程"""
    # 步骤 1：PDP 验证和批准
    approved, reason, scope = pdp.verify_and_approve(
        request=token_request,
        policy_gateway_result=True,
        rbac_result=True,
        rbac_scope=["contents:write", "pull_requests:write"],
    )
    
    assert approved
    
    # 步骤 2：CDP 签发令牌
    response = cdp.issue_token(
        request=token_request,
        pdp_approval=(approved, reason, scope),
    )
    
    assert response.token_id
    assert response.issued_token
    assert response.token_type == CapabilityTokenType.GITHUB_APP_TOKEN
    assert response.scope == scope
    
    # 步骤 3：验证审计
    pdp_events = pdp.get_audit_events()
    cdp_events = cdp.get_audit_events()
    
    assert len(pdp_events) > 0
    assert len(cdp_events) > 0
    assert pdp_events[-1].action == CredentialAuditAction.ISSUED
    assert cdp_events[-1].action == CredentialAuditAction.ISSUED
