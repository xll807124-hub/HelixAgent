"""
RT-007 Idempotency Key 与副作用边界 — 幂等性模块

本模块实现幂等键生成、管理、原子领取和状态账本，确保同一逻辑操作不重复产生外部副作用。

设计契约：REQ-RT-007 (v0.1-frozen)

核心组件：
- models: 幂等键数据模型和状态枚举
- types: 枚举和类型定义
- generator: 幂等键生成器（step_scope）
- digest: 请求摘要计算器
- manager: 幂等键管理器（原子领取、状态管理、冲突检测）
- storage: 存储抽象层（MVP 用内存实现）
- reconciler: 对账协调器（结果未知时的重试逻辑）
- escalation: 升级策略（人工介入）

MVP 限制：
- 存储层使用内存实现（PostgreSQL 集成留待后续）
- 暂不实现 Redis 24小时热缓存（性能优化留待后续）
- 暂不集成到 Action 执行流程（独立模块先行）
"""

from .digest import RequestDigestCalculator
from .escalation import EscalationReason, IdempotencyEscalationHandler
from .generator import IdempotencyKeyGenerator
from .manager import IdempotencyManager
from .models import IdempotencyKey, IdempotencyResult, LeaseAcquisition, ReconciliationAttempt
from .reconciler import IdempotencyReconciler, ReconciliationOutcome
from .storage import IdempotencyStorage, InMemoryIdempotencyStorage
from .types import IdempotencyScope, IdempotencyStatus

__all__ = [
    # 类型
    "IdempotencyScope",
    "IdempotencyStatus",
    # 模型
    "IdempotencyKey",
    "IdempotencyResult",
    "LeaseAcquisition",
    "ReconciliationAttempt",
    # 生成器
    "IdempotencyKeyGenerator",
    "RequestDigestCalculator",
    # 存储
    "IdempotencyStorage",
    "InMemoryIdempotencyStorage",
    # 管理器
    "IdempotencyManager",
    # 对账器
    "IdempotencyReconciler",
    "ReconciliationOutcome",
    # 升级处理器
    "IdempotencyEscalationHandler",
    "EscalationReason",
]
