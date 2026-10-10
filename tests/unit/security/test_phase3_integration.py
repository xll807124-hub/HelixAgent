"""
Phase 3 完整集成测试 - REQ-SEC-004 + REQ-SEC-005

展示沙箱隔离、连接器管理、凭据代理、撤销系统的完整工作流
"""
import pytest
from pydantic import HttpUrl
from src.security.sandbox.contracts import (
    FileSystemCapability,
    IsolationLevel,
    IsolationRequirement,
    NetworkCapability,
    SandboxBackendCapabilities,
)
from src.security.sandbox.connector_manager import (
    ConnectorDeclaration,
    ConnectorManager,
    DataClassification,
)
from src.security.sandbox.router import SandboxRouter
from src.security.credential.pdp_cdp import (
    CapabilityTokenRequest,
    CredentialCDP,
    CredentialPDP,
)


class TestPhase3Integration:
    """Phase 3 完整集成测试套件"""

    def test_complete_sandbox_and_credential_workflow(self):
        """
        完整工作流：
        1. 沙箱后端注册与路由
        2. 连接器声明、审批、绑定
        3. 凭据 PDP/CDP 完整流程
        """
        # ============ 第一步：沙箱系统初始化 ============
        
        router = SandboxRouter()
        
        # 注册 L2 后端
        l2_backend = SandboxBackendCapabilities(
            backend_id="gvisor-linux-l2-prod",
            isolation_level=IsolationLevel.L2,
            file_system={
                FileSystemCapability.WHITELIST_BASED,
                FileSystemCapability.TMPFS_ISOLATION,
            },
            network={
                NetworkCapability.DEFAULT_DENY,
                NetworkCapability.EGRESS_WHITELIST,
            },
            process={},
            resource={},
            audit={},
            tenant={},
            allocation_p95_ms=500,
            cost_per_hour=0.25,
            regions=["us-east-1"],
            is_production=True,
        )
        
        router.register_backend(l2_backend.backend_id, l2_backend)
        
        # ============ 第二步：连接器管理系统 ============
        
        connector_manager = ConnectorManager()
        
        # 声明连接器
        github_connector = ConnectorDeclaration(
            name="GitHub API Production",
            description="Production GitHub API access",
            owner="platform-team@company.com",
            environment="prod",
            target_service="github",
            target_endpoint=HttpUrl("https://api.github.com"),
            allowed_hosts=["api.github.com"],
            allowed_ports=[443],
            allowed_protocols=["https"],
            allowed_operations=["read", "write"],
            resource_scope="org/main-repo",
            data_classification=DataClassification.L2_INTERNAL,
            credential_type="github_app_token",
            required_scopes=["contents:read", "contents:write"],
        )
        
        connector_id = connector_manager.declare_connector(github_connector)
        
        # 审批连接器
        version_id = connector_manager.approve_connector(
            connector_id,
            approved_by="security-lead@company.com",
            approval_reason="Verified for production deployment",
        )
        
        assert version_id
        
        # ============ 第三步：路由决策 ============
        
        requirement = IsolationRequirement(
            min_isolation_level=IsolationLevel.L2,
            file_system_requirements={FileSystemCapability.TMPFS_ISOLATION},
            network_requirements={NetworkCapability.EGRESS_WHITELIST},
            max_cost_per_hour=0.50,
        )
        
        routing_decision = router.route(
            requirement,
            policy_version="policy-v1.0",
        )
        
        assert routing_decision.backend_id == l2_backend.backend_id
        assert routing_decision.isolation_level_assigned == IsolationLevel.L2
        
        # ============ 第四步：凭据代理 PDP/CDP ============
        
        pdp = CredentialPDP()
        cdp = CredentialCDP()
        
        # 构建令牌请求
        token_request = CapabilityTokenRequest(
            agent_svid="spiffe://example.com/agent/worker-001",
            task_id="task-001",
            worker_id="worker-001",
            target_service="github",
            target_resource="org/main-repo",
            requested_action="write",
            requested_scope=["contents:write"],
            policy_approval_ref="approval-123",
            justification="Deploy feature to main branch",
        )
        
        # PDP 验证和批准
        approved, reason, final_scope = pdp.verify_and_approve(
            request=token_request,
            policy_gateway_result=True,  # 策略网关批准
            rbac_result=True,             # RBAC 授权
            rbac_scope=["contents:read", "contents:write"],  # RBAC 允许的范围
        )
        
        assert approved
        assert "contents:write" in final_scope
        
        # CDP 签发令牌
        token_response = cdp.issue_token(
            request=token_request,
            pdp_approval=(approved, reason, final_scope),
            requested_ttl_seconds=3600,
        )
        
        assert token_response.token_id
        assert token_response.issued_token
        assert token_response.scope == final_scope
        
        # ============ 第五步：连接器绑定到任务 ============
        
        runtime_context = connector_manager.bind_connector_to_task(
            task_id="task-001",
            worker_id="worker-001",
            connector_id=connector_id,
            policy_version="policy-v1.0",
        )
        
        assert runtime_context.task_id == "task-001"
        assert runtime_context.connector_id == connector_id
        
        # ============ 第六步：网络策略验证 ============
        
        allowed, reason = connector_manager.verify_network_access(
            task_id="task-001",
            connector_id=connector_id,
            destination_host="api.github.com",
            destination_port=443,
            protocol="https",
        )
        
        assert allowed
        
        # ============ 第七步：审计追踪 ============
        
        # 验证路由审计
        routing_history = router.get_routing_history()
        assert len(routing_history) > 0
        
        # 验证连接器审计
        connector_audit = connector_manager.get_audit_log()
        assert any(log["action"] == "declare" for log in connector_audit)
        assert any(log["action"] == "approve" for log in connector_audit)
        assert any(log["action"] == "bind" for log in connector_audit)
        
        # 验证凭据审计
        pdp_events = pdp.get_audit_events()
        cdp_events = cdp.get_audit_events()
        assert len(pdp_events) > 0
        assert len(cdp_events) > 0
        
        print("=== Complete Phase 3 Workflow Succeeded ===")
        print(f"  Sandbox Router: {routing_decision.backend_id}")
        print(f"  Connector Version: {runtime_context.version_number}")
        print(f"  Token TTL: {(token_response.expires_at - token_response.issued_at).total_seconds()}s")
        print(f"  Granted Scope: {final_scope}")

    def test_multitenancy_isolation(self):
        """多租户隔离测试"""
        router = SandboxRouter()
        
        # 为不同租户注册不同的后端
        tenant_a_backend = SandboxBackendCapabilities(
            backend_id="gvisor-tenant-a",
            isolation_level=IsolationLevel.L2,
            file_system={FileSystemCapability.WHITELIST_BASED},
            network={NetworkCapability.DEFAULT_DENY},
            process={},
            resource={},
            audit={},
            tenant={},
            regions=["us-east-1"],
            is_production=True,
        )
        
        tenant_b_backend = SandboxBackendCapabilities(
            backend_id="kata-tenant-b",
            isolation_level=IsolationLevel.L3,
            file_system={FileSystemCapability.WHITELIST_BASED},
            network={NetworkCapability.DEFAULT_DENY},
            process={},
            resource={},
            audit={},
            tenant={},
            regions=["eu-west-1"],
            is_production=True,
        )
        
        router.register_backend(tenant_a_backend.backend_id, tenant_a_backend)
        router.register_backend(tenant_b_backend.backend_id, tenant_b_backend)
        
        # Tenant A 请求 L2 隔离，区域优先 US
        req_a = IsolationRequirement(
            min_isolation_level=IsolationLevel.L2,
            preferred_regions=["us-east-1"],
        )
        
        # Tenant B 请求 L3 隔离，区域优先 EU
        req_b = IsolationRequirement(
            min_isolation_level=IsolationLevel.L3,
            preferred_regions=["eu-west-1"],
        )
        
        decision_a = router.route(req_a, policy_version="policy-v1")
        decision_b = router.route(req_b, policy_version="policy-v1")
        
        # 验证隔离
        assert decision_a.backend_id == tenant_a_backend.backend_id
        assert decision_b.backend_id == tenant_b_backend.backend_id
        
        print("=== Multi-Tenant Isolation Verified ===")


    def test_scope_negotiation_and_least_privilege(self):
        """权限协商与最小权限原则"""
        pdp = CredentialPDP()
        
        # 请求特定权限
        request = CapabilityTokenRequest(
            agent_svid="spiffe://example.com/agent/worker-001",
            task_id="task-001",
            worker_id="worker-001",
            target_service="github",
            target_resource="org/repo",
            requested_action="write",
            requested_scope=["contents:write", "pull_requests:write", "admin:write"],
            policy_approval_ref="approval-123",
            justification="Deploy to main",
        )
        
        # RBAC 只允许读写，不允许管理员权限
        approved, reason, final_scope = pdp.verify_and_approve(
            request=request,
            policy_gateway_result=True,
            rbac_result=True,
            rbac_scope=["contents:read", "contents:write", "pull_requests:read"],
        )
        
        assert approved
        # 交集：contents:write（在请求的 write 列表中，也在 RBAC 中）
        assert "contents:write" in final_scope
        # admin:write 被拒绝（不在 RBAC 中）
        assert "admin:write" not in final_scope
        # pull_requests:write 被拒绝（RBAC 只有 read）
        assert "pull_requests:write" not in final_scope
        
        print("=== Least Privilege Principle Verified ===")
        print(f"  Requested: {request.requested_scope}")
        print(f"  RBAC Allowed: {['contents:read', 'contents:write', 'pull_requests:read']}")
        print(f"  Final Granted: {final_scope}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
