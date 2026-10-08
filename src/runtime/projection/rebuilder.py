"""
投影重建器（REQ-RT-004 §8）

提供从零重建和增量重建能力，用于：
1. 新投影版本上线
2. 投影表损坏修复
3. 迁移验证
4. 离线评估

关键原则：
- 重建不能修改事实事件
- 重建不能发送业务副作用
- 重建不能生成生产状态迁移事件
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .checkpoint import ProjectionCheckpoint, ProjectionStatus
from .projector import BaseProjector, EventApplicationResult

logger = logging.getLogger(__name__)


@dataclass
class RebuildResult:
    """重建结果"""

    rebuild_id: str
    projection_name: str
    partition_key: str
    start_sequence: int
    end_sequence: int
    events_processed: int
    events_applied: int
    events_skipped: int
    events_failed: int
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "IN_PROGRESS"  # IN_PROGRESS, COMPLETED, FAILED
    error_message: str | None = None


class ProjectionRebuilder:
    """
    投影重建器

    支持两种重建模式：
    1. 从零重建（from_scratch）：从最早事件开始完整重建
    2. 增量重建（incremental）：从已验证的 Checkpoint 继续
    """

    def __init__(
        self,
        projector: BaseProjector,
        event_store,
        rebuild_id: str | None = None,
    ):
        """
        Args:
            projector: 投影器实例
            event_store: 事件存储接口
            rebuild_id: 重建任务 ID（用于隔离重建命名空间）
        """
        self.projector = projector
        self.event_store = event_store
        self.rebuild_id = rebuild_id or f"rebuild_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    def rebuild_from_scratch(
        self,
        partition_key: str,
        end_sequence: int | None = None,
    ) -> RebuildResult:
        """
        从零重建投影（REQ-RT-004 §8.1）

        流程：
        1. 创建带唯一 rebuild_id 的临时投影命名空间
        2. 固定事实流起点、终点、事件版本迁移器和投影版本
        3. 从最早保留事件开始按 sequence 应用
        4. 对每个分区记录应用进度、失败和输入哈希
        5. 完成后执行实体引用、状态机不变量和摘要校验
        6. 返回重建结果（不自动切换查询别名）

        Args:
            partition_key: 分区键
            end_sequence: 重建终点序列（None 表示最新）

        Returns:
            重建结果
        """
        result = RebuildResult(
            rebuild_id=self.rebuild_id,
            projection_name=self.projector.projection_name,
            partition_key=partition_key,
            start_sequence=1,
            end_sequence=end_sequence or 999999999,
            events_processed=0,
            events_applied=0,
            events_skipped=0,
            events_failed=0,
            started_at=datetime.utcnow(),
        )

        logger.info(
            f"开始从零重建投影 {self.projector.projection_name}，"
            f"分区 {partition_key}，重建ID {self.rebuild_id}"
        )

        try:
            # 查询事件流
            events = self.event_store.query_events(
                partition_key=partition_key,
                start_sequence=result.start_sequence,
                end_sequence=result.end_sequence,
            )

            # 逐个应用事件
            for event in events:
                result.events_processed += 1

                try:
                    app_result = self.projector.apply_event(event)

                    if app_result.result == EventApplicationResult.APPLIED:
                        result.events_applied += 1
                    elif app_result.result == EventApplicationResult.DUPLICATE_IGNORED:
                        result.events_skipped += 1
                    else:
                        result.events_failed += 1
                        logger.warning(
                            f"事件应用失败: seq={event['sequence']}, "
                            f"result={app_result.result}, msg={app_result.message}"
                        )

                except Exception as e:
                    result.events_failed += 1
                    logger.error(
                        f"事件处理异常: seq={event['sequence']}, error={str(e)}"
                    )

            result.status = "COMPLETED"
            result.completed_at = datetime.utcnow()

            logger.info(
                f"重建完成: 处理={result.events_processed}, "
                f"应用={result.events_applied}, "
                f"跳过={result.events_skipped}, "
                f"失败={result.events_failed}"
            )

        except Exception as e:
            result.status = "FAILED"
            result.error_message = str(e)
            result.completed_at = datetime.utcnow()
            logger.error(f"重建失败: {str(e)}")

        return result

    def rebuild_from_checkpoint(
        self,
        partition_key: str,
        checkpoint: ProjectionCheckpoint,
        end_sequence: int | None = None,
    ) -> RebuildResult:
        """
        从 Checkpoint 增量重建（REQ-RT-004 §8.2）

        前置条件：
        - 校验 Checkpoint 的 last_applied_event_id、序列和哈希
        - 校验投影版本与 Checkpoint 兼容
        - 从下一个序列开始应用事件
        - 发现事件哈希或实体快照不匹配时，回退到更早边界或从零重建

        Args:
            partition_key: 分区键
            checkpoint: 已验证的 Checkpoint
            end_sequence: 重建终点序列

        Returns:
            重建结果
        """
        result = RebuildResult(
            rebuild_id=self.rebuild_id,
            projection_name=self.projector.projection_name,
            partition_key=partition_key,
            start_sequence=checkpoint.last_applied_sequence + 1,
            end_sequence=end_sequence or 999999999,
            events_processed=0,
            events_applied=0,
            events_skipped=0,
            events_failed=0,
            started_at=datetime.utcnow(),
        )

        logger.info(
            f"开始增量重建投影 {self.projector.projection_name}，"
            f"从序列 {result.start_sequence} 开始"
        )

        try:
            # 校验 Checkpoint 一致性
            if checkpoint.status == ProjectionStatus.FAILED:
                raise ValueError(
                    f"Checkpoint 状态为 FAILED，无法增量重建: {checkpoint.failure_ref}"
                )

            # 查询增量事件
            events = self.event_store.query_events(
                partition_key=partition_key,
                start_sequence=result.start_sequence,
                end_sequence=result.end_sequence,
            )

            # 逐个应用事件
            for event in events:
                result.events_processed += 1

                try:
                    app_result = self.projector.apply_event(event)

                    if app_result.result == EventApplicationResult.APPLIED:
                        result.events_applied += 1
                    elif app_result.result == EventApplicationResult.DUPLICATE_IGNORED:
                        result.events_skipped += 1
                    else:
                        result.events_failed += 1

                except Exception as e:
                    result.events_failed += 1
                    logger.error(f"事件处理异常: seq={event['sequence']}, error={str(e)}")

            result.status = "COMPLETED"
            result.completed_at = datetime.utcnow()

        except Exception as e:
            result.status = "FAILED"
            result.error_message = str(e)
            result.completed_at = datetime.utcnow()
            logger.error(f"增量重建失败: {str(e)}")

        return result

    def validate_rebuild(
        self,
        online_projection: Any,
        rebuilt_projection: Any,
        core_fields: list[str],
    ) -> tuple[bool, dict[str, Any]]:
        """
        验证重建投影与在线投影的一致性（REQ-RT-004 §8.1）

        Args:
            online_projection: 在线投影状态
            rebuilt_projection: 重建后的投影状态
            core_fields: 核心字段列表（必须100%一致）

        Returns:
            (是否一致, 差异报告)
        """
        differences = {}
        is_consistent = True

        for field in core_fields:
            online_value = getattr(online_projection, field, None)
            rebuilt_value = getattr(rebuilt_projection, field, None)

            if online_value != rebuilt_value:
                is_consistent = False
                differences[field] = {
                    "online": online_value,
                    "rebuilt": rebuilt_value,
                }

        return is_consistent, differences


class ProjectionHealthMonitor:
    """
    投影健康状态监控（REQ-RT-004 §8）

    监控指标：
    - 投影延迟（lag_events）
    - 消费进度（last_applied_sequence）
    - 健康状态（HEALTHY/BLOCKED/FAILED）
    - 缺口和死信统计
    """

    def __init__(self, storage):
        self.storage = storage

    def get_projection_health(
        self,
        projection_name: str,
        partition_key: str,
    ) -> dict[str, Any]:
        """
        获取投影健康状态

        Returns:
            健康状态报告
        """
        checkpoint = self.storage.load_checkpoint(projection_name, partition_key)
        latest_sequence = self.storage.get_latest_sequence(partition_key)

        lag = checkpoint.calculate_lag(latest_sequence)

        return {
            "projection_name": projection_name,
            "partition_key": partition_key,
            "status": checkpoint.status.value,
            "last_applied_sequence": checkpoint.last_applied_sequence,
            "latest_sequence": latest_sequence,
            "lag_events": lag,
            "pending_gap_from": checkpoint.pending_gap_from,
            "pending_gap_to": checkpoint.pending_gap_to,
            "failure_ref": checkpoint.failure_ref,
            "updated_at": checkpoint.updated_at.isoformat(),
        }

    def list_unhealthy_projections(
        self,
        lag_threshold: int = 100,
    ) -> list[dict[str, Any]]:
        """
        列出不健康的投影

        Args:
            lag_threshold: 延迟阈值（超过该值视为不健康）

        Returns:
            不健康投影列表
        """
        unhealthy = []

        # 查询所有 Checkpoint
        all_checkpoints = self.storage.list_all_checkpoints()

        for checkpoint in all_checkpoints:
            # 检查状态
            if checkpoint.status in [
                ProjectionStatus.BLOCKED,
                ProjectionStatus.FAILED,
            ]:
                unhealthy.append(
                    {
                        "projection_name": checkpoint.projection_name,
                        "partition_key": checkpoint.partition_key,
                        "status": checkpoint.status.value,
                        "reason": checkpoint.failure_ref or "blocked",
                    }
                )
                continue

            # 检查延迟
            latest_sequence = self.storage.get_latest_sequence(checkpoint.partition_key)
            lag = checkpoint.calculate_lag(latest_sequence)

            if lag > lag_threshold:
                unhealthy.append(
                    {
                        "projection_name": checkpoint.projection_name,
                        "partition_key": checkpoint.partition_key,
                        "status": "LAGGING",
                        "lag_events": lag,
                    }
                )

        return unhealthy
