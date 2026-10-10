"""
沙箱后端能力契约 - REQ-SEC-004

定义沙箱后端必须实现的统一接口契约，支持多后端抽象和路由。

核心设计原则：
1. 统一的概念能力契约，支持多种底层实现（Docker/gVisor/Kata/Firecracker）
2. 后端声明其能力、限制、版本，不能声称不具备的能力
3. 路由决策基于多维隔离需求（风险/数据分类/来源信任/租户/成本）
4. 隔离要求只可维持或升级，禁止向下降级
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class IsolationLevel(str, Enum):
    """隔离级别（Level 1-3 递进强度）"""
    L1 = "L1"  # 基础隔离：文件系统工作目录隔离、网络代理、资源限制
    L2 = "L2"  # 增强隔离：系统调用限制（Seccomp）、进程隔离、Capabilities 细粒度控制
    L3 = "L3"  # 强隔离：虚拟机级别（微VM）、完全的硬件隔离、多租户安全保证


class FileSystemCapability(str, Enum):
    """文件系统能力"""
    WHITELIST_BASED = "whitelist_based"     # 基于路径白名单
    READONLY_ROOT = "readonly_root"         # 根文件系统只读
    TMPFS_ISOLATION = "tmpfs_isolation"     # 工作目录 tmpfs 隔离
    VOLUME_MOUNT = "volume_mount"           # 支持卷挂载
    NO_PRIVILEGE_ESCALATION = "no_priv_esc" # 无权限提升


class NetworkCapability(str, Enum):
    """网络能力"""
    DEFAULT_DENY = "default_deny"           # 默认拒绝
    EGRESS_WHITELIST = "egress_whitelist"   # 出站白名单（基于连接器声明）
    DNS_CONTROL = "dns_control"             # DNS 防重绑定、CNAME 链检查
    PROXY_REQUIRED = "proxy_required"       # 必须通过代理
    NO_LOCALHOST = "no_localhost"           # 禁止 localhost 回环


class ProcessCapability(str, Enum):
    """进程隔离能力"""
    SECCOMP = "seccomp"                     # 系统调用过滤
    CAPABILITIES = "capabilities"           # Linux Capabilities 限制
    PID_ISOLATION = "pid_isolation"         # PID 命名空间隔离
    USER_ISOLATION = "user_isolation"       # UID 命名空间隔离
    NO_SYS_ADMIN = "no_sys_admin"          # 禁止 CAP_SYS_ADMIN


class ResourceCapability(str, Enum):
    """资源隔离能力"""
    CPU_LIMIT = "cpu_limit"                 # CPU 限制
    MEMORY_LIMIT = "memory_limit"           # 内存限制
    DISK_LIMIT = "disk_limit"               # 磁盘配额
    FORK_LIMIT = "fork_limit"               # 进程数限制
    TIMEOUT_ENFORCE = "timeout_enforce"     # 执行超时强制


class AuditCapability(str, Enum):
    """审计能力"""
    CONTAINER_LIFECYCLE = "container_lifecycle"  # 容器生命周期事件
    NETWORK_EVENTS = "network_events"           # 网络事件
    FILE_ACCESS = "file_access"                 # 文件访问审计
    POLICY_VIOLATIONS = "policy_violations"     # 策略违规事件
    COMPLETE_TRACE = "complete_trace"           # 完整追踪链


class TenantCapability(str, Enum):
    """多租户隔离能力"""
    RESOURCE_POOL_ISOLATION = "resource_pool_isolation"  # 租户级资源池
    METADATA_ISOLATION = "metadata_isolation"             # 元数据隔离
    CROSS_TENANT_PREVENTION = "cross_tenant_prevention"   # 租户间隔离


class SnapshotCapability(str, Enum):
    """快照/恢复能力"""
    STATE_SNAPSHOT = "state_snapshot"       # 状态快照
    INCREMENTAL_SNAPSHOT = "incremental_snapshot"  # 增量快照
    RESTORE = "restore"                    # 恢复能力
    # 注意：快照/恢复不能用作隔离证明，恢复前需重新验证策略


@dataclass
class SandboxBackendCapabilities:
    """后端能力声明"""
    backend_id: str                         # 后端标识（如 "docker-linux-prod"）
    isolation_level: IsolationLevel         # 隔离级别
    
    # 各维度能力集合
    file_system: set[FileSystemCapability]  # 文件系统能力
    network: set[NetworkCapability]         # 网络能力
    process: set[ProcessCapability]         # 进程隔离能力
    resource: set[ResourceCapability]       # 资源隔离能力
    audit: set[AuditCapability]             # 审计能力
    tenant: set[TenantCapability]           # 多租户能力
    snapshot: set[SnapshotCapability] = field(default_factory=set)  # 快照能力
    
    # 性能指标
    warmpool_available: bool = True         # 是否支持 WarmPool
    cold_start_latency_ms: int = 5000       # 冷启动延迟（毫秒）
    allocation_p95_ms: int = 200            # 分配延迟 p95
    
    # 版本与可用性
    version: str = "1.0.0"                  # 后端版本
    regions: list[str] = field(default_factory=list)  # 可用区域
    max_concurrent_instances: int = 1000    # 最大并发实例
    
    # 成本
    cost_per_hour: float = 0.0              # 小时成本
    cost_per_gb_memory: float = 0.0         # GB 内存成本
    
    # 限制
    max_memory_gb: int = 32                 # 最大内存
    max_cpu_cores: int = 16                 # 最大 CPU 核心
    max_execution_time_seconds: int = 3600  # 最大执行时间
    
    # 可靠性与保证
    uptime_slo: float = 0.999               # 99.9% SLO
    is_production: bool = False             # 是否生产环境
    
    known_limitations: list[str] = field(default_factory=list)  # 已知限制

    def supports_isolation_level(self, required: IsolationLevel) -> bool:
        """检查是否支持所需隔离级别"""
        level_ordering = {
            IsolationLevel.L1: 1,
            IsolationLevel.L2: 2,
            IsolationLevel.L3: 3,
        }
        return level_ordering.get(self.isolation_level, 0) >= level_ordering.get(required, 0)

    def supports_file_system_requirements(self, requirements: set[FileSystemCapability]) -> bool:
        """检查是否满足文件系统需求"""
        return requirements.issubset(self.file_system)

    def supports_network_requirements(self, requirements: set[NetworkCapability]) -> bool:
        """检查是否满足网络需求"""
        return requirements.issubset(self.network)

    def supports_all_requirements(
        self,
        isolation_level: IsolationLevel,
        filesystem: set[FileSystemCapability],
        network: set[NetworkCapability],
        process: set[ProcessCapability],
        resource: set[ResourceCapability],
    ) -> bool:
        """检查是否满足所有隔离需求"""
        return (
            self.supports_isolation_level(isolation_level)
            and self.supports_file_system_requirements(filesystem)
            and self.supports_network_requirements(network)
            and process.issubset(self.process)
            and resource.issubset(self.resource)
        )


class IsolationRequirement(BaseModel):
    """隔离需求（路由输入）"""
    min_isolation_level: IsolationLevel = Field(
        default=IsolationLevel.L1,
        description="最低隔离级别"
    )
    
    file_system_requirements: set[FileSystemCapability] = Field(
        default_factory=set,
        description="文件系统隔离需求"
    )
    
    network_requirements: set[NetworkCapability] = Field(
        default_factory=set,
        description="网络隔离需求"
    )
    
    process_requirements: set[ProcessCapability] = Field(
        default_factory=set,
        description="进程隔离需求"
    )
    
    resource_requirements: set[ResourceCapability] = Field(
        default_factory=set,
        description="资源隔离需求"
    )
    
    audit_requirements: set[AuditCapability] = Field(
        default_factory=set,
        description="审计需求"
    )
    
    tenant_isolation_required: bool = Field(
        default=False,
        description="是否需要多租户隔离"
    )
    
    max_cost_per_hour: Optional[float] = Field(
        default=None,
        description="最大小时成本（可选）"
    )
    
    preferred_regions: list[str] = Field(
        default_factory=list,
        description="优先区域"
    )


class SandboxBackendRegistry(BaseModel):
    """沙箱后端注册表"""
    backend_id: str = Field(..., description="后端唯一标识")
    capabilities: SandboxBackendCapabilities = Field(..., description="能力声明")
    registered_at: datetime = Field(default_factory=datetime.utcnow, description="注册时间")
    last_health_check: Optional[datetime] = Field(default=None, description="最后健康检查")
    is_healthy: bool = Field(default=True, description="是否健康")
    current_capacity: int = Field(default=0, description="当前可用容量")


class RoutingDecision(BaseModel):
    """路由决策结果"""
    backend_id: str = Field(..., description="选择的后端")
    isolation_level_assigned: IsolationLevel = Field(..., description="分配的隔离级别")
    reason: str = Field(..., description="选择原因")
    alternatives: list[str] = Field(default_factory=list, description="备选后端列表")
    estimated_latency_ms: int = Field(..., description="预估延迟")
    estimated_cost: float = Field(..., description="预估成本")
    
    # 审计追踪
    decision_timestamp: datetime = Field(default_factory=datetime.utcnow)
    decision_version: str = Field(default="1.0.0", description="决策版本")
    policy_version: str = Field(..., description="应用的策略版本")


class SandboxExecutionContext(BaseModel):
    """沙箱执行上下文"""
    execution_id: str = Field(..., description="执行唯一标识")
    task_id: str = Field(..., description="关联任务")
    worker_id: str = Field(..., description="关联 Worker")
    
    backend_id: str = Field(..., description="使用的后端")
    isolation_level: IsolationLevel = Field(..., description="隔离级别")
    
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = Field(default=None)
    
    # 资源使用
    memory_limit_mb: int = Field(default=4096)
    cpu_limit_cores: float = Field(default=2.0)
    disk_limit_gb: int = Field(default=50)
    
    # 网络与连接器
    connector_version: str = Field(..., description="使用的连接器版本（已审批）")
    allowed_outbound_destinations: list[str] = Field(default_factory=list)
    
    # 租户信息
    tenant_id: str = Field(..., description="租户 ID")
    
    # 策略版本
    policy_version: str = Field(..., description="应用的策略版本")
    
    # 审计
    audit_events: list[str] = Field(default_factory=list, description="审计事件 ID 列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "execution_id": "exec-12345",
                "task_id": "task-001",
                "worker_id": "worker-001",
                "backend_id": "docker-linux-prod",
                "isolation_level": "L2",
                "tenant_id": "org-001",
                "connector_version": "v1.2.3-approved-2026-10-09",
                "policy_version": "policy-v2.1",
            }
        }
