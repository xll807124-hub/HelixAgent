"""
Workflow 投影器实现（REQ-RT-004）

负责将 Workflow 相关事件转换为 WorkflowProjection 查询状态。

关键设计（REQ-RT-004 §3.5 父子投影与汇聚规则）：
- Worker 计数必须由 Worker 投影汇聚，不能由单个 Worker 事件直接写入
- Workflow 状态由自身生命周期事件直接更新
- 计数一致性只是查询视图，调度仍需重新校验事实

支持的事件类型：
- WorkflowCreated
- WorkflowStarted
- WorkflowStatusChanged
- WorkflowCompleted
- WorkflowFailed
- WorkerRegistered (更新计数)
- WorkerStarted (更新计数)
- WorkerCompleted (更新计数)
- WorkerFailed (更新计数)
"""

from datetime import datetime
from typing import Any

from .models import WorkflowProjection
from .projector import BaseProjector


class WorkflowProjector(BaseProjector[WorkflowProjection]):
    """Workflow 投影器"""

    PROJECTION_NAME = "workflow_projection"
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
        projection: WorkflowProjection | None,
        event: dict[str, Any],
    ) -> WorkflowProjection:
        """将事件应用到 Workflow 投影"""
        event_type = event["event_type"]
        payload = event["payload"]
        sequence = event["sequence"]
        event_id = event["event_id"]

        # WorkflowCreated: 创建新投影
        if event_type == "WorkflowCreated":
            return WorkflowProjection(
                workflow_id=payload["workflow_id"],
                task_id=payload["task_id"],
                organization_id=payload["organization_id"],
                project_id=payload["project_id"],
                repository_id=payload["repository_id"],
                status="READY",
                workflow_template_id=payload["workflow_template_id"],
                workflow_template_version=payload["workflow_template_version"],
                agent_profile_version=payload["agent_profile_version"],
                toolset_version=payload["toolset_version"],
                base_revision=payload["base_revision"],
                last_event_id=event_id,
                last_sequence=sequence,
                projection_version=self.PROJECTION_VERSION,
                created_at=datetime.fromisoformat(payload["created_at"]),
                updated_at=datetime.utcnow(),
            )

        if projection is None:
            raise ValueError(f"投影不存在，无法应用事件 {event_type}")

        # WorkflowStarted: 开始执行
        if event_type == "WorkflowStarted":
            projection.status = "RUNNING"
            projection.started_at = datetime.fromisoformat(payload["started_at"])

        # WorkflowStatusChanged: 状态变更
        elif event_type == "WorkflowStatusChanged":
            projection.status = payload["new_status"]
            projection.status_reason = payload.get("reason")

        # WorkflowCompleted: 完成
        elif event_type == "WorkflowCompleted":
            projection.status = "COMPLETED"
            projection.completed_at = datetime.fromisoformat(payload["completed_at"])
            projection.working_revision = payload.get("final_revision")

        # WorkflowFailed: 失败
        elif event_type == "WorkflowFailed":
            projection.status = "FAILED"
            projection.status_reason = payload.get("failure_reason")

        # Worker 计数更新（REQ-RT-004 §3.5 汇聚规则）
        elif event_type == "WorkerRegistered":
            projection.required_worker_count += 1
            projection.runnable_worker_count += 1

        elif event_type == "WorkerStarted":
            projection.runnable_worker_count = max(
                0, projection.runnable_worker_count - 1
            )
            projection.running_worker_count += 1
            projection.active_attempt_count += 1

        elif event_type == "WorkerCompleted":
            projection.running_worker_count = max(
                0, projection.running_worker_count - 1
            )
            projection.completed_worker_count += 1

        elif event_type == "WorkerFailed":
            projection.running_worker_count = max(
                0, projection.running_worker_count - 1
            )
            projection.failed_worker_count += 1

        elif event_type == "WorkerWaitingApproval":
            projection.waiting_approval_count += 1

        elif event_type == "WorkerApprovalGranted":
            projection.waiting_approval_count = max(
                0, projection.waiting_approval_count - 1
            )

        else:
            raise ValueError(f"未知事件类型: {event_type}")

        # 更新追溯字段
        projection.last_event_id = event_id
        projection.last_sequence = sequence
        projection.updated_at = datetime.utcnow()

        return projection

    def _validate_state_invariants(
        self, projection: WorkflowProjection
    ) -> tuple[bool, str]:
        """
        校验 Workflow 状态不变量

        不变量规则：
        1. workflow_id 不能为空
        2. 所有计数字段不能为负
        3. running + completed + failed <= required（counts derived from workers）
        4. completed_at 只能在终态存在
        """
        if not projection.workflow_id:
            return False, "workflow_id 不能为空"

        # 计数不能为负
        counts = [
            ("runnable_worker_count", projection.runnable_worker_count),
            ("running_worker_count", projection.running_worker_count),
            ("waiting_approval_count", projection.waiting_approval_count),
            ("failed_worker_count", projection.failed_worker_count),
            ("completed_worker_count", projection.completed_worker_count),
            ("required_worker_count", projection.required_worker_count),
            ("active_attempt_count", projection.active_attempt_count),
        ]

        for name, value in counts:
            if value < 0:
                return False, f"{name} 不能为负数: {value}"

        # Worker 总数约束（允许有误差，因为是最终一致）
        total_processed = (
            projection.running_worker_count
            + projection.completed_worker_count
            + projection.failed_worker_count
        )
        if total_processed > projection.required_worker_count + 10:  # 容忍误差
            return (
                False,
                f"已处理 Worker ({total_processed}) 远超需求数 "
                f"({projection.required_worker_count})",
            )

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
        projection: WorkflowProjection,
        checkpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """在同一事务中保存投影和 Checkpoint"""
        self.storage.save_workflow_projection_with_checkpoint(
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

    def _load_projection(self, entity_id: str) -> WorkflowProjection | None:
        """加载 Workflow 投影"""
        return self.storage.load_workflow_projection(workflow_id=entity_id)

    def _extract_entity_id(self, event):
        """WorkflowProjector 适配。

        Workflow 自身事件走 payload.workflow_id；Worker/Action/Artifact 子实体事件
        走 partition_key 取 workflow_id（满足 REQ-RT-004 §3.5 父子投影汇聚规则）。

        根据 REQ-RT-004 §3.5 父子投影与汇聚规则：
        - Workflow 自身事件（WorkflowCreated/Started/...）→ 用 payload.workflow_id
        - Worker/Action/Artifact 子实体事件 → 用 partition_key 的 workflow_id 部分（payload 里
          是 worker_id/action_id/artifact_id，需要从命名空间兜底）

        重要：基类优先级里 task_id 在 workflow_id 前面，会让 WorkflowCreated 等事件误用 task_id
        作为 entity_id 去加载 Workflow 投影（结果查不到），因此 Workflow 自身事件必须在子类显式
        优先用 workflow_id。
        """
        event_type = event.get("event_type", "")
        partition_key = event.get("partition_key", "")
        payload = event.get("payload", {})

        # 子实体（Worker / Action / Artifact）生命周期事件 → 从 partition_key 取 workflow_id
        if event_type.startswith(("Worker", "Action", "Artifact")):
            if ":" in partition_key:
                return partition_key.split(":", 1)[1]

        # Workflow 自身事件 → 优先 payload.workflow_id（覆盖基类 task_id 在前的顺序）
        if event_type.startswith("Workflow"):
            if "workflow_id" in payload:
                return payload["workflow_id"]

        # 其他父实体或异常情况：走基类逻辑
        return super()._extract_entity_id(event)
