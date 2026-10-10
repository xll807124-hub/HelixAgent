"""
沙箱路由器 - REQ-SEC-004 多维路由

核心职责：
1. 接收隔离需求，计算最低所需能力
2. 根据多维矩阵路由到合适的后端
3. 执行单调升级原则（不允许降级）
4. 记录路由决策用于审计
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .contracts import (
    AuditCapability,
    FileSystemCapability,
    IsolationLevel,
    IsolationRequirement,
    NetworkCapability,
    ProcessCapability,
    ResourceCapability,
    RoutingDecision,
    SandboxBackendCapabilities,
    SandboxBackendRegistry,
)

logger = logging.getLogger(__name__)


class SandboxRouter:
    """
    沙箱路由器 - 多维路由与后端选择
    
    职责：
    1. 维护后端注册表和能力声明
    2. 根据隔离需求进行多维路由
    3. 执行成本闸门和容量检查
    4. 记录路由决策审计
    """

    def __init__(self):
        """初始化路由器"""
        self._backends: dict[str, SandboxBackendRegistry] = {}
        self._routing_history: list[RoutingDecision] = []
        self._multi_dimensional_matrix: dict[str, IsolationLevel] = {}

    def register_backend(
        self,
        backend_id: str,
        capabilities: SandboxBackendCapabilities,
    ) -> None:
        """
        注册沙箱后端
        
        Args:
            backend_id: 后端标识
            capabilities: 能力声明
            
        Raises:
            ValueError: 如果后端已注册或配置无效
        """
        if backend_id in self._backends:
            raise ValueError(f"Backend {backend_id} already registered")
        
        if not capabilities.is_production and capabilities.uptime_slo < 0.95:
            logger.warning(
                f"Backend {backend_id} has low SLO {capabilities.uptime_slo} and is not production"
            )
        
        registry = SandboxBackendRegistry(
            backend_id=backend_id,
            capabilities=capabilities,
            current_capacity=capabilities.max_concurrent_instances,
        )
        self._backends[backend_id] = registry
        logger.info(f"Backend registered: {backend_id} (isolation={capabilities.isolation_level})")

    def unregister_backend(self, backend_id: str) -> None:
        """取消注册后端"""
        if backend_id in self._backends:
            del self._backends[backend_id]
            logger.info(f"Backend unregistered: {backend_id}")

    def update_backend_health(
        self,
        backend_id: str,
        is_healthy: bool,
        current_capacity: Optional[int] = None,
    ) -> None:
        """更新后端健康状态"""
        if backend_id not in self._backends:
            logger.warning(f"Backend {backend_id} not found")
            return
        
        backend = self._backends[backend_id]
        backend.is_healthy = is_healthy
        backend.last_health_check = datetime.utcnow()
        if current_capacity is not None:
            backend.current_capacity = current_capacity
        
        logger.debug(f"Backend health updated: {backend_id} (healthy={is_healthy})")

    def route(
        self,
        requirement: IsolationRequirement,
        policy_version: str,
        preferred_backend_id: Optional[str] = None,
        current_backend_id: Optional[str] = None,
    ) -> RoutingDecision:
        """
        路由到合适的后端
        
        Args:
            requirement: 隔离需求
            policy_version: 应用的策略版本
            preferred_backend_id: 优先后端（仅用作提示，不强制）
            current_backend_id: 当前后端（用于检查单调性）
            
        Returns:
            RoutingDecision: 路由决策
            
        Raises:
            ValueError: 如果无可用后端或无法满足需求
        """
        # 第一步：过滤符合最低隔离能力的后端
        capable_backends = self._filter_capable_backends(requirement)
        
        if not capable_backends:
            raise ValueError(
                f"No backends satisfy isolation requirement: {requirement.min_isolation_level}"
            )
        
        # 第二步：检查单调性（禁止降级）
        if current_backend_id:
            # 检查当前后端是否满足新需求
            if current_backend_id not in self._backends:
                raise ValueError(f"Current backend {current_backend_id} not found")
            
            current_level = self._backends[current_backend_id].capabilities.isolation_level
            
            # 检查当前后端的隔离级别是否足以满足新需求
            if not self._backends[current_backend_id].capabilities.supports_isolation_level(
                requirement.min_isolation_level
            ):
                # 需要升级，查找满足的更好后端
                candidates = self._check_monotonicity(capable_backends, current_backend_id)
            else:
                # 当前后端可以满足新需求
                candidates = capable_backends
        else:
            candidates = capable_backends
        
        if not candidates:
            raise ValueError(
                f"Cannot find backend to upgrade from {current_backend_id}; no suitable backend available"
            )
        
        # 第三步：应用成本闸门
        cost_filtered = self._apply_cost_filter(
            candidates,
            requirement.max_cost_per_hour,
        )
        
        if not cost_filtered:
            raise ValueError(
                f"No backends available within cost limit: {requirement.max_cost_per_hour}"
            )
        
        # 第四步：优化选择（可用性、延迟、区域）
        selected_backend_id = self._select_optimal_backend(
            cost_filtered,
            requirement.preferred_regions,
            preferred_backend_id,
        )
        
        backend_registry = self._backends[selected_backend_id]
        
        # 第五步：生成决策
        decision = RoutingDecision(
            backend_id=selected_backend_id,
            isolation_level_assigned=backend_registry.capabilities.isolation_level,
            reason=self._generate_decision_reason(
                requirement,
                selected_backend_id,
                len(candidates),
            ),
            alternatives=[b for b in candidates if b != selected_backend_id][:3],
            estimated_latency_ms=backend_registry.capabilities.allocation_p95_ms,
            estimated_cost=backend_registry.capabilities.cost_per_hour,
            policy_version=policy_version,
        )
        
        self._routing_history.append(decision)
        logger.info(f"Routing decision: {selected_backend_id} (reason: {decision.reason})")
        
        return decision

    def _filter_capable_backends(
        self,
        requirement: IsolationRequirement,
    ) -> list[str]:
        """过滤能满足隔离需求的后端"""
        capable = []
        
        for backend_id, registry in self._backends.items():
            if not registry.is_healthy:
                continue
            
            if not registry.capabilities.supports_all_requirements(
                requirement.min_isolation_level,
                requirement.file_system_requirements,
                requirement.network_requirements,
                requirement.process_requirements,
                requirement.resource_requirements,
            ):
                continue
            
            # 检查区域
            if (
                requirement.preferred_regions
                and not any(r in registry.capabilities.regions for r in requirement.preferred_regions)
            ):
                continue
            
            # 检查容量
            if registry.current_capacity <= 0:
                logger.warning(f"Backend {backend_id} at capacity")
                continue
            
            capable.append(backend_id)
        
        return capable

    def _check_monotonicity(
        self,
        candidates: list[str],
        current_backend_id: str,
    ) -> list[str]:
        """
        检查单调升级原则
        
        返回可升级（或相同）的后端列表
        """
        if current_backend_id not in self._backends:
            return candidates
        
        current_level = self._backends[current_backend_id].capabilities.isolation_level
        
        level_ordering = {
            IsolationLevel.L1: 1,
            IsolationLevel.L2: 2,
            IsolationLevel.L3: 3,
        }
        
        current_rank = level_ordering.get(current_level, 0)
        
        # 只允许升级（等级增加）或维持
        valid_candidates = [
            backend_id
            for backend_id in candidates
            if level_ordering.get(
                self._backends[backend_id].capabilities.isolation_level,
                0,
            ) >= current_rank
        ]
        
        return valid_candidates

    def _apply_cost_filter(
        self,
        candidates: list[str],
        max_cost_per_hour: Optional[float],
    ) -> list[str]:
        """应用成本闸门"""
        if max_cost_per_hour is None:
            return candidates
        
        filtered = [
            backend_id
            for backend_id in candidates
            if self._backends[backend_id].capabilities.cost_per_hour <= max_cost_per_hour
        ]
        
        return filtered  # 如果都超出预算，返回空列表让上层处理

    def _select_optimal_backend(
        self,
        candidates: list[str],
        preferred_regions: list[str],
        preferred_backend_id: Optional[str],
    ) -> str:
        """
        从候选后端中选择最优的
        
        优先级：
        1. 优先后端（如果可用）
        2. 区域匹配
        3. 最低成本
        4. 最低延迟
        5. 最高可用性
        """
        # 优先后端优先
        if preferred_backend_id and preferred_backend_id in candidates:
            return preferred_backend_id
        
        # 区域过滤
        region_matched = [
            b for b in candidates
            if any(r in self._backends[b].capabilities.regions for r in preferred_regions)
        ] if preferred_regions else candidates
        
        candidates = region_matched or candidates
        
        # 按成本排序
        candidates_by_cost = sorted(
            candidates,
            key=lambda b: self._backends[b].capabilities.cost_per_hour,
        )
        
        # 按延迟排序（在相似成本下）
        low_cost_tier = candidates_by_cost[:max(1, len(candidates_by_cost) // 3)]
        best_latency = min(
            low_cost_tier,
            key=lambda b: self._backends[b].capabilities.allocation_p95_ms,
        )
        
        return best_latency

    def _generate_decision_reason(
        self,
        requirement: IsolationRequirement,
        selected_backend_id: str,
        num_candidates: int,
    ) -> str:
        """生成决策理由"""
        backend = self._backends[selected_backend_id].capabilities
        
        reasons = [
            f"Selected {selected_backend_id} from {num_candidates} qualified backends",
            f"Isolation: {requirement.min_isolation_level} → {backend.isolation_level}",
        ]
        
        if requirement.file_system_requirements:
            reasons.append(f"FS: {', '.join(r.value for r in requirement.file_system_requirements)}")
        
        if requirement.network_requirements:
            reasons.append(f"Net: {', '.join(r.value for r in requirement.network_requirements)}")
        
        return " | ".join(reasons)

    def get_routing_history(self, limit: int = 100) -> list[RoutingDecision]:
        """获取路由决策历史"""
        return self._routing_history[-limit:]

    def get_backend_stats(self) -> dict:
        """获取后端统计信息"""
        stats = {
            "total_backends": len(self._backends),
            "healthy_backends": sum(1 for r in self._backends.values() if r.is_healthy),
            "backends": {},
        }
        
        for backend_id, registry in self._backends.items():
            stats["backends"][backend_id] = {
                "isolation_level": registry.capabilities.isolation_level.value,
                "is_healthy": registry.is_healthy,
                "current_capacity": registry.current_capacity,
                "max_capacity": registry.capabilities.max_concurrent_instances,
                "allocation_p95_ms": registry.capabilities.allocation_p95_ms,
                "cost_per_hour": registry.capabilities.cost_per_hour,
            }
        
        return stats
