"""
Worker 投影器实现（REQ-RT-004）

负责将 Worker 相关事件转换为 WorkerProjection 查询状态。

支持的事件类型：
- WorkerCreated
- WorkerStarted
- WorkerStatusChanged
- WorkerCompleted
- WorkerFailed
- ActionProposed (更新计数)
- ActionStarted (更新计数)
- ActionCompleted (更新计数)
- ActionFailed (更新计数)
"""

from datetime import datetime
from typing import Any

from .models import WorkerProjection
from .projector import BaseProjector


class WorkerProjector(BaseProjector[WorkerProjection]):
    """Worker 投影器"""

    PROJECTION_NAME = "worker_projection"
    PROJECTION_VERSION = "v1.0.0"

    def __init__(self, storage):
        super().__init__()
        self.storage = storage

    def get_projection_name(self) -> str:
        return self.PROJECTION_NAME

    def get_projection_version(self) -> str:
        return self.PROJECTION_VERSION

    def _apply_event_to_projection(
        self,
        projection: WorkerProjection | None,
        event: dict[str, Any],
    ) -> WorkerProjection:
        """将事件应用到 Worker 投影"""
        event_type = event["event_type"]
        payload = event["payload"]
        sequence = event["sequence"]
        event_id = event["event_id"]

        # WorkerCreated: 创建新投影
        if event_type == "WorkerCreated":
            return WorkerProjection(
                worker_id=payload["worker_id"],
                workflow_id=payload["workflow_id"],
                task_id=payload["task_id"],
                step_id=payload["step_id"],
                worker_type=payload["worker_type"],
                attempt=payload.get("attempt", 1),
                status="READY",
                source_revision=payload["source_revision"],
                last_event_id=event_id,
                last_sequence=sequence,
                projection_version=self.PROJECTION_VERSION,
                created_at=datetime.fromisoformat(payload["created_at"]),
                updated_at=datetime.utcnow(),
            )

        if projection is None:
            raise ValueError(f"投影不存在，无法应用事件 {event_type}")

        # WorkerStarted: 开始执行
        if event_type == "WorkerStarted":
            projection.status = "RUNNING"
            projection.started_at = datetime.fromisoformat(payload["started_at"])

        # WorkerStatusChanged: 状态变更
        elif event_type == "WorkerStatusChanged":
            projection.status = payload["new_status"]
            projection.status_reason = payload.get("reason")

        # WorkerCompleted: 完成
        elif event_type == "WorkerCompleted":
            projection.status = "COMPLETED"
            projection.completed_at = datetime.fromisoformat(payload["completed_at"])
            # 更新输出产物
            if "output_artifact_ids" in payload:
                projection.output_artifact_ids = payload["output_artifact_ids"]

        # WorkerFailed: 失败
        elif event_type == "WorkerFailed":
            projection.status = "FAILED"
            projection.status_reason = payload.get("failure_reason")

        # Action 计数更新
        elif event_type == "ActionProposed":
            projection.waiting_action_count += 1

        elif event_type == "ActionStarted":
            projection.waiting_action_count = max(0, projection.waiting_action_count - 1)
            projection.active_action_count += 1
            projection.last_action_id = payload["action_id"]

        elif event_type == "ActionCompleted":
            projection.active_action_count = max(0, projection.active_action_count - 1)

        elif event_type == "ActionFailed":
            projection.active_action_count = max(0, projection.active_action_count - 1)
            projection.failed_action_count += 1

        # 输入产物关联
        elif event_type == "ArtifactConsumed":
            artifact_id = payload["artifact_id"]
            if artifact_id not in projection.input_artifact_ids:
                projection.input_artifact_ids.append(artifact_id)

        else:
            raise ValueError(f"未知事件类型: {event_type}")

        # 更新追溯字段
        projection.last_event_id = event_id
        projection.last_sequence = sequence
        projection.updated_at = datetime.utcnow()

        return projection

    def _validate_state_invariants(
        self, projection: WorkerProjection
    ) -> tuple[bool, str]:
        """
        校验 Worker 状态不变量

        不变量规则：
        1. worker_id 不能为空
        2. attempt >= 1
        3. 所有计数字段不能为负
        4. completed_at 只能在终态存在
        """
        if not projection.worker_id:
            return False, "worker_id 不能为空"

        if projection.attempt < 1:
            return False, f"attempt 必须 >= 1: {projection.attempt}"

        # 计数不能为负
        if projection.active_action_count < 0:
            return False, "active_action_count 不能为负数"
        if projection.waiting_action_count < 0:
            return False, "waiting_action_count 不能为负数"
        if projection.failed_action_count < 0:
            return False, "failed_action_count 不能为负数"

        # 完成时间约束
        if projection.completed_at and projection.status not in [
            "COMPLETED",
            "FAILED",
            "CANCELLED",
        ]:
            return False, f"状态 {projection.status} 不应有 completed_at"

        return True, "OK"

    def _save_projection_transaction(
        self,
        projection: WorkerProjection,
        checkpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """在同一事务中保存投影和 Checkpoint"""
        self.storage.save_worker_projection_with_checkpoint(
            projection=projection,
            checkpoint=checkpoint,
            event_id=event_id,
            event_hash=event_hash,
        )

    def _load_checkpoint(self, partition_key: str):
        """加载 Checkpoint"""
        return self.storage.load_checkpoint(
            projection_name=self.PROJECTION_NAME,
            partition_key=partition_key,
        )

    def _load_projection(self, entity_id: str) -> WorkerProjection | None:
        """加载 Worker 投影"""
        return self.storage.load_worker_projection(worker_id=entity_id)

    def _extract_entity_id(self, event):
        """WorkerProjector 适配：Action/Artifact 子实体事件取 partition_key 的 worker_id

        Worker 生命周期事件（WorkerCreated/Started/Completed/Failed/...）的 entity_id
        是 worker_id（在基类逻辑已支持）。Action/ArtifactConsumed 等子实体事件携带
        worker_id，但 partition_key 形如 "workflow:wf_xxx"——必须从 partition_key 兜底
        时按 worker: 命名空间解析，避免错误使用 wf_xxx 作为 entity_id。

        实际测试 partition_key 命名以 caller 提供的为准：当 caller 用 "worker:wk_xxx"
        时，分号后的 wk_xxx 就是 worker_id。
        """
        event_type = event.get("event_type", "")
        partition_key = event.get("partition_key", "")
        payload = event.get("payload", {})

        # Action/Artifact 子实体事件 → 从 partition_key 兜底取 worker_id
        if event_type.startswith(("Action", "Artifact")):
            if "worker_id" in payload:
                return payload["worker_id"]
            if ":" in partition_key:
                # 兼容 worker:wk_xxx 与 workflow:wf_xxx 两种命名
                head = partition_key.split(":", 1)[1]
                if head.startswith("wk_") or head.startswith("worker_"):
                    return head

        # Worker 生命周期事件：走基类逻辑（payload 里有 worker_id）
        return super()._extract_entity_id(event)
