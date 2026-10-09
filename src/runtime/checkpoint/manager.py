"""
Checkpoint Manager（REQ-RT-005 §5, §6）

职责：
1. 保存检查点（原子性保证）
2. 读取检查点
3. 列出检查点
4. 校验检查点完整性
5. 标记无效检查点
6. 查找最新有效检查点（含回退逻辑）

核心原则（REQ-RT-005 §3, §6.3）：
- 检查点创建后不可修改（不可变性）
- 哈希篡改必须被检测
- 损坏时自动回退到更早有效点
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from src.runtime.checkpoint.models import CheckpointStatus, WorkflowCheckpoint

if TYPE_CHECKING:
    pass


class CheckpointManagerError(Exception):
    """Checkpoint Manager 异常"""

    pass


class CheckpointVerificationError(CheckpointManagerError):
    """检查点校验失败"""

    pass


class CheckpointStorage(ABC):
    """
    检查点存储接口（抽象类）

    子类必须实现持久化逻辑（文件系统、数据库、对象存储等）
    """

    @abstractmethod
    def store(self, checkpoint: WorkflowCheckpoint) -> None:
        """
        持久化检查点

        Args:
            checkpoint: 检查点对象

        Raises:
            CheckpointManagerError: 存储失败
        """
        pass

    @abstractmethod
    def retrieve(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        """
        读取检查点

        Args:
            checkpoint_id: 检查点ID

        Returns:
            检查点对象，不存在则返回 None
        """
        pass

    @abstractmethod
    def list_by_workflow(
        self, workflow_id: str, limit: int = 10
    ) -> list[WorkflowCheckpoint]:
        """
        按 workflow_id 列出检查点（按创建时间倒序）

        Args:
            workflow_id: Workflow ID
            limit: 返回数量限制

        Returns:
            检查点列表
        """
        pass

    @abstractmethod
    def mark_invalid(self, checkpoint_id: str, reason: str) -> None:
        """
        标记检查点为无效

        Args:
            checkpoint_id: 检查点ID
            reason: 失效原因
        """
        pass


class InMemoryCheckpointStorage(CheckpointStorage):
    """
    内存检查点存储（MVP 实现）

    用于测试和开发，不适合生产环境
    """

    def __init__(self) -> None:
        self._checkpoints: dict[str, WorkflowCheckpoint] = {}
        self._invalid_checkpoints: dict[str, str] = {}  # checkpoint_id -> reason

    def store(self, checkpoint: WorkflowCheckpoint) -> None:
        """持久化检查点到内存"""
        if checkpoint.checkpoint_id in self._checkpoints:
            raise CheckpointManagerError(
                f"Checkpoint {checkpoint.checkpoint_id} already exists"
            )
        self._checkpoints[checkpoint.checkpoint_id] = checkpoint

    def retrieve(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        """从内存读取检查点"""
        return self._checkpoints.get(checkpoint_id)

    def list_by_workflow(
        self, workflow_id: str, limit: int = 10
    ) -> list[WorkflowCheckpoint]:
        """按 workflow_id 列出检查点（按创建时间倒序）"""
        filtered = [
            cp for cp in self._checkpoints.values() if cp.workflow_id == workflow_id
        ]
        sorted_checkpoints = sorted(
            filtered, key=lambda cp: cp.created_at, reverse=True
        )
        return sorted_checkpoints[:limit]

    def mark_invalid(self, checkpoint_id: str, reason: str) -> None:
        """标记检查点为无效"""
        self._invalid_checkpoints[checkpoint_id] = reason

    def is_invalid(self, checkpoint_id: str) -> bool:
        """检查检查点是否被标记为无效"""
        return checkpoint_id in self._invalid_checkpoints

    def get_invalid_reason(self, checkpoint_id: str) -> str | None:
        """获取无效原因"""
        return self._invalid_checkpoints.get(checkpoint_id)


class CheckpointManager:
    """
    检查点管理器

    提供检查点的保存、读取、校验、回退等操作
    """

    def __init__(self, storage: CheckpointStorage) -> None:
        self.storage = storage

    def save_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None:
        """
        保存检查点（原子性保证）

        Args:
            checkpoint: 检查点对象

        Raises:
            CheckpointManagerError: 保存失败
        """
        # 1. 验证检查点完整性
        self.verify_checkpoint(checkpoint)

        # 2. 持久化（由存储层保证原子性）
        self.storage.store(checkpoint)

    def get_checkpoint(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        """
        读取检查点

        Args:
            checkpoint_id: 检查点ID

        Returns:
            检查点对象，不存在则返回 None
        """
        checkpoint = self.storage.retrieve(checkpoint_id)
        if checkpoint:
            # 读取时也验证完整性
            try:
                self.verify_checkpoint(checkpoint)
            except CheckpointVerificationError as e:
                # 自动标记为无效
                self.storage.mark_invalid(checkpoint_id, str(e))
                raise
        return checkpoint

    def list_checkpoints(
        self, workflow_id: str, limit: int = 10
    ) -> list[WorkflowCheckpoint]:
        """
        列出检查点

        Args:
            workflow_id: Workflow ID
            limit: 返回数量限制

        Returns:
            检查点列表（按创建时间倒序）
        """
        return self.storage.list_by_workflow(workflow_id, limit)

    def verify_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None:
        """
        校验检查点完整性（REQ-RT-005 §6.1）

        验证内容：
        1. 哈希一致性（防篡改）
        2. 必填字段存在
        3. 检查点状态合法

        Args:
            checkpoint: 检查点对象

        Raises:
            CheckpointVerificationError: 校验失败
        """
        # 1. 重新计算哈希
        checkpoint_dict = checkpoint.model_dump(mode="json")
        original_hash = checkpoint_dict.pop("checkpoint_hash", None)

        if not original_hash:
            raise CheckpointVerificationError("Missing checkpoint_hash")

        computed_hash = self._compute_hash(checkpoint_dict)

        if computed_hash != original_hash:
            raise CheckpointVerificationError(
                f"Hash mismatch: expected {original_hash}, got {computed_hash}"
            )

        # 2. 验证必填字段
        required_fields = [
            "checkpoint_id",
            "workflow_id",
            "task_id",
            "source_event_sequence",
            "source_event_id",
            "source_event_hash",
        ]
        for field in required_fields:
            if not getattr(checkpoint, field, None):
                raise CheckpointVerificationError(f"Missing required field: {field}")

        # 3. 验证状态
        if checkpoint.checkpoint_status not in [
            CheckpointStatus.CREATED,
            CheckpointStatus.VERIFIED,
        ]:
            raise CheckpointVerificationError(
                f"Invalid checkpoint_status: {checkpoint.checkpoint_status}"
            )

    def mark_invalid(self, checkpoint_id: str, reason: str) -> None:
        """
        标记无效检查点

        Args:
            checkpoint_id: 检查点ID
            reason: 失效原因
        """
        self.storage.mark_invalid(checkpoint_id, reason)

    def find_valid_checkpoint(self, workflow_id: str) -> WorkflowCheckpoint | None:
        """
        查找最新有效检查点（含回退逻辑 REQ-RT-005 §6.3）

        回退策略：
        1. 尝试最新检查点
        2. 如果损坏，标记为无效并回退到前一个
        3. 重复直到找到有效检查点或无更多检查点

        Args:
            workflow_id: Workflow ID

        Returns:
            最新有效检查点，或 None（无有效检查点）
        """
        checkpoints = self.list_checkpoints(workflow_id, limit=10)

        for checkpoint in checkpoints:
            # 跳过已标记为无效的检查点
            if isinstance(self.storage, InMemoryCheckpointStorage):
                if self.storage.is_invalid(checkpoint.checkpoint_id):
                    continue

            try:
                self.verify_checkpoint(checkpoint)
                return checkpoint
            except CheckpointVerificationError as e:
                # 自动标记为无效并尝试下一个
                self.mark_invalid(checkpoint.checkpoint_id, str(e))
                continue

        return None

    def _compute_hash(self, checkpoint_dict: dict[str, Any]) -> str:
        """
        计算检查点哈希（SHA-256）

        Args:
            checkpoint_dict: 检查点字典（不含 checkpoint_hash 字段）

        Returns:
            十六进制哈希值
        """
        canonical_json = json.dumps(checkpoint_dict, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
