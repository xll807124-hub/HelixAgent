"""
沙箱路由器测试 - REQ-SEC-004

测试覆盖：
1. 后端注册与能力声明
2. 多维路由与后端选择
3. 单调升级原则
4. 成本闸门
5. 路由决策审计
"""
import pytest
from src.security.sandbox.contracts import (
    AuditCapability,
    FileSystemCapability,
    IsolationLevel,
    IsolationRequirement,
    NetworkCapability,
    ProcessCapability,
    ResourceCapability,
    SandboxBackendCapabilities,
)
from src.security.sandbox.router import SandboxRouter


@pytest.fixture
def router():
    """创建路由器"""
    return SandboxRouter()


@pytest.fixture
def linux_l1_backend():
    """L1 基础后端"""
    return SandboxBackendCapabilities(
        backend_id="docker-linux-l1-prod",
        isolation_level=IsolationLevel.L1,
        file_system={
            FileSystemCapability.WHITELIST_BASED,
            FileSystemCapability.TMPFS_ISOLATION,
        },
        network={
            NetworkCapability.DEFAULT_DENY,
            NetworkCapability.EGRESS_WHITELIST,
        },
        process={ProcessCapability.PID_ISOLATION},
        resource={
            ResourceCapability.CPU_LIMIT,
            ResourceCapability.MEMORY_LIMIT,
        },
        audit={AuditCapability.CONTAINER_LIFECYCLE},
        tenant={},
        allocation_p95_ms=300,
        cost_per_hour=0.10,
        regions=["us-east-1", "us-west-2"],
        is_production=True,
    )


@pytest.fixture
def linux_l2_backend():
    """L2 增强后端"""
    return SandboxBackendCapabilities(
        backend_id="gvisor-linux-l2-prod",
        isolation_level=IsolationLevel.L2,
        file_system={
            FileSystemCapability.WHITELIST_BASED,
            FileSystemCapability.TMPFS_ISOLATION,
            FileSystemCapability.READONLY_ROOT,
        },
        network={
            NetworkCapability.DEFAULT_DENY,
            NetworkCapability.EGRESS_WHITELIST,
            NetworkCapability.DNS_CONTROL,
            NetworkCapability.PROXY_REQUIRED,
        },
        process={
            ProcessCapability.SECCOMP,
            ProcessCapability.PID_ISOLATION,
            ProcessCapability.NO_SYS_ADMIN,
        },
        resource={
            ResourceCapability.CPU_LIMIT,
            ResourceCapability.MEMORY_LIMIT,
            ResourceCapability.FORK_LIMIT,
        },
        audit={
            AuditCapability.CONTAINER_LIFECYCLE,
            AuditCapability.POLICY_VIOLATIONS,
        },
        tenant={},
        allocation_p95_ms=500,
        cost_per_hour=0.25,
        regions=["us-east-1"],
        is_production=True,
    )


@pytest.fixture
def linux_l3_backend():
    """L3 强隔离后端"""
    return SandboxBackendCapabilities(
        backend_id="kata-linux-l3-prod",
        isolation_level=IsolationLevel.L3,
        file_system={
            FileSystemCapability.WHITELIST_BASED,
            FileSystemCapability.TMPFS_ISOLATION,
            FileSystemCapability.READONLY_ROOT,
            FileSystemCapability.NO_PRIVILEGE_ESCALATION,
        },
        network={
            NetworkCapability.DEFAULT_DENY,
            NetworkCapability.EGRESS_WHITELIST,
            NetworkCapability.DNS_CONTROL,
            NetworkCapability.PROXY_REQUIRED,
            NetworkCapability.NO_LOCALHOST,
        },
        process={
            ProcessCapability.SECCOMP,
            ProcessCapability.CAPABILITIES,
            ProcessCapability.PID_ISOLATION,
            ProcessCapability.USER_ISOLATION,
            ProcessCapability.NO_SYS_ADMIN,
        },
        resource={
            ResourceCapability.CPU_LIMIT,
            ResourceCapability.MEMORY_LIMIT,
            ResourceCapability.DISK_LIMIT,
            ResourceCapability.FORK_LIMIT,
            ResourceCapability.TIMEOUT_ENFORCE,
        },
        audit={
            AuditCapability.CONTAINER_LIFECYCLE,
            AuditCapability.POLICY_VIOLATIONS,
            AuditCapability.COMPLETE_TRACE,
        },
        tenant={TenantCapability.RESOURCE_POOL_ISOLATION},
        allocation_p95_ms=1000,
        cost_per_hour=0.50,
        regions=["us-east-1", "us-west-2", "eu-west-1"],
        is_production=True,
    )


# 测试：后端注册
def test_register_backend(router, linux_l1_backend):
    """测试后端注册"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    
    assert linux_l1_backend.backend_id in router._backends
    assert router._backends[linux_l1_backend.backend_id].capabilities == linux_l1_backend


def test_register_duplicate_backend_fails(router, linux_l1_backend):
    """测试重复注册失败"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    
    with pytest.raises(ValueError, match="already registered"):
        router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)


# 测试：简单路由
def test_route_to_capable_backend(router, linux_l1_backend, linux_l2_backend):
    """测试路由到能满足需求的后端"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    router.register_backend(linux_l2_backend.backend_id, linux_l2_backend)
    
    requirement = IsolationRequirement(
        min_isolation_level=IsolationLevel.L1,
        file_system_requirements={FileSystemCapability.TMPFS_ISOLATION},
    )
    
    decision = router.route(requirement, policy_version="policy-v1", preferred_backend_id=None)
    
    assert decision.backend_id in [linux_l1_backend.backend_id, linux_l2_backend.backend_id]
    assert decision.isolation_level_assigned >= IsolationLevel.L1


def test_route_no_capable_backend(router):
    """测试无满足需求的后端"""
    requirement = IsolationRequirement(
        min_isolation_level=IsolationLevel.L3,
    )
    
    with pytest.raises(ValueError, match="No backends satisfy"):
        router.route(requirement, policy_version="policy-v1")


# 测试：单调升级原则
def test_monotonic_upgrade_allowed(router, linux_l1_backend, linux_l2_backend):
    """测试允许升级"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    router.register_backend(linux_l2_backend.backend_id, linux_l2_backend)
    
    requirement = IsolationRequirement(min_isolation_level=IsolationLevel.L2)
    
    decision = router.route(
        requirement,
        policy_version="policy-v1",
        current_backend_id=linux_l1_backend.backend_id,
    )
    
    # 应该升级到 L2 或更高
    assert decision.isolation_level_assigned >= IsolationLevel.L2


def test_monotonic_no_downgrade(router, linux_l1_backend, linux_l2_backend):
    """测试禁止降级"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    router.register_backend(linux_l2_backend.backend_id, linux_l2_backend)
    
    # 从 L2 降级尝试：仍然需要 L2 级别的隔离，但当前后端是 L2
    # 此时不应该允许降到 L1
    requirement = IsolationRequirement(min_isolation_level=IsolationLevel.L2)
    
    # 从 L2 开始，新需求也是 L2，应该保持或升级（选 L2）
    decision = router.route(
        requirement,
        policy_version="policy-v1",
        current_backend_id=linux_l2_backend.backend_id,
    )
    
    # 应该选择 L2（维持）或更高，不能降到 L1
    assert decision.isolation_level_assigned >= IsolationLevel.L2


# 测试：成本闸门
def test_cost_filter_within_budget(router, linux_l1_backend):
    """测试在预算内的成本过滤"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    
    requirement = IsolationRequirement(
        min_isolation_level=IsolationLevel.L1,
        max_cost_per_hour=0.20,  # L1 的 0.10 在此预算内
    )
    
    decision = router.route(requirement, policy_version="policy-v1")
    assert decision.backend_id == linux_l1_backend.backend_id


def test_cost_filter_exceeds_budget(router, linux_l2_backend):
    """测试超出预算的成本过滤"""
    router.register_backend(linux_l2_backend.backend_id, linux_l2_backend)
    
    requirement = IsolationRequirement(
        min_isolation_level=IsolationLevel.L2,
        max_cost_per_hour=0.15,  # L2 的 0.25 超出此预算
    )
    
    with pytest.raises(ValueError, match="No backends available within cost limit"):
        router.route(requirement, policy_version="policy-v1")


# 测试：区域优先
def test_region_preference(router, linux_l1_backend):
    """测试区域优先"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    
    requirement = IsolationRequirement(
        min_isolation_level=IsolationLevel.L1,
        preferred_regions=["us-east-1"],
    )
    
    decision = router.route(requirement, policy_version="policy-v1")
    assert decision.backend_id == linux_l1_backend.backend_id


# 测试：健康状态检查
def test_unhealthy_backend_filtered(router, linux_l1_backend, linux_l2_backend):
    """测试不健康的后端被过滤"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    router.register_backend(linux_l2_backend.backend_id, linux_l2_backend)
    
    # 将 L1 标记为不健康
    router.update_backend_health(linux_l1_backend.backend_id, is_healthy=False)
    
    requirement = IsolationRequirement(min_isolation_level=IsolationLevel.L1)
    
    decision = router.route(requirement, policy_version="policy-v1")
    assert decision.backend_id == linux_l2_backend.backend_id  # 应该选择 L2


# 测试：容量检查
def test_backend_at_capacity_filtered(router, linux_l1_backend):
    """测试容量满的后端被过滤"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    
    # 设置容量为 0
    router.update_backend_health(
        linux_l1_backend.backend_id,
        is_healthy=True,
        current_capacity=0,
    )
    
    requirement = IsolationRequirement(min_isolation_level=IsolationLevel.L1)
    
    with pytest.raises(ValueError, match="No backends satisfy"):
        router.route(requirement, policy_version="policy-v1")


# 测试：能力检查
def test_network_capability_requirement(router, linux_l1_backend, linux_l2_backend):
    """测试网络能力需求检查"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    router.register_backend(linux_l2_backend.backend_id, linux_l2_backend)
    
    # 需要 DNS 控制（L1 不支持，L2 支持）
    requirement = IsolationRequirement(
        min_isolation_level=IsolationLevel.L1,
        network_requirements={NetworkCapability.DNS_CONTROL},
    )
    
    decision = router.route(requirement, policy_version="policy-v1")
    assert decision.backend_id == linux_l2_backend.backend_id


# 测试：路由决策记录
def test_routing_history_recorded(router, linux_l1_backend):
    """测试路由决策被记录"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    
    requirement = IsolationRequirement(min_isolation_level=IsolationLevel.L1)
    
    decision1 = router.route(requirement, policy_version="policy-v1")
    decision2 = router.route(requirement, policy_version="policy-v1")
    
    history = router.get_routing_history(limit=10)
    assert len(history) >= 2
    assert history[-1].backend_id == decision2.backend_id


# 测试：后端统计
def test_backend_stats(router, linux_l1_backend, linux_l2_backend):
    """测试后端统计信息"""
    router.register_backend(linux_l1_backend.backend_id, linux_l1_backend)
    router.register_backend(linux_l2_backend.backend_id, linux_l2_backend)
    
    stats = router.get_backend_stats()
    
    assert stats["total_backends"] == 2
    assert stats["healthy_backends"] == 2
    assert linux_l1_backend.backend_id in stats["backends"]
    assert stats["backends"][linux_l1_backend.backend_id]["allocation_p95_ms"] == 300
