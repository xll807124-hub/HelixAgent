"""
Event Store - 事件存储接口

定义事件存储的抽象接口，支持：
- 追加式写入（append-only）
- 单调递增序列
- 幂等性保证
- 查询和流式读取

实现类：
- PostgreSQLEventStore: PostgreSQL实现（MVP）
- InMemoryEventStore: 内存实现（测试用）

设计依据：REQ-RT-003 Event Schema与版本策略
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from .envelope import EventEnvelope

# 类型别名
EventId = str
TaskId = str


class AppendStatus(str, Enum):
    """追加状态"""
    SUCCESS = "SUCCESS"  # 成功追加
    DUPLICATE = "DUPLICATE"  # 重复事件（event_id已存在）
    CONFLICT = "CONFLICT"  # 幂等键冲突（内容不同）


@dataclass
class AppendResult:
    """追加结果"""
    status: AppendStatus
    event_id: EventId
    sequence: int
    recorded_at: datetime
    conflict_event_id: EventId | None = None  # 冲突的事件ID
    error_message: str | None = None


class EventStoreError(Exception):
    """事件存储基础异常"""
    pass


class DuplicateEventError(EventStoreError):
    """重复事件错误"""
    def __init__(self, event_id: EventId, existing_sequence: int):
        self.event_id = event_id
        self.existing_sequence = existing_sequence
        super().__init__(
            f"Event {event_id} already exists at sequence {existing_sequence}"
        )


class IdempotencyConflictError(EventStoreError):
    """幂等键冲突错误"""
    def __init__(
        self,
        idempotency_key: str,
        existing_event_id: EventId,
        new_content_hash: str,
        existing_content_hash: str,
    ):
        self.idempotency_key = idempotency_key
        self.existing_event_id = existing_event_id
        self.new_content_hash = new_content_hash
        self.existing_content_hash = existing_content_hash
        super().__init__(
            f"Idempotency key '{idempotency_key}' conflict: "
            f"existing event {existing_event_id} has different content "
            f"(hash {existing_content_hash[:8]} != {new_content_hash[:8]})"
        )


class SequenceConflictError(EventStoreError):
    """序列冲突错误"""
    def __init__(self, task_id: TaskId, expected: int, actual: int):
        self.task_id = task_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Sequence conflict for task {task_id}: "
            f"expected {expected}, got {actual}"
        )


class EventStore(ABC):
    """
    事件存储抽象接口
    
    核心职责：
    1. 追加式写入事件（不可修改、不可删除）
    2. 分配单调递增序列号
    3. 检测重复和幂等键冲突
    4. 支持按task_id查询事件流
    
    不变量：
    - 同一event_id只能存在一次
    - 同一task_id内sequence单调递增
    - 同一idempotency_key不能有不同内容
    - 事件一旦写入不可修改
    """

    @abstractmethod
    async def append(self, event: EventEnvelope) -> AppendResult:
        """
        追加事件到存储
        
        Args:
            event: 事件信封
            
        Returns:
            追加结果
            
        Raises:
            DuplicateEventError: event_id已存在
            IdempotencyConflictError: 幂等键冲突
            EventStoreError: 其他存储错误
        """
        pass

    @abstractmethod
    async def get_by_id(self, event_id: EventId) -> EventEnvelope | None:
        """
        根据event_id获取事件
        
        Args:
            event_id: 事件ID
            
        Returns:
            事件信封，不存在返回None
        """
        pass

    @abstractmethod
    async def query(
        self,
        task_id: TaskId,
        from_sequence: int = 0,
        to_sequence: int | None = None,
        event_types: list[str] | None = None,
        limit: int = 1000,
    ) -> list[EventEnvelope]:
        """
        查询事件流
        
        Args:
            task_id: 任务ID
            from_sequence: 起始序列（含）
            to_sequence: 结束序列（含），None表示最新
            event_types: 事件类型过滤，None表示全部
            limit: 最大返回数量
            
        Returns:
            事件列表（按sequence升序）
        """
        pass

    @abstractmethod
    async def get_latest_sequence(self, task_id: TaskId) -> int:
        """
        获取任务的最新序列号
        
        Args:
            task_id: 任务ID
            
        Returns:
            最新序列号，无事件返回0
        """
        pass

    @abstractmethod
    async def count(
        self,
        task_id: TaskId | None = None,
        event_types: list[str] | None = None,
    ) -> int:
        """
        统计事件数量
        
        Args:
            task_id: 任务ID过滤，None表示全部
            event_types: 事件类型过滤，None表示全部
            
        Returns:
            事件数量
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        健康检查
        
        Returns:
            True表示存储可用
        """
        pass


class InMemoryEventStore(EventStore):
    """
    内存事件存储（测试用）
    
    警告：仅用于测试，不支持持久化
    """

    def __init__(self) -> None:
        self._events: dict[EventId, EventEnvelope] = {}
        self._task_sequences: dict[TaskId, list[EventEnvelope]] = {}
        self._idempotency_keys: dict[str, EventId] = {}
        self._next_sequence: dict[TaskId, int] = {}

    async def append(self, event: EventEnvelope) -> AppendResult:
        """追加事件"""
        # 检查重复event_id
        if event.event_id in self._events:
            existing = self._events[event.event_id]
            return AppendResult(
                status=AppendStatus.DUPLICATE,
                event_id=event.event_id,
                sequence=existing.sequence,
                recorded_at=existing.recorded_at or event.occurred_at,
            )

        # 检查幂等键冲突
        if event.idempotency_key:
            if event.idempotency_key in self._idempotency_keys:
                existing_id = self._idempotency_keys[event.idempotency_key]
                existing = self._events[existing_id]
                
                new_hash = event.compute_content_hash()
                existing_hash = existing.compute_content_hash()
                
                if new_hash != existing_hash:
                    return AppendResult(
                        status=AppendStatus.CONFLICT,
                        event_id=event.event_id,
                        sequence=0,
                        recorded_at=datetime.now(UTC),
                        conflict_event_id=existing_id,
                        error_message="Idempotency key conflict with different content",
                    )
                
                # 内容相同，返回已存在的事件
                return AppendResult(
                    status=AppendStatus.DUPLICATE,
                    event_id=existing_id,
                    sequence=existing.sequence,
                    recorded_at=existing.recorded_at or existing.occurred_at,
                )

        # 分配序列号
        if event.task_id not in self._next_sequence:
            self._next_sequence[event.task_id] = 1
        
        sequence = self._next_sequence[event.task_id]
        self._next_sequence[event.task_id] += 1

        # 更新事件
        recorded_at = datetime.now(UTC)
        event.sequence = sequence
        event.recorded_at = recorded_at

        # 保存
        self._events[event.event_id] = event
        
        if event.task_id not in self._task_sequences:
            self._task_sequences[event.task_id] = []
        self._task_sequences[event.task_id].append(event)
        
        if event.idempotency_key:
            self._idempotency_keys[event.idempotency_key] = event.event_id

        return AppendResult(
            status=AppendStatus.SUCCESS,
            event_id=event.event_id,
            sequence=sequence,
            recorded_at=recorded_at,
        )

    async def get_by_id(self, event_id: EventId) -> EventEnvelope | None:
        """根据ID获取事件"""
        return self._events.get(event_id)

    async def query(
        self,
        task_id: TaskId,
        from_sequence: int = 0,
        to_sequence: int | None = None,
        event_types: list[str] | None = None,
        limit: int = 1000,
    ) -> list[EventEnvelope]:
        """查询事件流"""
        events = self._task_sequences.get(task_id, [])
        
        # 过滤序列范围
        filtered = [
            e for e in events
            if e.sequence >= from_sequence
            and (to_sequence is None or e.sequence <= to_sequence)
        ]
        
        # 过滤事件类型
        if event_types:
            filtered = [e for e in filtered if e.event_type in event_types]
        
        # 排序并限制数量
        filtered.sort(key=lambda e: e.sequence)
        return filtered[:limit]

    async def get_latest_sequence(self, task_id: TaskId) -> int:
        """获取最新序列号"""
        return self._next_sequence.get(task_id, 0)

    async def count(
        self,
        task_id: TaskId | None = None,
        event_types: list[str] | None = None,
    ) -> int:
        """统计事件数量"""
        if task_id:
            events = self._task_sequences.get(task_id, [])
        else:
            events = list(self._events.values())
        
        if event_types:
            events = [e for e in events if e.event_type in event_types]
        
        return len(events)

    async def health_check(self) -> bool:
        """健康检查"""
        return True
