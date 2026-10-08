"""
投影存储接口（抽象层）

定义投影器与存储层的交互契约。

实际实现可以基于：
- PostgreSQL（事务支持）
- 内存存储（测试用）
- 其他支持事务的数据库

关键要求：
1. 投影 + Checkpoint + 去重记录必须在同一事务中保存
2. 支持乐观并发控制（条件更新）
3. 支持按分区查询 Checkpoint
4. 支持按实体 ID 查询投影
"""

from abc import ABC, abstractmethod
from typing import Any

from .checkpoint import ProjectionCheckpoint
from .models import (
    ActionProjection,
    TaskProjection,
    WorkerProjection,
    WorkflowProjection,
)


class ProjectionStorage(ABC):
    """
    投影存储接口（抽象基类）

    子类必须实现所有抽象方法，提供事务保证。
    """

    # ============ Checkpoint 操作 ============

    @abstractmethod
    def load_checkpoint(
        self,
        projection_name: str,
        partition_key: str,
    ) -> ProjectionCheckpoint:
        """
        加载 Checkpoint

        Args:
            projection_name: 投影名称
            partition_key: 分区键

        Returns:
            Checkpoint（若不存在则返回初始状态）
        """
        pass

    @abstractmethod
    def save_checkpoint(
        self,
        checkpoint: ProjectionCheckpoint,
    ) -> None:
        """
        保存 Checkpoint（独立保存，不在事务中）

        Args:
            checkpoint: Checkpoint 对象
        """
        pass

    @abstractmethod
    def list_all_checkpoints(self) -> list[ProjectionCheckpoint]:
        """
        列出所有 Checkpoint（用于健康监控）

        Returns:
            Checkpoint 列表
        """
        pass

    # ============ Task 投影操作 ============

    @abstractmethod
    def load_task_projection(self, task_id: str) -> TaskProjection | None:
        """
        加载 Task 投影

        Args:
            task_id: 任务 ID

        Returns:
            投影对象（若不存在则返回 None）
        """
        pass

    @abstractmethod
    def save_task_projection_with_checkpoint(
        self,
        projection: TaskProjection,
        checkpoint: ProjectionCheckpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """
        在同一事务中保存 Task 投影、Checkpoint 和去重记录

        Args:
            projection: Task 投影
            checkpoint: Checkpoint
            event_id: 事件 ID（用于去重）
            event_hash: 事件哈希（用于一致性校验）

        Raises:
            Exception: 事务失败时抛出异常
        """
        pass

    # ============ Workflow 投影操作 ============

    @abstractmethod
    def load_workflow_projection(
        self, workflow_id: str
    ) -> WorkflowProjection | None:
        """加载 Workflow 投影"""
        pass

    @abstractmethod
    def save_workflow_projection_with_checkpoint(
        self,
        projection: WorkflowProjection,
        checkpoint: ProjectionCheckpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """在同一事务中保存 Workflow 投影和 Checkpoint"""
        pass

    # ============ Worker 投影操作 ============

    @abstractmethod
    def load_worker_projection(self, worker_id: str) -> WorkerProjection | None:
        """加载 Worker 投影"""
        pass

    @abstractmethod
    def save_worker_projection_with_checkpoint(
        self,
        projection: WorkerProjection,
        checkpoint: ProjectionCheckpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """在同一事务中保存 Worker 投影和 Checkpoint"""
        pass

    # ============ Action 投影操作 ============

    @abstractmethod
    def load_action_projection(self, action_id: str) -> ActionProjection | None:
        """加载 Action 投影"""
        pass

    @abstractmethod
    def save_action_projection_with_checkpoint(
        self,
        projection: ActionProjection,
        checkpoint: ProjectionCheckpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """在同一事务中保存 Action 投影和 Checkpoint"""
        pass

    # ============ 事件查询（用于重建）============

    @abstractmethod
    def query_events(
        self,
        partition_key: str,
        start_sequence: int,
        end_sequence: int,
    ) -> list[dict[str, Any]]:
        """
        查询事件流（用于重建）

        Args:
            partition_key: 分区键
            start_sequence: 起始序列（包含）
            end_sequence: 结束序列（包含）

        Returns:
            事件列表（按序列排序）
        """
        pass

    @abstractmethod
    def get_latest_sequence(self, partition_key: str) -> int:
        """
        获取分区的最新序列号

        Args:
            partition_key: 分区键

        Returns:
            最新序列号
        """
        pass

    # ============ 去重记录操作 ============

    @abstractmethod
    def is_event_processed(
        self,
        projection_name: str,
        event_id: str,
    ) -> bool:
        """
        检查事件是否已被处理（去重检查）

        Args:
            projection_name: 投影名称
            event_id: 事件 ID

        Returns:
            是否已处理
        """
        pass

    @abstractmethod
    def mark_event_processed(
        self,
        projection_name: str,
        event_id: str,
        event_hash: str,
    ) -> None:
        """
        标记事件已处理（通常在事务中调用）

        Args:
            projection_name: 投影名称
            event_id: 事件 ID
            event_hash: 事件哈希
        """
        pass
