"""
Phase 3 快速参考指南 - 核心 API 与使用示例
"""

# ============================================================================
# 1. 沙箱路由 API
# ============================================================================

from src.security.sandbox.router import SandboxRouter
from src.security.sandbox.contracts import (
    SandboxBackendCapabilities, IsolationLevel, IsolationRequirement
)

# 初始化路由器
router = SandboxRouter()

# 注册后端
backend = SandboxBackendCapabilities(
    backend_id="gvisor-prod",
    isolation_level=IsolationLevel.L2,
    file_system={...},
    network={...},
    ...
)
router.register_backend(backend.backend_id, backend)

# 路由决策
requirement = IsolationRequirement(
    min_isolation_level=IsolationLevel.L2,
    max_cost_per_hour=0.50,
    preferred_regions=["us-east-1"]
)
decision = router.route(requirement, policy_version="policy-v1")
print(f"选定后端: {decision.backend_id}")


# ============================================================================
# 2. 连接器管理 API
# ============================================================================

from src.security.sandbox.connector_manager import (
    ConnectorManager, ConnectorDeclaration, DataClassification
)
from pydantic import HttpUrl

manager = ConnectorManager()

# 阶段 1: 声明
connector = ConnectorDeclaration(
    name="GitHub API",
    owner="platform-team@company.com",
    target_service="github",
    target_endpoint=HttpUrl("https://api.github.com"),
    allowed_hosts=["api.github.com"],
    allowed_ports=[443],
    allowed_protocols=["https"],
    allowed_operations=["read", "write"],
    resource_scope="org/repo-*",
    data_classification=DataClassification.L2_INTERNAL,
    credential_type="github_app_token",
    required_scopes=["contents:read", "contents:write"],
)
connector_id = manager.declare_connector(connector)

# 阶段 2: 审批（产生版本）
version_id = manager.approve_connector(
    connector_id,
    approved_by="security-lead@company.com"
)

# 阶段 3: 绑定到任务
context = manager.bind_connector_to_task(
    task_id="task-001",
    worker_id="worker-001",
    connector_id=connector_id,
    policy_version="policy-v1"
)

# 阶段 4: 运行时验证网络访问
allowed, reason = manager.verify_network_access(
    task_id="task-001",
    connector_id=connector_id,
    destination_host="api.github.com",
    destination_port=443,
    protocol="https"
)

if not allowed:
    raise PermissionError(f"Network access denied: {reason}")


# ============================================================================
# 3. 凭据 PDP/CDP API
# ============================================================================

from src.security.credential.pdp_cdp import (
    CredentialPDP, CredentialCDP, CapabilityTokenRequest
)

pdp = CredentialPDP()
cdp = CredentialCDP()

# 构建令牌请求
request = CapabilityTokenRequest(
    agent_svid="spiffe://example.com/agent/worker-001",
    task_id="task-001",
    worker_id="worker-001",
    target_service="github",
    target_resource="org/repo",
    requested_action="write",
    requested_scope=["contents:write"],
    policy_approval_ref="approval-123",
    justification="Deploy feature"
)

# PDP: 验证和批准（权限协商）
approved, reason, final_scope = pdp.verify_and_approve(
    request=request,
    policy_gateway_result=True,        # 策略网关已批准
    rbac_result=True,                   # RBAC 已授权
    rbac_scope=["contents:read", "contents:write"]  # RBAC 允许的范围
)

if not approved:
    raise PermissionError(f"PDP rejected: {reason}")

# CDP: 铸造短期令牌
response = cdp.issue_token(
    request=request,
    pdp_approval=(approved, reason, final_scope),
    requested_ttl_seconds=3600  # 请求 1 小时 TTL
)

print(f"令牌 ID: {response.token_id}")
print(f"过期时间: {response.expires_at}")
print(f"授予权限: {response.scope}")

# 使用令牌...

# 撤销令牌
cdp.revoke_token(response.token_id, reason="Task completed")


# ============================================================================
# 4. 分布式撤销 API
# ============================================================================

from src.security.credential.revocation import (
    RevocationBroker, RevocationCoordinator, RevocationEvent
)
import asyncio

async def revoke_token():
    broker = RevocationBroker()
    coordinator = RevocationCoordinator(
        broker,
        propagation_timeout_seconds=5.0
    )
    
    # 请求撤销
    success = await coordinator.request_revocation(
        token_id="token-001",
        task_id="task-001",
        reason="Kill Switch activated",
        triggered_by="kill_switch"
    )
    
    if not success:
        raise RuntimeError("Failed to publish revocation")
    
    # 等待全局传播
    success, confirmed = await coordinator.wait_for_propagation(
        revocation_id="rev-123",
        expected_instances={"cdp-1", "cdp-2", "cdp-3"}
    )
    
    if not success:
        print(f"Warning: Revocation timeout, only {len(confirmed)} confirmed")

asyncio.run(revoke_token())


# ============================================================================
# 5. 审计日志查询
# ============================================================================

# 路由审计
routing_history = router.get_routing_history(limit=100)
for decision in routing_history:
    print(f"Backend: {decision.backend_id}, Reason: {decision.reason}")

# 连接器审计
connector_log = manager.get_audit_log(limit=50)
for entry in connector_log:
    print(f"{entry['action']}: {entry['connector_id']} by {entry.get('approved_by', 'N/A')}")

# 凭据审计 (PDP)
pdp_events = pdp.get_audit_events()
for event in pdp_events:
    print(f"PDP Event: {event.action}, Decision: {event.decision}")

# 凭据审计 (CDP)
cdp_events = cdp.get_audit_events()
for event in cdp_events:
    print(f"CDP Event: {event.action}, Token: {event.token_id}")

# 撤销审计
revocation_log = coordinator.get_audit_log()
for entry in revocation_log:
    print(f"Revocation: {entry['token_id']}, Status: {entry['status']}")


# ============================================================================
# 6. 常见错误处理
# ============================================================================

# 错误 1: 无满足条件的后端
try:
    req = IsolationRequirement(min_isolation_level=IsolationLevel.L3)
    decision = router.route(req, policy_version="policy-v1")
except ValueError as e:
    print(f"Routing failed: {e}")
    # 处理: 检查可用后端、策略需求

# 错误 2: 超出预算
try:
    req = IsolationRequirement(
        min_isolation_level=IsolationLevel.L3,
        max_cost_per_hour=0.01  # 太低
    )
    decision = router.route(req, policy_version="policy-v1")
except ValueError as e:
    print(f"Budget exceeded: {e}")
    # 处理: 增加预算或选择低隔离级别

# 错误 3: 凭据拒绝
try:
    approved, reason, scope = pdp.verify_and_approve(
        request, False, False, []  # RBAC 拒绝
    )
    if not approved:
        raise PermissionError(reason)
except PermissionError as e:
    print(f"Credential rejected: {e}")
    # 处理: 检查用户权限、联系安全团队

# 错误 4: CDP 不可用
try:
    cdp.set_health(False)
    response = cdp.issue_token(request, pdp_approval)
except RuntimeError as e:
    print(f"CDP unavailable: {e}")
    # 处理: 等待 CDP 恢复，触发告警


# ============================================================================
# 7. 完整端到端示例
# ============================================================================

def complete_workflow_example():
    """完整的请求→路由→凭据→撤销工作流"""
    
    # 1. 路由
    requirement = IsolationRequirement(
        min_isolation_level=IsolationLevel.L2,
        max_cost_per_hour=0.50
    )
    routing = router.route(requirement, policy_version="policy-v1")
    print(f"1. 路由完成: {routing.backend_id}")
    
    # 2. 绑定连接器
    context = manager.bind_connector_to_task(
        task_id="task-001",
        worker_id="worker-001",
        connector_id="github-prod",
        policy_version="policy-v1"
    )
    print(f"2. 连接器绑定: {context.connector_id} v{context.version_number}")
    
    # 3. 凭据签发
    token_req = CapabilityTokenRequest(
        agent_svid="spiffe://example.com/worker-001",
        task_id="task-001",
        worker_id="worker-001",
        target_service="github",
        target_resource="org/repo",
        requested_action="write",
        requested_scope=["contents:write"],
        policy_approval_ref="approval-123",
        justification="Deploy to main"
    )
    
    approved, reason, scope = pdp.verify_and_approve(
        request=token_req,
        policy_gateway_result=True,
        rbac_result=True,
        rbac_scope=["contents:write"]
    )
    
    token_resp = cdp.issue_token(
        request=token_req,
        pdp_approval=(approved, reason, scope)
    )
    print(f"3. 凭据签发: {token_resp.token_id}, TTL {(token_resp.expires_at - token_resp.issued_at).total_seconds()}s")
    
    # 4. 任务执行期间验证网络
    allowed, msg = manager.verify_network_access(
        task_id="task-001",
        connector_id="github-prod",
        destination_host="api.github.com",
        destination_port=443,
        protocol="https"
    )
    print(f"4. 网络验证: {'✓' if allowed else '✗'} {msg}")
    
    # 5. 任务完成，撤销凭据
    cdp.revoke_token(token_resp.token_id, reason="Task completed")
    print(f"5. 凭据撤销: {token_resp.token_id}")
    
    # 6. 查看审计
    print("\n审计追踪:")
    for log in manager.get_audit_log()[-3:]:
        print(f"  - {log['action']}: {log['connector_id']}")


# ============================================================================
# 8. 配置最佳实践
# ============================================================================

"""
# .env 配置示例
SANDBOX_ISOLATION_LEVEL=L2
SANDBOX_COST_LIMIT=0.50
SANDBOX_PREFERRED_REGION=us-east-1

CREDENTIAL_GITHUB_TTL=3600
CREDENTIAL_AWS_TTL=900
CREDENTIAL_OAUTH_TTL=1800

REVOCATION_TIMEOUT_SECONDS=5
REVOCATION_CACHE_TTL_SECONDS=3600

POLICY_VERSION=policy-v1.0
AUDIT_LEVEL=DEBUG
"""


# ============================================================================
# 9. 监控指标
# ============================================================================

def print_monitoring_metrics():
    """打印关键监控指标"""
    
    # 路由器指标
    router_stats = router.get_backend_stats()
    print("=== 路由器统计 ===")
    print(f"总后端数: {router_stats['total_backends']}")
    print(f"健康后端: {router_stats['healthy_backends']}")
    
    # 凭据指标
    cdp_stats = cdp.get_rental_stats()
    print("\n=== 凭据统计 ===")
    print(f"活跃租约: {cdp_stats['total_active_rentals']}")
    print(f"按服务: {cdp_stats['by_service']}")
    
    # 清理过期
    cleaned = cdp.cleanup_expired_tokens()
    print(f"清理过期令牌: {cleaned}")


# ============================================================================
# 10. 测试工具函数
# ============================================================================

def create_test_backend(backend_id: str, isolation_level: IsolationLevel):
    """创建测试用后端"""
    return SandboxBackendCapabilities(
        backend_id=backend_id,
        isolation_level=isolation_level,
        file_system={FileSystemCapability.WHITELIST_BASED},
        network={NetworkCapability.DEFAULT_DENY},
        process=set(),
        resource=set(),
        audit=set(),
        tenant=set(),
        regions=["us-east-1"],
        is_production=False,
    )

def create_test_connector(connector_id: str, service: str):
    """创建测试用连接器"""
    return ConnectorDeclaration(
        name=f"Test {service}",
        owner="test@example.com",
        target_service=service,
        target_endpoint=HttpUrl(f"https://api.{service}.com"),
        allowed_hosts=[f"api.{service}.com"],
        allowed_ports=[443],
        allowed_protocols=["https"],
        allowed_operations=["read", "write"],
        resource_scope="test/*",
        data_classification=DataClassification.L1_PUBLIC,
        credential_type=f"{service}_token",
    )
