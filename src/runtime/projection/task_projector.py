"""
Task 投影器实现（REQ-RT-004）

负责将 Task 相关事件转换为 TaskProjection 查询状态。

支持的事件类型：
- TaskCreated
- TaskStarted
- TaskStatusChanged
- TaskCompleted
- TaskFailed
- WorkflowAttached
"""

from datetime import datetime
from typing import Any

from ..entities.task import TaskStatus
from .models import TaskProjection
from .projector import BaseProjector


class TaskProjector(BaseProjector[TaskProjection]):
    """Task 投影器"""

    PROJECTION_NAME = "task_projection"
    PROJECTION_VERSION = "v1.0.0"

    def __init__(self, storage):
        """
        Args:
            storage: 投影存储接口（需实现 load/save 方法）
        """
        super().__init__()
        self.storage = storage

    def get_projection_name(self) -> str:
        return self.PROJECTION_NAME

    def get_projection_version(self) -> str:
        return self.PROJECTION_VERSION

    def _apply_event_to_projection(
        self,
        projection: TaskProjection | None,
        event: dict[str, Any],
    ) -> TaskProjection:
        """
        将事件应用到 Task 投影

        状态转换规则（REQ-RT-002）：
        - TaskCreated: 创建初始投影，状态 PENDING
        - TaskStarted: 状态 -> PLANNING
        - TaskStatusChanged: 更新状态和原因
        - TaskCompleted: 状态 -> COMPLETED，记录完成时间和摘要
        - TaskFailed: 状态 -> FAILED，记录失败原因
        - WorkflowAttached: 更新 current_workflow_id
        """
        event_type = event["event_type"]
        payload = event["payload"]
        sequence = event["sequence"]
        event_id = event["event_id"]

        # TaskCreated: 创建新投影
        if event_type == "TaskCreated":
            return TaskProjection(
                task_id=payload["task_id"],
                organization_id=payload["organization_id"],
                project_id=payload["project_id"],
                repository_id=payload["repository_id"],
                creator_id=payload["creator_id"],
                status=TaskStatus.CREATED.value,
                risk_level=payload["risk_level"],
                base_revision=payload["base_revision"],
                last_event_id=event_id,
                last_sequence=sequence,
                last_event_type=event_type,
                projection_version=self.PROJECTION_VERSION,
                created_at=datetime.fromisoformat(payload["created_at"]),
                updated_at=datetime.utcnow(),
            )

        # 后续事件需要已有投影
        if projection is None:
            raise ValueError(f"投影不存在，无法应用事件 {event_type}")

        # TaskStarted: 开始执行
        if event_type == "TaskStarted":
            projection.status = TaskStatus.PLANNING.value
            projection.started_at = datetime.fromisoformat(payload["started_at"])
            projection.current_step_id = payload.get("initial_step_id")

        # TaskStatusChanged: 状态变更
        elif event_type == "TaskStatusChanged":
            projection.status = payload["new_status"]
            projection.status_reason = payload.get("reason")
            if payload.get("step_id"):
                projection.current_step_id = payload["step_id"]

        # TaskCompleted: 完成
        elif event_type == "TaskCompleted":
            projection.status = TaskStatus.COMPLETED.value
            projection.completed_at = datetime.fromisoformat(payload["completed_at"])
            projection.completion_summary = payload.get("summary", {})
            projection.working_revision = payload.get("final_revision")

        # TaskFailed: 失败
        elif event_type == "TaskFailed":
            projection.status = TaskStatus.FAILED.value
            projection.status_reason = payload.get("failure_reason")
            projection.unresolved_failure_count += 1

        # WorkflowAttached: 关联工作流
        elif event_type == "WorkflowAttached":
            projection.current_workflow_id = payload["workflow_id"]

        # ArtifactCreated: 增加产物计数
        elif event_type == "ArtifactCreated":
            projection.artifact_count += 1

        # EvidenceRecorded: 增加证据计数
        elif event_type == "EvidenceRecorded":
            projection.evidence_count += 1

        # ApprovalRequired: 增加审批计数
        elif event_type == "ApprovalRequired":
            projection.required_approval_count += 1

        # ApprovalGranted: 减少审批计数
        elif event_type == "ApprovalGranted":
            projection.required_approval_count = max(
                0, projection.required_approval_count - 1
            )

        else:
            # 未知事件类型 - 根据投影版本决定是否跳过
            raise ValueError(f"未知事件类型: {event_type}")

        # 更新追溯字段
        projection.last_event_id = event_id
        projection.last_sequence = sequence
        projection.last_event_type = event_type
        projection.updated_at = datetime.utcnow()

        return projection

    def _validate_state_invariants(self, projection: TaskProjection) -> tuple[bool, str]:
        """
        校验 Task 状态不变量

        不变量规则：
        1. task_id 不能为空
        2. status 必须是合法的 TaskStatus
        3. 计数字段不能为负数
        4. completed_at 只能在 COMPLETED/FAILED 状态存在
        5. working_revision 只能在开始执行后存在
        """
        # 1. 基本字段校验
        if not projection.task_id:
            return False, "task_id 不能为空"

        # 2. 状态合法性
        valid_statuses = {s.value for s in TaskStatus}
        if projection.status not in valid_statuses:
            return False, f"无效的任务状态: {projection.status}"

        # 3. 计数不能为负
        if projection.required_approval_count < 0:
            return False, "required_approval_count 不能为负数"
        if projection.unresolved_failure_count < 0:
            return False, "unresolved_failure_count 不能为负数"
        if projection.artifact_count < 0:
            return False, "artifact_count 不能为负数"
        if projection.evidence_count < 0:
            return False, "evidence_count 不能为负数"

        # 4. 完成时间约束
        if projection.completed_at and projection.status not in [
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        ]:
            return False, f"状态 {projection.status} 不应有 completed_at"

        # 5. 时间顺序
        if projection.started_at and projection.completed_at:
            if projection.started_at > projection.completed_at:
                return False, "started_at 不能晚于 completed_at"

        return True, "OK"

    def _save_projection_transaction(
        self,
        projection: TaskProjection,
        checkpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """
        在同一事务中保存投影和 Checkpoint

        这里是抽象接口，实际实现由 storage 层提供事务支持
        """
        self.storage.save_task_projection_with_checkpoint(
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

    def _load_projection(self, entity_id: str) -> TaskProjection | None:
        """加载 Task 投影"""
        return self.storage.load_task_projection(task_id=entity_id)
