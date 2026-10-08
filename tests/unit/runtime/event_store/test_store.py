"""
Event Store 单元测试

测试覆盖：
- 追加新事件
- 重复event_id检测
- 幂等键冲突检测
- 序列号生成
- 查询过滤和分页
- 并发追加安全性
"""

import pytest
from datetime import datetime, timezone

from src.runtime.common.types import generate_entity_id, ensure_utc
from src.runtime.event_store import (
    EventEnvelope,
    EventCategory,
    InMemoryEventStore,
    AppendStatus,
)


class TestInMemoryEventStore:
    """InMemoryEventStore 功能测试"""

    @pytest.fixture
    def store(self):
        """创建存储实例"""
        return InMemoryEventStore()

    @pytest.fixture
    def sample_event(self):
        """创建示例事件"""
        return EventEnvelope(
            event_type="TaskCreated",
            payload_schema="TaskCreated.v1",
            payload={"name": "test-task"},
            task_id="task-123",
        )

    @pytest.mark.asyncio
    async def test_smoke_append_new_event(self, store, sample_event):
        """冒烟：追加新事件成功"""
        result = await store.append(sample_event)
        
        assert result.status == AppendStatus.SUCCESS
        assert result.event_id == sample_event.event_id
        assert result.sequence == 1  # 第一个事件
        assert result.recorded_at is not None

    @pytest.mark.asyncio
    async def test_smoke_get_by_id_returns_event(self, store, sample_event):
        """冒烟：根据ID获取事件"""
        await store.append(sample_event)
        
        retrieved = await store.get_by_id(sample_event.event_id)
        
        assert retrieved is not None
        assert retrieved.event_id == sample_event.event_id
        assert retrieved.event_type == sample_event.event_type

    @pytest.mark.asyncio
    async def test_smoke_get_by_id_returns_none_for_missing(self, store):
        """冒烟：不存在的事件返回None"""
        result = await store.get_by_id("non-existent-id")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_boundary_duplicate_event_id_returns_duplicate(self, store, sample_event):
        """边界：重复event_id返回DUPLICATE"""
        # 第一次追加
        result1 = await store.append(sample_event)
        assert result1.status == AppendStatus.SUCCESS
        
        # 第二次追加相同事件
        result2 = await store.append(sample_event)
        assert result2.status == AppendStatus.DUPLICATE
        assert result2.event_id == sample_event.event_id
        assert result2.sequence == result1.sequence  # 返回原序列

    @pytest.mark.asyncio
    async def test_boundary_sequence_increments_per_task(self, store):
        """边界：序列号按task_id递增"""
        task_id = "task-123"
        
        event1 = EventEnvelope(
            event_type="Event1",
            payload_schema="Event.v1",
            payload={},
            task_id=task_id,
        )
        event2 = EventEnvelope(
            event_type="Event2",
            payload_schema="Event.v1",
            payload={},
            task_id=task_id,
        )
        
        result1 = await store.append(event1)
        result2 = await store.append(event2)
        
        assert result1.sequence == 1
        assert result2.sequence == 2

    @pytest.mark.asyncio
    async def test_boundary_sequences_independent_per_task(self, store):
        """边界：不同task的序列号独立"""
        event1 = EventEnvelope(
            event_type="Event1",
            payload_schema="Event.v1",
            payload={},
            task_id="task-a",
        )
        event2 = EventEnvelope(
            event_type="Event2",
            payload_schema="Event.v1",
            payload={},
            task_id="task-b",
        )
        
        result1 = await store.append(event1)
        result2 = await store.append(event2)
        
        # 两个task都从1开始
        assert result1.sequence == 1
        assert result2.sequence == 1

    @pytest.mark.asyncio
    async def test_boundary_idempotency_key_same_content_returns_duplicate(self, store):
        """边界：相同幂等键+相同内容返回DUPLICATE"""
        # 注意：哈希基于 event_id, event_type, event_type_version, task_id, occurred_at, payload
        # 所以要让两个事件内容"相同"，这些字段都必须相同
        occurred_at = ensure_utc(datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc))
        
        event1 = EventEnvelope(
            event_id="event-1",
            event_type="TestEvent",
            event_type_version="v1",
            payload_schema="Test.v1",
            payload={"key": "value"},
            task_id="task-123",
            idempotency_key="idem-123",
            occurred_at=occurred_at,
        )
        event2 = EventEnvelope(
            event_id="event-1",  # 相同event_id（幂等键保护的是业务操作，不是event_id）
            event_type="TestEvent",
            event_type_version="v1",
            payload_schema="Test.v1",
            payload={"key": "value"},  # 相同内容
            task_id="task-123",
            idempotency_key="idem-123",  # 相同幂等键
            occurred_at=occurred_at,
        )
        
        result1 = await store.append(event1)
        assert result1.status == AppendStatus.SUCCESS
        
        result2 = await store.append(event2)
        assert result2.status == AppendStatus.DUPLICATE
        assert result2.event_id == event1.event_id  # 返回第一个事件的ID

    @pytest.mark.asyncio
    async def test_exception_idempotency_key_different_content_returns_conflict(self, store):
        """异常：相同幂等键+不同内容返回CONFLICT"""
        event1 = EventEnvelope(
            event_id="event-1",
            event_type="TestEvent",
            payload_schema="Test.v1",
            payload={"key": "value1"},
            task_id="task-123",
            idempotency_key="idem-123",
            occurred_at=ensure_utc(datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)),
        )
        event2 = EventEnvelope(
            event_id="event-2",
            event_type="TestEvent",
            payload_schema="Test.v1",
            payload={"key": "value2"},  # 不同内容
            task_id="task-123",
            idempotency_key="idem-123",  # 相同幂等键
            occurred_at=ensure_utc(datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)),
        )
        
        result1 = await store.append(event1)
        assert result1.status == AppendStatus.SUCCESS
        
        result2 = await store.append(event2)
        assert result2.status == AppendStatus.CONFLICT
        assert result2.conflict_event_id == event1.event_id
        assert "Idempotency key conflict" in result2.error_message

    @pytest.mark.asyncio
    async def test_query_returns_events_in_sequence_order(self, store):
        """查询：按序列号升序返回"""
        task_id = "task-123"
        
        # 追加3个事件
        for i in range(3):
            event = EventEnvelope(
                event_type=f"Event{i}",
                payload_schema="Event.v1",
                payload={"index": i},
                task_id=task_id,
            )
            await store.append(event)
        
        # 查询
        events = await store.query(task_id)
        
        assert len(events) == 3
        assert events[0].sequence == 1
        assert events[1].sequence == 2
        assert events[2].sequence == 3

    @pytest.mark.asyncio
    async def test_query_filters_by_sequence_range(self, store):
        """查询：按序列范围过滤"""
        task_id = "task-123"
        
        # 追加5个事件
        for i in range(5):
            event = EventEnvelope(
                event_type=f"Event{i}",
                payload_schema="Event.v1",
                payload={},
                task_id=task_id,
            )
            await store.append(event)
        
        # 查询序列2-4
        events = await store.query(task_id, from_sequence=2, to_sequence=4)
        
        assert len(events) == 3
        assert events[0].sequence == 2
        assert events[1].sequence == 3
        assert events[2].sequence == 4

    @pytest.mark.asyncio
    async def test_query_filters_by_event_types(self, store):
        """查询：按事件类型过滤"""
        task_id = "task-123"
        
        # 追加不同类型事件
        types = ["TypeA", "TypeB", "TypeA", "TypeC"]
        for event_type in types:
            event = EventEnvelope(
                event_type=event_type,
                payload_schema="Event.v1",
                payload={},
                task_id=task_id,
            )
            await store.append(event)
        
        # 只查询TypeA
        events = await store.query(task_id, event_types=["TypeA"])
        
        assert len(events) == 2
        assert all(e.event_type == "TypeA" for e in events)

    @pytest.mark.asyncio
    async def test_query_respects_limit(self, store):
        """查询：限制返回数量"""
        task_id = "task-123"
        
        # 追加10个事件
        for i in range(10):
            event = EventEnvelope(
                event_type="Event",
                payload_schema="Event.v1",
                payload={},
                task_id=task_id,
            )
            await store.append(event)
        
        # 限制返回5个
        events = await store.query(task_id, limit=5)
        
        assert len(events) == 5

    @pytest.mark.asyncio
    async def test_get_latest_sequence_returns_current_sequence(self, store):
        """获取最新序列号"""
        task_id = "task-123"
        
        # 初始为0
        seq = await store.get_latest_sequence(task_id)
        assert seq == 0
        
        # 追加3个事件
        for i in range(3):
            event = EventEnvelope(
                event_type="Event",
                payload_schema="Event.v1",
                payload={},
                task_id=task_id,
            )
            await store.append(event)
        
        # 最新序列应为4（下一个要分配的）
        seq = await store.get_latest_sequence(task_id)
        assert seq == 4

    @pytest.mark.asyncio
    async def test_count_all_events(self, store):
        """统计：全部事件"""
        # 追加多个task的事件
        for task_id in ["task-1", "task-2"]:
            for i in range(3):
                event = EventEnvelope(
                    event_type="Event",
                    payload_schema="Event.v1",
                    payload={},
                    task_id=task_id,
                )
                await store.append(event)
        
        count = await store.count()
        assert count == 6

    @pytest.mark.asyncio
    async def test_count_by_task_id(self, store):
        """统计：按task过滤"""
        task1_id = "task-1"
        task2_id = "task-2"
        
        # task1: 3个事件
        for i in range(3):
            event = EventEnvelope(
                event_type="Event",
                payload_schema="Event.v1",
                payload={},
                task_id=task1_id,
            )
            await store.append(event)
        
        # task2: 2个事件
        for i in range(2):
            event = EventEnvelope(
                event_type="Event",
                payload_schema="Event.v1",
                payload={},
                task_id=task2_id,
            )
            await store.append(event)
        
        count1 = await store.count(task_id=task1_id)
        count2 = await store.count(task_id=task2_id)
        
        assert count1 == 3
        assert count2 == 2

    @pytest.mark.asyncio
    async def test_count_by_event_types(self, store):
        """统计：按事件类型过滤"""
        task_id = "task-123"
        
        # 不同类型事件
        types = ["TypeA", "TypeB", "TypeA", "TypeC", "TypeA"]
        for event_type in types:
            event = EventEnvelope(
                event_type=event_type,
                payload_schema="Event.v1",
                payload={},
                task_id=task_id,
            )
            await store.append(event)
        
        count = await store.count(task_id=task_id, event_types=["TypeA"])
        assert count == 3

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self, store):
        """健康检查：返回True"""
        is_healthy = await store.health_check()
        assert is_healthy is True

    @pytest.mark.asyncio
    async def test_concurrent_append_safe(self, store):
        """并发：并发追加安全"""
        import asyncio
        
        task_id = "task-123"
        
        async def append_event(index: int):
            event = EventEnvelope(
                event_type=f"Event{index}",
                payload_schema="Event.v1",
                payload={"index": index},
                task_id=task_id,
            )
            return await store.append(event)
        
        # 并发追加10个事件
        results = await asyncio.gather(*[append_event(i) for i in range(10)])
        
        # 所有追加成功
        assert all(r.status == AppendStatus.SUCCESS for r in results)
        
        # 序列号从1到10
        sequences = sorted(r.sequence for r in results)
        assert sequences == list(range(1, 11))
        
        # 查询返回10个事件
        events = await store.query(task_id)
        assert len(events) == 10
