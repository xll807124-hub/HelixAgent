"""
ProjectionCheckpoint: 投影消费者进度记录

记录某个投影消费者已安全应用到哪个事件序列，用于：
1. 投影器重启后从断点继续
2. 检测序列缺口和乱序事件
3. 监控投影延迟和健康状态

注意：这不是 REQ-RT-005 的业务恢复 Checkpoint，只是消费进度记录。
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProjectionStatus(str, Enum):
    """投影健康状态"""

    HEALTHY = "HEALTHY"  # 正常追赶事件流
    CATCHING_UP = "CATCHING_UP"  # 正在追赶积压
    BLOCKED = "BLOCKED"  # 序列缺口或引用冲突，阻塞中
    REBUILDING = "REBUILDING"  # 正在重建投影
    FAILED = "FAILED"  # 不可恢复的失败


class ProjectionCheckpoint(BaseModel):
    """
    投影消费者进度记录

    设计原则（REQ-RT-004 §5.1）：
    - last_applied_sequence 只能前进，不能回退
    - 只有事件和投影更新在同一事务成功后，才能推进
    - Checkpoint 损坏或哈希不一致时必须进入 FAILED 或 REBUILDING
    - 不包含模型上下文、工具副作用或可恢复执行的凭据
    """

    schema_version: str = Field(
        default="runtime.projection-checkpoint.v1",
        description="Checkpoint Schema 版本",
    )

    projection_name: str = Field(
        ...,
        description="投影名称，如 'task_projection', 'workflow_projection'",
        examples=["task_projection", "workflow_projection"],
    )

    projection_version: str = Field(
        ...,
        description="投影器版本，用于检测投影代码升级",
        examples=["v1.0.0"],
    )

    partition_key: str = Field(
        ...,
        description="事实流分区键，格式 'workflow:{workflow_id}'",
        examples=["workflow:wf_20241008_abc123"],
    )

    last_applied_sequence: int = Field(
        default=0,
        ge=0,
        description="最后成功应用的事件序列号（单调递增）",
    )

    last_applied_event_id: str | None = Field(
        default=None,
        description="最后应用的事件 ID（用于幂等检查）",
    )

    last_applied_event_hash: str | None = Field(
        default=None,
        description="最后应用事件的内容哈希（用于一致性校验）",
    )

    pending_gap_from: int | None = Field(
        default=None,
        description="序列缺口起始位置",
    )

    pending_gap_to: int | None = Field(
        default=None,
        description="序列缺口结束位置",
    )

    status: ProjectionStatus = Field(
        default=ProjectionStatus.HEALTHY,
        description="投影健康状态",
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="最后更新时间（UTC）",
    )

    failure_ref: str | None = Field(
        default=None,
        description="失败引用（错误ID或死信队列引用）",
    )

    # ============ 辅助方法 ============

    def can_apply_sequence(self, sequence: int) -> tuple[bool, str]:
        """
        检查是否可以应用指定序列的事件

        Returns:
            (可否应用, 原因说明)
        """
        if self.status == ProjectionStatus.FAILED:
            return False, f"投影状态为 FAILED: {self.failure_ref}"

        if self.status == ProjectionStatus.BLOCKED:
            return False, f"投影被阻塞，等待序列 {self.pending_gap_from} 补齐"

        if sequence < self.last_applied_sequence:
            return False, f"事件序列 {sequence} 小于已应用序列 {self.last_applied_sequence}"

        if sequence == self.last_applied_sequence:
            return False, f"事件序列 {sequence} 已被应用（可能是重复投递）"

        if sequence == self.last_applied_sequence + 1:
            return True, "下一个序列，可以应用"

        # 序列缺口
        return False, f"序列缺口：期望 {self.last_applied_sequence + 1}，实际 {sequence}"

    def mark_gap(self, from_seq: int, to_seq: int) -> None:
        """标记序列缺口"""
        self.pending_gap_from = from_seq
        self.pending_gap_to = to_seq
        self.status = ProjectionStatus.BLOCKED
        self.updated_at = datetime.utcnow()

    def clear_gap(self) -> None:
        """清除序列缺口标记"""
        self.pending_gap_from = None
        self.pending_gap_to = None
        if self.status == ProjectionStatus.BLOCKED:
            self.status = ProjectionStatus.HEALTHY
        self.updated_at = datetime.utcnow()

    def advance(
        self,
        sequence: int,
        event_id: str,
        event_hash: str,
    ) -> None:
        """
        推进消费进度（仅在事务成功后调用）

        Args:
            sequence: 新应用的事件序列
            event_id: 新应用的事件 ID
            event_hash: 新应用的事件内容哈希
        """
        if sequence <= self.last_applied_sequence:
            raise ValueError(
                f"不能回退序列：当前 {self.last_applied_sequence}，尝试设置 {sequence}"
            )

        self.last_applied_sequence = sequence
        self.last_applied_event_id = event_id
        self.last_applied_event_hash = event_hash
        self.updated_at = datetime.utcnow()

        # 如果填补了缺口，清除缺口标记
        if self.pending_gap_from and sequence >= self.pending_gap_to:  # type: ignore
            self.clear_gap()

    def mark_failed(self, failure_ref: str) -> None:
        """标记投影失败"""
        self.status = ProjectionStatus.FAILED
        self.failure_ref = failure_ref
        self.updated_at = datetime.utcnow()

    def mark_rebuilding(self) -> None:
        """标记正在重建"""
        self.status = ProjectionStatus.REBUILDING
        self.updated_at = datetime.utcnow()

    def calculate_lag(self, latest_sequence: int) -> int:
        """
        计算投影延迟（事件数量）

        Args:
            latest_sequence: 事实流的最新序列号

        Returns:
            延迟的事件数量
        """
        return max(0, latest_sequence - self.last_applied_sequence)
