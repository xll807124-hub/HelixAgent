"""
集成测试：完整的投影流程

测试从事件应用到重建的完整流程。
"""

from datetime import datetime

from src.runtime.projection.in_memory_storage import InMemoryProjectionStorage
from src.runtime.projection.projector import EventApplicationResult
from src.runtime.projection.rebuilder import ProjectionHealthMonitor, ProjectionRebuilder
from src.runtime.projection.task_projector import TaskProjector
from src.runtime.projection.workflow_projector import WorkflowProjector


class TestProjectionIntegration:
    """集成测试：完整投影流程"""

    def setup_method(self):
        """每个测试前初始化"""
        self.storage = InMemoryProjectionStorage()
        self.task_projector = TaskProjector(self.storage)
        self.workflow_projector = WorkflowProjector(self.storage)

    def test_full_task_lifecycle(self):
        """测试完整的任务生命周期投影"""
        partition_key = "workflow:wf_test_001"

        # 事件序列
        events = [
            # 1. TaskCreated
            {
                "event_id": "evt_001",
                "event_type": "TaskCreated",
                "event_type_version": "v1",
                "sequence": 1,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {
                    "task_id": "task_001",
                    "organization_id": "org_001",
                    "project_id": "proj_001",
                    "repository_id": "repo_001",
                    "creator_id": "user_001",
                    "risk_level": "MEDIUM",
                    "base_revision": "abc123",
                    "created_at": datetime.utcnow().isoformat(),
                },
            },
            # 2. TaskStarted
            {
                "event_id": "evt_002",
                "event_type": "TaskStarted",
                "event_type_version": "v1",
                "sequence": 2,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {
                    "task_id": "task_001",
                    "started_at": datetime.utcnow().isoformat(),
                    "initial_step_id": "step_planning",
                },
            },
            # 3. WorkflowAttached
            {
                "event_id": "evt_003",
                "event_type": "WorkflowAttached",
                "event_type_version": "v1",
                "sequence": 3,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {
                    "task_id": "task_001",
                    "workflow_id": "wf_test_001",
                },
            },
            # 4. TaskCompleted
            {
                "event_id": "evt_004",
                "event_type": "TaskCompleted",
                "event_type_version": "v1",
                "sequence": 4,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {
                    "task_id": "task_001",
                    "completed_at": datetime.utcnow().isoformat(),
                    "final_revision": "def456",
                    "summary": {"pr_created": True},
                },
            },
        ]

        # 逐个应用事件
        for event in events:
            self.storage.add_event(event)
            result = self.task_projector.apply_event(event)
            assert result.result == EventApplicationResult.APPLIED

        # 验证最终投影状态
        projection = self.storage.load_task_projection("task_001")
        assert projection is not None
        assert projection.status == "COMPLETED"
        assert projection.current_workflow_id == "wf_test_001"
        assert projection.working_revision == "def456"
        assert projection.completion_summary == {"pr_created": True}
        assert projection.last_sequence == 4

    def test_workflow_worker_counting(self):
        """测试 Workflow Worker 计数汇聚"""
        partition_key = "workflow:wf_test_002"

        events = [
            # 1. WorkflowCreated
            {
                "event_id": "evt_001",
                "event_type": "WorkflowCreated",
                "event_type_version": "v1",
                "sequence": 1,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {
                    "workflow_id": "wf_test_002",
                    "task_id": "task_002",
                    "organization_id": "org_001",
                    "project_id": "proj_001",
                    "repository_id": "repo_001",
                    "workflow_template_id": "template_001",
                    "workflow_template_version": "v1.0",
                    "agent_profile_version": "v1.0",
                    "toolset_version": "v1.0",
                    "base_revision": "abc123",
                    "created_at": datetime.utcnow().isoformat(),
                },
            },
            # 2. WorkflowStarted
            {
                "event_id": "evt_002",
                "event_type": "WorkflowStarted",
                "event_type_version": "v1",
                "sequence": 2,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {
                    "workflow_id": "wf_test_002",
                    "started_at": datetime.utcnow().isoformat(),
                },
            },
            # 3. WorkerRegistered (x3)
            {
                "event_id": "evt_003",
                "event_type": "WorkerRegistered",
                "event_type_version": "v1",
                "sequence": 3,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {"worker_id": "worker_001"},
            },
            {
                "event_id": "evt_004",
                "event_type": "WorkerRegistered",
                "event_type_version": "v1",
                "sequence": 4,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {"worker_id": "worker_002"},
            },
            {
                "event_id": "evt_005",
                "event_type": "WorkerRegistered",
                "event_type_version": "v1",
                "sequence": 5,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {"worker_id": "worker_003"},
            },
            # 4. WorkerStarted (x2)
            {
                "event_id": "evt_006",
                "event_type": "WorkerStarted",
                "event_type_version": "v1",
                "sequence": 6,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {"worker_id": "worker_001"},
            },
            {
                "event_id": "evt_007",
                "event_type": "WorkerStarted",
                "event_type_version": "v1",
                "sequence": 7,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {"worker_id": "worker_002"},
            },
            # 5. WorkerCompleted (x1)
            {
                "event_id": "evt_008",
                "event_type": "WorkerCompleted",
                "event_type_version": "v1",
                "sequence": 8,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {"worker_id": "worker_001"},
            },
        ]

        # 应用所有事件
        for event in events:
            self.storage.add_event(event)
            result = self.workflow_projector.apply_event(event)
            assert result.result == EventApplicationResult.APPLIED

        # 验证计数
        projection = self.storage.load_workflow_projection("wf_test_002")
        assert projection is not None
        assert projection.required_worker_count == 3  # 3个注册
        assert projection.runnable_worker_count == 1  # 3注册 - 2启动
        assert projection.running_worker_count == 1  # 2启动 - 1完成
        assert projection.completed_worker_count == 1

    def test_rebuild_from_scratch(self):
        """测试从零重建投影"""
        partition_key = "workflow:wf_test_003"

        # 创建事件序列
        events = [
            {
                "event_id": f"evt_{i:03d}",
                "event_type": "TaskCreated" if i == 1 else "ArtifactCreated",
                "event_type_version": "v1",
                "sequence": i,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {
                    "task_id": "task_003",
                    "organization_id": "org_001",
                    "project_id": "proj_001",
                    "repository_id": "repo_001",
                    "creator_id": "user_001",
                    "risk_level": "LOW",
                    "base_revision": "abc123",
                    "created_at": datetime.utcnow().isoformat(),
                }
                if i == 1
                # 增量事件必须保留 task_id 字段，否则 _extract_entity_id 兜底到
                # partition_key（wf_test_003），找不到 task_003 投影。
                else {"task_id": "task_003", "artifact_id": f"artifact_{i}"},
            }
            for i in range(1, 11)
        ]

        # 添加事件到存储
        for event in events:
            self.storage.add_event(event)

        # 执行在线投影
        for event in events:
            self.task_projector.apply_event(event)

        online_projection = self.storage.load_task_projection("task_003")
        assert online_projection.artifact_count == 9  # 1个创建 + 9个产物

        # 清空投影，模拟重建场景
        self.storage.task_projections.clear()
        self.storage.checkpoints.clear()

        # 执行从零重建
        rebuilder = ProjectionRebuilder(
            projector=self.task_projector,
            event_store=self.storage,
        )

        result = rebuilder.rebuild_from_scratch(partition_key=partition_key)

        assert result.status == "COMPLETED"
        assert result.events_processed == 10
        assert result.events_applied == 10
        assert result.events_failed == 0

        # 验证重建后的投影
        rebuilt_projection = self.storage.load_task_projection("task_003")
        assert rebuilt_projection.artifact_count == 9

    def test_projection_health_monitoring(self):
        """测试投影健康监控"""
        partition_key = "workflow:wf_test_004"

        # 创建一些事件
        for i in range(1, 6):
            event = {
                "event_id": f"evt_{i:03d}",
                "event_type": "TaskCreated" if i == 1 else "ArtifactCreated",
                "event_type_version": "v1",
                "sequence": i,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                "payload": {
                    "task_id": "task_004",
                    "organization_id": "org_001",
                    "project_id": "proj_001",
                    "repository_id": "repo_001",
                    "creator_id": "user_001",
                    "risk_level": "LOW",
                    "base_revision": "abc123",
                    "created_at": datetime.utcnow().isoformat(),
                }
                if i == 1
                # 增量事件必须携带 task_id 字段（同 test_rebuild_from_scratch 的修复原因）。
                else {"task_id": "task_004", "artifact_id": f"artifact_{i}"},
            }
            self.storage.add_event(event)

        # 只应用前3个事件
        for i in range(1, 4):
            event = self.storage.query_events(partition_key, i, i)[0]
            self.task_projector.apply_event(event)

        # 检查健康状态
        monitor = ProjectionHealthMonitor(self.storage)
        health = monitor.get_projection_health("task_projection", partition_key)

        assert health["last_applied_sequence"] == 3
        assert health["latest_sequence"] == 5
        assert health["lag_events"] == 2
        assert health["status"] == "HEALTHY"

    def test_gap_detection_and_recovery(self):
        """测试序列缺口检测和恢复"""
        partition_key = "workflow:wf_test_005"

        # 事件1
        event1 = {
            "event_id": "evt_001",
            "event_type": "TaskCreated",
            "event_type_version": "v1",
            "sequence": 1,
            "partition_key": partition_key,
            "occurred_at": datetime.utcnow().isoformat(),
            "payload": {
                "task_id": "task_005",
                "organization_id": "org_001",
                "project_id": "proj_001",
                "repository_id": "repo_001",
                "creator_id": "user_001",
                "risk_level": "LOW",
                "base_revision": "abc123",
                "created_at": datetime.utcnow().isoformat(),
            },
        }

        self.storage.add_event(event1)
        result1 = self.task_projector.apply_event(event1)
        assert result1.result == EventApplicationResult.APPLIED

        # 跳过序列2-4，直接应用序列5
        event5 = {
            "event_id": "evt_005",
            "event_type": "ArtifactCreated",
            "event_type_version": "v1",
            "sequence": 5,
            "partition_key": partition_key,
            "occurred_at": datetime.utcnow().isoformat(),
            # 增量事件必须携带 task_id 字段。
            "payload": {"task_id": "task_005", "artifact_id": "artifact_005"},
        }

        self.storage.add_event(event5)
        result5 = self.task_projector.apply_event(event5)

        # 应该检测到缺口
        assert result5.result == EventApplicationResult.GAP_DETECTED
        assert result5.gap_from == 2
        assert result5.gap_to == 4

        # 检查 Checkpoint 状态
        checkpoint = self.storage.load_checkpoint("task_projection", partition_key)
        assert checkpoint.status.value == "BLOCKED"
        assert checkpoint.pending_gap_from == 2
        assert checkpoint.pending_gap_to == 4

        # 补齐缺失事件
        for i in range(2, 5):
            event = {
                "event_id": f"evt_{i:03d}",
                "event_type": "ArtifactCreated",
                "event_type_version": "v1",
                "sequence": i,
                "partition_key": partition_key,
                "occurred_at": datetime.utcnow().isoformat(),
                # 增量事件必须携带 task_id 字段。
                "payload": {"task_id": "task_005", "artifact_id": f"artifact_{i:03d}"},
            }
            self.storage.add_event(event)
            result = self.task_projector.apply_event(event)

            if i == 2:
                # 第一个补齐事件应该能应用（从 BLOCKED 恢复）
                assert result.result == EventApplicationResult.APPLIED

        # 现在应用序列5应该成功
        result5_retry = self.task_projector.apply_event(event5)
        assert result5_retry.result == EventApplicationResult.APPLIED

        # 验证投影状态
        projection = self.storage.load_task_projection("task_005")
        assert projection.artifact_count == 4  # 序列2-5共4个产物事件
