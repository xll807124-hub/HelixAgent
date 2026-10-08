"""
单元测试：BaseProjector 事件应用逻辑

测试投影器的通用处理流程。
"""

from datetime import datetime

from pydantic import BaseModel

from src.runtime.projection.checkpoint import ProjectionCheckpoint
from src.runtime.projection.projector import (
    BaseProjector,
    EventApplicationResult,
)

# ============ 测试用的简单投影模型 ============


class SimpleProjection(BaseModel):
    """测试用的简单投影"""

    entity_id: str
    counter: int = 0
    status: str = "INIT"
    last_event_id: str = ""
    last_sequence: int = 0


# ============ 测试用的投影器实现 ============


class TestProjector(BaseProjector[SimpleProjection]):
    """测试用投影器"""

    def __init__(self):
        super().__init__()
        self.projections = {}  # 内存存储
        self.checkpoints = {}

    def get_projection_name(self) -> str:
        return "test_projection"

    def get_projection_version(self) -> str:
        return "v1.0.0"

    def _apply_event_to_projection(self, projection, event):
        """简单的事件应用逻辑"""
        payload = event["payload"]
        event_type = event["event_type"]

        if event_type == "EntityCreated":
            return SimpleProjection(
                entity_id=payload["entity_id"],
                counter=0,
                status="CREATED",
                last_event_id=event["event_id"],
                last_sequence=event["sequence"],
            )

        if projection is None:
            raise ValueError("Projection not found")

        if event_type == "CounterIncremented":
            projection.counter += payload["increment"]
        elif event_type == "StatusChanged":
            projection.status = payload["new_status"]

        projection.last_event_id = event["event_id"]
        projection.last_sequence = event["sequence"]
        return projection

    def _validate_state_invariants(self, projection):
        """简单的不变量校验"""
        if projection.counter < 0:
            return False, "Counter cannot be negative"
        return True, "OK"

    def _save_projection_transaction(self, projection, checkpoint, event_id, event_hash):
        """保存到内存"""
        self.projections[projection.entity_id] = projection
        self.checkpoints[checkpoint.partition_key] = checkpoint

    def _load_checkpoint(self, partition_key):
        """从内存加载"""
        if partition_key not in self.checkpoints:
            return ProjectionCheckpoint(
                projection_name=self.get_projection_name(),
                projection_version=self.get_projection_version(),
                partition_key=partition_key,
            )
        return self.checkpoints[partition_key]

    def _load_projection(self, entity_id):
        """从内存加载"""
        return self.projections.get(entity_id)


# ============ 测试用例 ============


class TestBaseProjectorEventApplication:
    """测试事件应用流程"""

    def test_apply_first_event_success(self):
        """测试应用第一个事件"""
        projector = TestProjector()

        event = {
            "event_id": "evt_001",
            "event_type": "EntityCreated",
            "event_type_version": "v1",
            "sequence": 1,
            "partition_key": "workflow:wf_test",
            "occurred_at": datetime.utcnow().isoformat(),
            "payload": {"entity_id": "ent_001"},
        }

        result = projector.apply_event(event)

        assert result.result == EventApplicationResult.APPLIED
        assert result.applied_sequence == 1
        assert projector.projections["ent_001"].counter == 0
        assert projector.projections["ent_001"].status == "CREATED"

    def test_apply_duplicate_event_ignored(self):
        """测试重复事件被忽略"""
        projector = TestProjector()

        event1 = {
            "event_id": "evt_001",
            "event_type": "EntityCreated",
            "event_type_version": "v1",
            "sequence": 1,
            "partition_key": "workflow:wf_test",
            "occurred_at": datetime.utcnow().isoformat(),
            "payload": {"entity_id": "ent_001"},
        }

        # 第一次应用
        result1 = projector.apply_event(event1)
        assert result1.result == EventApplicationResult.APPLIED

        # 第二次应用相同事件
        result2 = projector.apply_event(event1)
        assert result2.result == EventApplicationResult.DUPLICATE_IGNORED

    def test_apply_gap_detected(self):
        """测试检测序列缺口"""
        projector = TestProjector()

        event1 = {
            "event_id": "evt_001",
            "event_type": "EntityCreated",
            "event_type_version": "v1",
            "sequence": 1,
            "partition_key": "workflow:wf_test",
            "occurred_at": datetime.utcnow().isoformat(),
            "payload": {"entity_id": "ent_001"},
        }

        projector.apply_event(event1)

        # 跳过序列 2，直接应用序列 5
        event5 = {
            "event_id": "evt_005",
            "event_type": "CounterIncremented",
            "event_type_version": "v1",
            "sequence": 5,
            "partition_key": "workflow:wf_test",
            "occurred_at": datetime.utcnow().isoformat(),
            "payload": {"increment": 10},
        }

        result = projector.apply_event(event5)

        assert result.result == EventApplicationResult.GAP_DETECTED
        assert result.gap_from == 2
        assert result.gap_to == 4

    def test_apply_events_in_sequence(self):
        """测试按序应用多个事件"""
        projector = TestProjector()

        events = [
            {
                "event_id": "evt_001",
                "event_type": "EntityCreated",
                "event_type_version": "v1",
                "sequence": 1,
                "partition_key": "workflow:wf_test",
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {"entity_id": "ent_001"},
            },
            {
                "event_id": "evt_002",
                "event_type": "CounterIncremented",
                "event_type_version": "v1",
                "sequence": 2,
                "partition_key": "workflow:wf_test",
                "occurred_at": datetime.utcnow().isoformat(),
                # 增量事件必须保留 entity_id 字段，否则 _extract_entity_id 兜底到
                # partition_key（wf_test），找不到已创建的 ent_001 投影。
                "payload": {"entity_id": "ent_001", "increment": 5},
            },
            {
                "event_id": "evt_003",
                "event_type": "StatusChanged",
                "event_type_version": "v1",
                "sequence": 3,
                "partition_key": "workflow:wf_test",
                "occurred_at": datetime.utcnow().isoformat(),
                # 同上：增量事件必须保留 entity_id。
                "payload": {"entity_id": "ent_001", "new_status": "ACTIVE"},
            },
        ]

        for event in events:
            result = projector.apply_event(event)
            assert result.result == EventApplicationResult.APPLIED

        projection = projector.projections["ent_001"]
        assert projection.counter == 5
        assert projection.status == "ACTIVE"
        assert projection.last_sequence == 3

    def test_event_hash_conflict_detection(self):
        """测试事件哈希冲突检测"""
        projector = TestProjector()

        event1 = {
            "event_id": "evt_001",
            "event_type": "EntityCreated",
            "event_type_version": "v1",
            "sequence": 1,
            "partition_key": "workflow:wf_test",
            "occurred_at": datetime.utcnow().isoformat(),
            "payload": {"entity_id": "ent_001"},
        }

        projector.apply_event(event1)

        # 相同 event_id 但不同 payload（模拟冲突）
        event1_conflict = {
            "event_id": "evt_001",
            "event_type": "EntityCreated",
            "event_type_version": "v1",
            "sequence": 1,
            "partition_key": "workflow:wf_test",
            "occurred_at": datetime.utcnow().isoformat(),
            "payload": {"entity_id": "ent_002"},  # 不同的 payload
        }

        result = projector.apply_event(event1_conflict)
        assert result.result == EventApplicationResult.REFERENCE_CONFLICT
        assert "哈希冲突" in result.message

    def test_batch_apply_events(self):
        """测试批量应用事件"""
        projector = TestProjector()

        events = [
            {
                "event_id": f"evt_{i:03d}",
                "event_type": "EntityCreated" if i == 1 else "CounterIncremented",
                "event_type_version": "v1",
                "sequence": i,
                "partition_key": "workflow:wf_test",
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {"entity_id": "ent_001"}
                if i == 1
                else {"entity_id": "ent_001", "increment": 1},
            }
            for i in range(1, 11)
        ]

        results = projector.apply_events_batch(events)

        assert len(results) == 10
        assert all(r.result == EventApplicationResult.APPLIED for r in results)

        projection = projector.projections["ent_001"]
        assert projection.counter == 9  # 1个创建事件 + 9个增量事件
        assert projection.last_sequence == 10

    def test_validate_event_envelope(self):
        """测试事件格式校验"""
        projector = TestProjector()

        # 缺少必需字段
        invalid_event = {
            "event_id": "evt_001",
            "event_type": "EntityCreated",
            # 缺少其他必需字段
        }

        result = projector.apply_event(invalid_event)
        assert result.result == EventApplicationResult.FAILED
        assert "缺少必需字段" in result.message
