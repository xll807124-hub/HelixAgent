"""
Event Envelope 单元测试

测试覆盖：
- 创建合法事件信封
- 必填字段验证
- 字段类型验证
- 内容哈希计算
- 序列化/反序列化
- 因果引用验证
- 生产者引用验证
"""

import pytest
from datetime import datetime, timezone

from src.runtime.common.types import ActorRef, generate_entity_id, ensure_utc
from src.runtime.event_store import (
    EventEnvelope,
    EventCategory,
    CausationType,
    CausationRef,
    ProducerRef,
    ContentRef,
    DataSensitivity,
)


class TestEventEnvelope:
    """EventEnvelope 核心功能测试"""

    def test_smoke_create_minimal_event(self):
        """冒烟：创建最小合法事件"""
        event = EventEnvelope(
            event_type="TaskCreated",
            payload_schema="TaskCreated.v1",
            payload={"name": "test-task"},
        )
        
        assert event.event_id is not None
        assert event.event_type == "TaskCreated"
        assert event.payload_schema == "TaskCreated.v1"
        assert event.payload == {"name": "test-task"}
        assert event.sequence == 0  # 未分配序列
        assert event.event_category == EventCategory.DOMAIN
        assert event.schema_version == "runtime.event-envelope.v1"

    def test_smoke_event_has_default_values(self):
        """冒烟：事件有合理的默认值"""
        event = EventEnvelope(
            event_type="TestEvent",
            payload_schema="TestEvent.v1",
            payload={},
        )
        
        assert event.event_id is not None
        assert event.task_id is not None
        assert event.organization_id is not None
        assert event.project_id is not None
        assert event.repository_id is not None
        assert event.trace_id is not None
        assert event.correlation_id is not None
        assert event.occurred_at is not None
        assert event.occurred_at.tzinfo is not None  # 时区感知
        assert event.attempt == 1
        assert event.actor.actor_type == "SYSTEM"
        assert event.causation.causation_type == CausationType.COMMAND

    def test_boundary_event_type_required(self):
        """边界：event_type必填"""
        with pytest.raises(ValueError, match="event_type cannot be empty"):
            EventEnvelope(
                event_type="",
                payload_schema="Test.v1",
                payload={},
            )

    def test_boundary_payload_schema_required(self):
        """边界：payload_schema必填"""
        with pytest.raises(ValueError, match="payload_schema cannot be empty"):
            EventEnvelope(
                event_type="TestEvent",
                payload_schema="",
                payload={},
            )

    def test_boundary_occurred_at_must_be_timezone_aware(self):
        """边界：occurred_at必须带时区"""
        with pytest.raises(ValueError, match="must be timezone-aware"):
            EventEnvelope(
                event_type="TestEvent",
                payload_schema="Test.v1",
                payload={},
                occurred_at=datetime(2026, 10, 8, 12, 0, 0),  # naive datetime
            )

    def test_boundary_attempt_must_be_positive(self):
        """边界：attempt必须≥1"""
        with pytest.raises(ValueError, match="attempt must be >= 1"):
            EventEnvelope(
                event_type="TestEvent",
                payload_schema="Test.v1",
                payload={},
                attempt=0,
            )

    def test_boundary_sequence_cannot_be_negative(self):
        """边界：sequence不能为负"""
        with pytest.raises(ValueError, match="sequence must be non-negative"):
            EventEnvelope(
                event_type="TestEvent",
                payload_schema="Test.v1",
                payload={},
                sequence=-1,
            )

    def test_compute_content_hash_is_deterministic(self):
        """哈希：相同内容产生相同哈希"""
        event1 = EventEnvelope(
            event_id="550e8400-e29b-41d4-a716-446655440000",
            event_type="TestEvent",
            payload_schema="Test.v1",
            payload={"key": "value"},
            task_id="660e8400-e29b-41d4-a716-446655440000",
            occurred_at=ensure_utc(datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)),
        )
        
        event2 = EventEnvelope(
            event_id="550e8400-e29b-41d4-a716-446655440000",
            event_type="TestEvent",
            payload_schema="Test.v1",
            payload={"key": "value"},
            task_id="660e8400-e29b-41d4-a716-446655440000",
            occurred_at=ensure_utc(datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)),
        )
        
        hash1 = event1.compute_content_hash()
        hash2 = event2.compute_content_hash()
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def test_compute_content_hash_differs_for_different_content(self):
        """哈希：不同内容产生不同哈希"""
        event1 = EventEnvelope(
            event_type="TestEvent",
            payload_schema="Test.v1",
            payload={"key": "value1"},
        )
        
        event2 = EventEnvelope(
            event_type="TestEvent",
            payload_schema="Test.v1",
            payload={"key": "value2"},
        )
        
        hash1 = event1.compute_content_hash()
        hash2 = event2.compute_content_hash()
        
        assert hash1 != hash2

    def test_to_dict_includes_all_fields(self):
        """序列化：to_dict包含所有字段"""
        event = EventEnvelope(
            event_type="TestEvent",
            payload_schema="Test.v1",
            payload={"test": "data"},
            workflow_id="workflow-123",
            worker_id="worker-456",
            action_id="action-789",
            idempotency_key="idem-key-123",
        )
        
        data = event.to_dict()
        
        assert data["event_type"] == "TestEvent"
        assert data["payload_schema"] == "Test.v1"
        assert data["payload"] == {"test": "data"}
        assert data["workflow_id"] == "workflow-123"
        assert data["worker_id"] == "worker-456"
        assert data["action_id"] == "action-789"
        assert data["idempotency_key"] == "idem-key-123"
        assert data["schema_version"] == "runtime.event-envelope.v1"
        assert data["event_category"] == EventCategory.DOMAIN.value

    def test_from_dict_reconstructs_event(self):
        """反序列化：from_dict正确重建事件"""
        original = EventEnvelope(
            event_type="TestEvent",
            payload_schema="Test.v1",
            payload={"test": "data"},
            event_category=EventCategory.LIFECYCLE,
            idempotency_key="test-key",
        )
        
        data = original.to_dict()
        reconstructed = EventEnvelope.from_dict(data)
        
        assert reconstructed.event_id == original.event_id
        assert reconstructed.event_type == original.event_type
        assert reconstructed.payload_schema == original.payload_schema
        assert reconstructed.payload == original.payload
        assert reconstructed.event_category == original.event_category
        assert reconstructed.idempotency_key == original.idempotency_key

    def test_serialization_roundtrip(self):
        """序列化：往返转换保持一致"""
        original = EventEnvelope(
            event_type="ComplexEvent",
            payload_schema="Complex.v1",
            payload={"nested": {"data": [1, 2, 3]}},
            event_category=EventCategory.AUDIT,
            data_classification=DataSensitivity.CONFIDENTIAL,
        )
        
        data = original.to_dict()
        reconstructed = EventEnvelope.from_dict(data)
        
        assert reconstructed.compute_content_hash() == original.compute_content_hash()


class TestCausationRef:
    """CausationRef 验证测试"""

    def test_smoke_create_causation_ref(self):
        """冒烟：创建因果引用"""
        ref = CausationRef(
            causation_type=CausationType.EVENT,
            causation_id="parent-event-123",
            parent_event_id="parent-id",
            root_event_id="root-id",
        )
        
        assert ref.causation_type == CausationType.EVENT
        assert ref.causation_id == "parent-event-123"
        assert ref.parent_event_id == "parent-id"
        assert ref.root_event_id == "root-id"

    def test_exception_causation_id_required(self):
        """异常：causation_id不能为空"""
        with pytest.raises(ValueError, match="causation_id cannot be empty"):
            CausationRef(
                causation_type=CausationType.COMMAND,
                causation_id="",
            )


class TestProducerRef:
    """ProducerRef 验证测试"""

    def test_smoke_create_producer_ref(self):
        """冒烟：创建生产者引用"""
        ref = ProducerRef(
            producer_type="WORKER",
            producer_id="coder-worker",
            producer_version="v1.2.3",
        )
        
        assert ref.producer_type == "WORKER"
        assert ref.producer_id == "coder-worker"
        assert ref.producer_version == "v1.2.3"

    def test_exception_producer_type_required(self):
        """异常：producer_type不能为空"""
        with pytest.raises(ValueError, match="producer_type cannot be empty"):
            ProducerRef(
                producer_type="",
                producer_id="test",
                producer_version="v1",
            )

    def test_exception_producer_id_required(self):
        """异常：producer_id不能为空"""
        with pytest.raises(ValueError, match="producer_id cannot be empty"):
            ProducerRef(
                producer_type="SYSTEM",
                producer_id="",
                producer_version="v1",
            )

    def test_exception_producer_version_required(self):
        """异常：producer_version不能为空"""
        with pytest.raises(ValueError, match="producer_version cannot be empty"):
            ProducerRef(
                producer_type="SYSTEM",
                producer_id="runtime",
                producer_version="",
            )


class TestContentRef:
    """ContentRef 验证测试"""

    def test_smoke_create_content_ref(self):
        """冒烟：创建内容引用"""
        ref = ContentRef(
            content_type="DIFF",
            storage_url="s3://bucket/diff-123.txt",
            content_hash="abc123",
            size_bytes=1024,
        )
        
        assert ref.content_type == "DIFF"
        assert ref.storage_url == "s3://bucket/diff-123.txt"
        assert ref.content_hash == "abc123"
        assert ref.size_bytes == 1024

    def test_exception_content_type_required(self):
        """异常：content_type不能为空"""
        with pytest.raises(ValueError, match="content_type cannot be empty"):
            ContentRef(
                content_type="",
                storage_url="s3://test",
                content_hash="hash",
                size_bytes=100,
            )

    def test_exception_storage_url_required(self):
        """异常：storage_url不能为空"""
        with pytest.raises(ValueError, match="storage_url cannot be empty"):
            ContentRef(
                content_type="LOG",
                storage_url="",
                content_hash="hash",
                size_bytes=100,
            )

    def test_exception_content_hash_required(self):
        """异常：content_hash不能为空"""
        with pytest.raises(ValueError, match="content_hash cannot be empty"):
            ContentRef(
                content_type="LOG",
                storage_url="s3://test",
                content_hash="",
                size_bytes=100,
            )

    def test_exception_size_bytes_cannot_be_negative(self):
        """异常：size_bytes不能为负"""
        with pytest.raises(ValueError, match="size_bytes must be non-negative"):
            ContentRef(
                content_type="LOG",
                storage_url="s3://test",
                content_hash="hash",
                size_bytes=-1,
            )
