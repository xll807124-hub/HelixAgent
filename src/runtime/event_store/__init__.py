"""
Event Store Module - 事件存储模块

本模块提供事件事实源的核心功能：
- EventEnvelope: 统一事件信封
- EventStore: 存储抽象接口
- InMemoryEventStore: 内存实现（测试用）
- PostgreSQLEventStore: PostgreSQL实现（生产用，待实现）

核心原则：
1. 事件不可变（Append-Only）
2. 单调递增序列
3. 幂等性保证
4. 完整性验证

设计依据：REQ-RT-003 Event Schema与版本策略
"""

from .envelope import (
    CausationRef,
    CausationType,
    ContentRef,
    DataSensitivity,
    EventCategory,
    EventEnvelope,
    ProducerRef,
)
from .store import (
    AppendResult,
    AppendStatus,
    DuplicateEventError,
    EventStore,
    EventStoreError,
    IdempotencyConflictError,
    InMemoryEventStore,
    SequenceConflictError,
)

__all__ = [
    # Envelope
    "EventEnvelope",
    "EventCategory",
    "CausationType",
    "CausationRef",
    "ProducerRef",
    "ContentRef",
    "DataSensitivity",
    # Store
    "EventStore",
    "InMemoryEventStore",
    "AppendResult",
    "AppendStatus",
    # Exceptions
    "EventStoreError",
    "DuplicateEventError",
    "IdempotencyConflictError",
    "SequenceConflictError",
]
