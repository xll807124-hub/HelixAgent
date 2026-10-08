"""
内存存储实现（用于测试和演示）

实现 ProjectionStorage 接口，提供内存版本的投影存储。

注意：
- 仅用于单元测试和本地演示
- 不提供持久化和分布式支持
- 事务通过 Python 异常回滚模拟
"""

from typing import Any

from .checkpoint import ProjectionCheckpoint
from .models import (
    ActionProjection,
    TaskProjection,
    WorkerProjection,
    WorkflowProjection,
)
from .storage import ProjectionStorage


class InMemoryProjectionStorage(ProjectionStorage):
    """内存投影存储（测试用）"""

    def __init__(self) -> None:
        # 存储结构
        self.checkpoints: dict[tuple[str, str], ProjectionCheckpoint] = {}
        self.task_projections: dict[str, TaskProjection] = {}
        self.workflow_projections: dict[str, WorkflowProjection] = {}
        self.worker_projections: dict[str, WorkerProjection] = {}
        self.action_projections: dict[str, ActionProjection] = {}
        self.processed_events: dict[tuple[str, str], str] = {}  # (projection, event_id) -> hash
        self.event_store: dict[tuple[str, int], dict[str, Any]] = {}  # type: ignore
        # noqa: E501 - (partition_key, sequence) -> event
        self.partition_max_sequence: dict[str, int] = {}

    # ============ Checkpoint 操作 ============

    def load_checkpoint(
        self,
        projection_name: str,
        partition_key: str,
    ) -> ProjectionCheckpoint:
        """加载 Checkpoint"""
        key = (projection_name, partition_key)
        if key not in self.checkpoints:
            # 返回初始 Checkpoint
            return ProjectionCheckpoint(
                projection_name=projection_name,
                projection_version="v1.0.0",
                partition_key=partition_key,
            )
        return self.checkpoints[key]

    def save_checkpoint(self, checkpoint: ProjectionCheckpoint) -> None:
        """保存 Checkpoint"""
        key = (checkpoint.projection_name, checkpoint.partition_key)
        self.checkpoints[key] = checkpoint

    def list_all_checkpoints(self) -> list[ProjectionCheckpoint]:
        """列出所有 Checkpoint"""
        return list(self.checkpoints.values())

    # ============ Task 投影操作 ============

    def load_task_projection(self, task_id: str) -> TaskProjection | None:
        """加载 Task 投影"""
        return self.task_projections.get(task_id)

    def save_task_projection_with_checkpoint(
        self,
        projection: TaskProjection,
        checkpoint: ProjectionCheckpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """在同一事务中保存 Task 投影和 Checkpoint"""
        # 模拟事务：全部成功或全部失败
        try:
            self.task_projections[projection.task_id] = projection
            self.save_checkpoint(checkpoint)
            self.mark_event_processed(
                checkpoint.projection_name, event_id, event_hash
            )
        except Exception as e:
            # 回滚（实际实现应在数据库事务中处理）
            raise e

    # ============ Workflow 投影操作 ============

    def load_workflow_projection(
        self, workflow_id: str
    ) -> WorkflowProjection | None:
        """加载 Workflow 投影"""
        return self.workflow_projections.get(workflow_id)

    def save_workflow_projection_with_checkpoint(
        self,
        projection: WorkflowProjection,
        checkpoint: ProjectionCheckpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """在同一事务中保存 Workflow 投影和 Checkpoint"""
        try:
            self.workflow_projections[projection.workflow_id] = projection
            self.save_checkpoint(checkpoint)
            self.mark_event_processed(
                checkpoint.projection_name, event_id, event_hash
            )
        except Exception as e:
            raise e

    # ============ Worker 投影操作 ============

    def load_worker_projection(self, worker_id: str) -> WorkerProjection | None:
        """加载 Worker 投影"""
        return self.worker_projections.get(worker_id)

    def save_worker_projection_with_checkpoint(
        self,
        projection: WorkerProjection,
        checkpoint: ProjectionCheckpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """在同一事务中保存 Worker 投影和 Checkpoint"""
        try:
            self.worker_projections[projection.worker_id] = projection
            self.save_checkpoint(checkpoint)
            self.mark_event_processed(
                checkpoint.projection_name, event_id, event_hash
            )
        except Exception as e:
            raise e

    # ============ Action 投影操作 ============

    def load_action_projection(self, action_id: str) -> ActionProjection | None:
        """加载 Action 投影"""
        return self.action_projections.get(action_id)

    def save_action_projection_with_checkpoint(
        self,
        projection: ActionProjection,
        checkpoint: ProjectionCheckpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """在同一事务中保存 Action 投影和 Checkpoint"""
        try:
            self.action_projections[projection.action_id] = projection
            self.save_checkpoint(checkpoint)
            self.mark_event_processed(
                checkpoint.projection_name, event_id, event_hash
            )
        except Exception as e:
            raise e

    # ============ 事件查询（用于重建）============

    def query_events(
        self,
        partition_key: str,
        start_sequence: int,
        end_sequence: int,
    ) -> list[dict[str, Any]]:
        """查询事件流"""
        events = []
        for (pk, seq), event in self.event_store.items():
            if pk == partition_key and start_sequence <= seq <= end_sequence:
                events.append(event)

        # 按序列排序
        events.sort(key=lambda e: e["sequence"])
        return events

    def get_latest_sequence(self, partition_key: str) -> int:
        """获取分区的最新序列号"""
        return self.partition_max_sequence.get(partition_key, 0)

    def add_event(self, event: dict[str, Any]) -> None:
        """添加事件到内存存储（测试辅助方法）"""
        partition_key = event["partition_key"]
        sequence = event["sequence"]

        self.event_store[(partition_key, sequence)] = event

        # 更新最大序列号
        current_max = self.partition_max_sequence.get(partition_key, 0)
        self.partition_max_sequence[partition_key] = max(current_max, sequence)

    # ============ 去重记录操作 ============

    def is_event_processed(
        self,
        projection_name: str,
        event_id: str,
    ) -> bool:
        """检查事件是否已被处理"""
        return (projection_name, event_id) in self.processed_events

    def mark_event_processed(
        self,
        projection_name: str,
        event_id: str,
        event_hash: str,
    ) -> None:
        """标记事件已处理"""
        self.processed_events[(projection_name, event_id)] = event_hash
