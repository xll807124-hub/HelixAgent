"""
ProjectionRebuilder & HealthMonitor 单元测试（REQ-RT-004 §8）

补齐覆盖率：rebuilder.py 原 48%，目标 ≥ 80%。
"""

from datetime import datetime

from src.runtime.projection.checkpoint import ProjectionCheckpoint, ProjectionStatus
from src.runtime.projection.in_memory_storage import InMemoryProjectionStorage
from src.runtime.projection.rebuilder import (
    ProjectionHealthMonitor,
    ProjectionRebuilder,
)
from src.runtime.projection.task_projector import TaskProjector


def _mk_event(event_id, event_type, sequence, payload, partition_key="workflow:wf_rebuild_test"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "event_type_version": "v1",
        "sequence": sequence,
        "partition_key": partition_key,
        "occurred_at": datetime.now().isoformat(),
        "payload": payload,
    }


def _seed_task_events(storage, partition_key, count=5):
    """生成 1 个 TaskCreated + (count-1) 个 ArtifactCreated 事件"""
    events = [
        _mk_event(
            f"evt_{i:03d}",
            "TaskCreated" if i == 1 else "ArtifactCreated",
            i,
            {
                "task_id": "task_rebuild_001",
                "organization_id": "org_001",
                "project_id": "proj_001",
                "repository_id": "repo_001",
                "creator_id": "user_001",
                "risk_level": "LOW",
                "base_revision": "abc",
                "created_at": datetime.now().isoformat(),
            }
            if i == 1
            else {"task_id": "task_rebuild_001", "artifact_id": f"art_{i}"},
            partition_key=partition_key,
        )
        for i in range(1, count + 1)
    ]
    for e in events:
        storage.add_event(e)
    return events


class TestRebuilderFromScratch:
    """从零重建"""

    def test_rebuild_from_scratch_success(self):
        """正常从零重建：5 个事件全部应用"""
        storage = InMemoryProjectionStorage()
        tp = TaskProjector(storage)
        partition_key = "workflow:wf_rebuild_001"
        _seed_task_events(storage, partition_key, count=5)

        rebuilder = ProjectionRebuilder(projector=tp, event_store=storage)
        result = rebuilder.rebuild_from_scratch(partition_key=partition_key)

        assert result.status == "COMPLETED"
        assert result.events_processed == 5
        assert result.events_applied == 5
        assert result.events_failed == 0
        assert result.events_skipped == 0
        assert result.completed_at is not None
        # 重建应创建投影
        proj = storage.load_task_projection("task_rebuild_001")
        assert proj is not None
        assert proj.artifact_count == 4  # 1 创建 + 4 产物

    def test_rebuild_with_end_sequence(self):
        """指定 end_sequence 截断"""
        storage = InMemoryProjectionStorage()
        tp = TaskProjector(storage)
        partition_key = "workflow:wf_rebuild_002"
        _seed_task_events(storage, partition_key, count=10)

        rebuilder = ProjectionRebuilder(projector=tp, event_store=storage)
        result = rebuilder.rebuild_from_scratch(
            partition_key=partition_key, end_sequence=5
        )
        assert result.events_processed == 5
        assert result.events_applied == 5

    def test_rebuild_with_no_events(self):
        """无事件流的 partition：返回 COMPLETED 但 0 应用"""
        storage = InMemoryProjectionStorage()
        tp = TaskProjector(storage)

        rebuilder = ProjectionRebuilder(projector=tp, event_store=storage)
        result = rebuilder.rebuild_from_scratch(partition_key="workflow:nonexistent")
        assert result.status == "COMPLETED"
        assert result.events_processed == 0

    def test_rebuild_with_custom_rebuild_id(self):
        """自定义 rebuild_id 用于隔离"""
        storage = InMemoryProjectionStorage()
        tp = TaskProjector(storage)
        rebuilder = ProjectionRebuilder(
            projector=tp, event_store=storage, rebuild_id="my_rebuild_001"
        )
        assert rebuilder.rebuild_id == "my_rebuild_001"


class TestRebuilderFromCheckpoint:
    """从 Checkpoint 增量重建"""

    def test_rebuild_from_checkpoint_success(self):
        """Checkpoint 已 applied seq=3，从 seq=4 开始"""
        storage = InMemoryProjectionStorage()
        tp = TaskProjector(storage)
        partition_key = "workflow:wf_rebuild_chk_001"
        _seed_task_events(storage, partition_key, count=6)

        # 先在线应用前 3 个事件
        for i in range(1, 4):
            tp.apply_event(_mk_event(
                f"evt_{i:03d}", "TaskCreated" if i == 1 else "ArtifactCreated",
                i,
                {
                    "task_id": "task_rebuild_001",
                    "organization_id": "org_001",
                    "project_id": "proj_001",
                    "repository_id": "repo_001",
                    "creator_id": "user_001",
                    "risk_level": "LOW",
                    "base_revision": "abc",
                    "created_at": datetime.now().isoformat(),
                } if i == 1 else {"task_id": "task_rebuild_001", "artifact_id": f"art_{i}"},
                partition_key=partition_key,
            ))

        cp = storage.load_checkpoint("task_projection", partition_key)
        assert cp.last_applied_sequence == 3

        rebuilder = ProjectionRebuilder(projector=tp, event_store=storage)
        result = rebuilder.rebuild_from_checkpoint(
            partition_key=partition_key, checkpoint=cp
        )
        assert result.status == "COMPLETED"
        assert result.events_processed == 3  # 4, 5, 6
        assert result.events_applied == 3

    def test_rebuild_from_failed_checkpoint_rejected(self):
        """FAILED Checkpoint 不允许增量重建"""
        storage = InMemoryProjectionStorage()
        tp = TaskProjector(storage)

        cp = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_failed",
        )
        cp.mark_failed("test failure")

        rebuilder = ProjectionRebuilder(projector=tp, event_store=storage)
        result = rebuilder.rebuild_from_checkpoint(
            partition_key="workflow:wf_failed", checkpoint=cp
        )
        assert result.status == "FAILED"
        assert "FAILED" in result.error_message or "失败" in result.error_message


class TestRebuilderValidateRebuild:
    """validate_rebuild 一致性比对"""

    def test_validate_rebuild_identical(self):
        """两个相同投影：is_consistent=True"""
        from src.runtime.projection.models import TaskProjection

        proj1 = TaskProjection(
            task_id="t1", organization_id="o1", project_id="p1",
            repository_id="r1", creator_id="u1", risk_level="LOW",
            base_revision="abc",
            status="COMPLETED", last_event_id="e1", last_sequence=1,
            last_event_type="TaskCreated",
            projection_version="v1", created_at=datetime.now(), updated_at=datetime.now(),
        )
        proj2 = proj1.model_copy()
        rebuilder = ProjectionRebuilder(
            projector=TaskProjector(InMemoryProjectionStorage()),
            event_store=InMemoryProjectionStorage(),
        )
        is_consistent, diffs = rebuilder.validate_rebuild(proj1, proj2, ["status", "task_id"])
        assert is_consistent
        assert diffs == {}

    def test_validate_rebuild_different_status(self):
        """status 字段不一致：is_consistent=False，记录差异"""
        from src.runtime.projection.models import TaskProjection

        proj1 = TaskProjection(
            task_id="t1", organization_id="o1", project_id="p1",
            repository_id="r1", creator_id="u1", risk_level="LOW",
            base_revision="abc",
            status="COMPLETED", last_event_id="e1", last_sequence=1,
            last_event_type="TaskCreated",
            projection_version="v1", created_at=datetime.now(), updated_at=datetime.now(),
        )
        proj2 = proj1.model_copy()
        proj2.status = "FAILED"
        rebuilder = ProjectionRebuilder(
            projector=TaskProjector(InMemoryProjectionStorage()),
            event_store=InMemoryProjectionStorage(),
        )
        is_consistent, diffs = rebuilder.validate_rebuild(proj1, proj2, ["status"])
        assert not is_consistent
        assert "status" in diffs
        assert diffs["status"]["online"] == "COMPLETED"
        assert diffs["status"]["rebuilt"] == "FAILED"


class TestHealthMonitor:
    """ProjectionHealthMonitor"""

    def test_get_health_healthy(self):
        """健康状态：lag=0, status=HEALTHY"""
        storage = InMemoryProjectionStorage()
        tp = TaskProjector(storage)
        partition_key = "workflow:wf_health_001"
        _seed_task_events(storage, partition_key, count=3)

        # 应用前 3 个事件
        for i in range(1, 4):
            tp.apply_event(_mk_event(
                f"evt_{i:03d}", "TaskCreated" if i == 1 else "ArtifactCreated",
                i,
                {
                    "task_id": "task_rebuild_001", "organization_id": "o",
                    "project_id": "p", "repository_id": "r", "creator_id": "u",
                    "risk_level": "LOW", "base_revision": "b",
                    "created_at": datetime.now().isoformat(),
                } if i == 1 else {"task_id": "task_rebuild_001", "artifact_id": f"a{i}"},
                partition_key=partition_key,
            ))

        monitor = ProjectionHealthMonitor(storage)
        health = monitor.get_projection_health("task_projection", partition_key)
        assert health["status"] == "HEALTHY"
        assert health["last_applied_sequence"] == 3
        assert health["latest_sequence"] == 3
        assert health["lag_events"] == 0

    def test_get_health_with_lag(self):
        """有 lag：last_applied < latest"""
        storage = InMemoryProjectionStorage()
        tp = TaskProjector(storage)
        partition_key = "workflow:wf_health_002"
        _seed_task_events(storage, partition_key, count=5)

        # 只应用前 3 个事件
        for i in range(1, 4):
            tp.apply_event(_mk_event(
                f"evt_{i:03d}", "TaskCreated" if i == 1 else "ArtifactCreated",
                i,
                {
                    "task_id": "task_rebuild_001", "organization_id": "o",
                    "project_id": "p", "repository_id": "r", "creator_id": "u",
                    "risk_level": "LOW", "base_revision": "b",
                    "created_at": datetime.now().isoformat(),
                } if i == 1 else {"task_id": "task_rebuild_001", "artifact_id": f"a{i}"},
                partition_key=partition_key,
            ))

        monitor = ProjectionHealthMonitor(storage)
        health = monitor.get_projection_health("task_projection", partition_key)
        assert health["last_applied_sequence"] == 3
        assert health["latest_sequence"] == 5
        assert health["lag_events"] == 2

    def test_get_health_no_checkpoint(self):
        """无 Checkpoint 的 partition：返回初始（last_applied=0）"""
        storage = InMemoryProjectionStorage()
        monitor = ProjectionHealthMonitor(storage)
        health = monitor.get_projection_health(
            "task_projection", "workflow:nonexistent"
        )
        assert health["last_applied_sequence"] == 0
        assert health["status"] == "HEALTHY"

    def test_list_unhealthy_blocked(self):
        """BLOCKED 状态的投影列入不健康列表"""
        storage = InMemoryProjectionStorage()
        cp = ProjectionCheckpoint(
            projection_name="p1", projection_version="v1.0.0",
            partition_key="workflow:wf_blocked",
        )
        cp.status = ProjectionStatus.BLOCKED
        storage.save_checkpoint(cp)

        monitor = ProjectionHealthMonitor(storage)
        unhealthy = monitor.list_unhealthy_projections()
        assert len(unhealthy) == 1
        assert unhealthy[0]["status"] == "BLOCKED"
        assert unhealthy[0]["partition_key"] == "workflow:wf_blocked"

    def test_list_unhealthy_lagging(self):
        """lag > threshold 的投影列入不健康"""
        storage = InMemoryProjectionStorage()
        partition_key = "workflow:wf_lagging"
        # 添加 200 个事件
        for i in range(1, 201):
            storage.add_event(_mk_event(
                f"evt_{i:04d}", "TaskCreated" if i == 1 else "ArtifactCreated",
                i,
                {
                    "task_id": "t1", "organization_id": "o", "project_id": "p",
                    "repository_id": "r", "creator_id": "u", "risk_level": "LOW",
                    "base_revision": "b", "created_at": datetime.now().isoformat(),
                } if i == 1 else {"task_id": "t1", "artifact_id": f"a{i}"},
                partition_key=partition_key,
            ))

        # 创建一个 Checkpoint，last_applied=0（即所有事件都没处理）
        cp = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key=partition_key,
        )
        storage.save_checkpoint(cp)

        monitor = ProjectionHealthMonitor(storage)
        unhealthy = monitor.list_unhealthy_projections(lag_threshold=100)
        # 200 个事件没处理，lag=200 > 100，应被列入
        assert any(u["status"] == "LAGGING" for u in unhealthy)
        lagging = [u for u in unhealthy if u["status"] == "LAGGING"][0]
        assert lagging["lag_events"] == 200

    def test_list_unhealthy_empty_when_all_healthy(self):
        """全部健康的存储：unhealthy 为空"""
        storage = InMemoryProjectionStorage()
        monitor = ProjectionHealthMonitor(storage)
        unhealthy = monitor.list_unhealthy_projections()
        assert unhealthy == []