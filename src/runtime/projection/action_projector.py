"""
Action 投影器实现（REQ-RT-004）

负责将 Action 相关事件转换为 ActionProjection 查询状态。

关键设计（REQ-RT-004 §5.5）：
- 不保存完整参数、敏感代码和凭据
- 使用 target_resource_hash 用于幂等检查
- 使用 observation_artifact_id 引用结果，不直接保存完整输出

支持的事件类型：
- ActionProposed
- ActionApproved
- ActionStarted
- ActionCompleted
- ActionFailed
- PolicyDecisionMade
"""

from datetime import datetime
from typing import Any

from .models import ActionProjection
from .projector import BaseProjector


class ActionProjector(BaseProjector[ActionProjection]):
    """Action 投影器"""

    PROJECTION_NAME = "action_projection"
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
        projection: ActionProjection | None,
        event: dict[str, Any],
    ) -> ActionProjection:
        """将事件应用到 Action 投影"""
        event_type = event["event_type"]
        payload = event["payload"]
        sequence = event["sequence"]
        event_id = event["event_id"]

        # ActionProposed: 创建新投影
        if event_type == "ActionProposed":
            return ActionProjection(
                action_id=payload["action_id"],
                task_id=payload["task_id"],
                workflow_id=payload["workflow_id"],
                worker_id=payload["worker_id"],
                step_id=payload["step_id"],
                attempt=payload.get("attempt", 1),
                type=payload["type"],
                tool_name=payload["tool_name"],
                tool_schema_version=payload["tool_schema_version"],
                target_resource_hash=payload["target_resource_hash"],
                source_revision=payload["source_revision"],
                risk_level=payload["risk_level"],
                status="PROPOSED",
                last_event_id=event_id,
                last_sequence=sequence,
                projection_version=self.PROJECTION_VERSION,
                proposed_at=datetime.fromisoformat(payload["proposed_at"]),
                updated_at=datetime.utcnow(),
            )

        if projection is None:
            raise ValueError(f"投影不存在，无法应用事件 {event_type}")

        # ActionApproved: 审批通过
        if event_type == "ActionApproved":
            projection.status = "APPROVED"
            projection.approval_id = payload.get("approval_id")

        # ActionStarted: 开始执行
        elif event_type == "ActionStarted":
            projection.status = "EXECUTING"
            projection.started_at = datetime.fromisoformat(payload["started_at"])

        # ActionCompleted: 完成
        elif event_type == "ActionCompleted":
            projection.status = "COMPLETED"
            projection.completed_at = datetime.fromisoformat(payload["completed_at"])
            projection.observation_artifact_id = payload.get("observation_artifact_id")

        # ActionFailed: 失败
        elif event_type == "ActionFailed":
            projection.status = "FAILED"
            projection.failure_ref = payload.get("failure_ref")
            projection.completed_at = datetime.fromisoformat(payload["failed_at"])

        # PolicyDecisionMade: 策略决策
        elif event_type == "PolicyDecisionMade":
            projection.policy_decision_id = payload["decision_id"]
            if payload.get("requires_approval"):
                projection.status = "WAITING_APPROVAL"

        else:
            raise ValueError(f"未知事件类型: {event_type}")

        # 更新追溯字段
        projection.last_event_id = event_id
        projection.last_sequence = sequence
        projection.updated_at = datetime.utcnow()

        return projection

    def _validate_state_invariants(
        self, projection: ActionProjection
    ) -> tuple[bool, str]:
        """
        校验 Action 状态不变量

        不变量规则：
        1. action_id 不能为空
        2. attempt >= 1
        3. 风险级别必须是合法值
        4. completed_at 只能在终态存在
        5. 不保存敏感凭据
        """
        if not projection.action_id:
            return False, "action_id 不能为空"

        if projection.attempt < 1:
            return False, f"attempt 必须 >= 1: {projection.attempt}"

        # 风险级别校验
        valid_risk_levels = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        if projection.risk_level not in valid_risk_levels:
            return False, f"无效的风险级别: {projection.risk_level}"

        # 完成时间约束
        if projection.completed_at and projection.status not in [
            "COMPLETED",
            "FAILED",
            "CANCELLED",
        ]:
            return False, f"状态 {projection.status} 不应有 completed_at"

        # 时间顺序
        if projection.started_at and projection.completed_at:
            if projection.started_at > projection.completed_at:
                return False, "started_at 不能晚于 completed_at"

        return True, "OK"

    def _save_projection_transaction(
        self,
        projection: ActionProjection,
        checkpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """在同一事务中保存投影和 Checkpoint"""
        self.storage.save_action_projection_with_checkpoint(
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

    def _load_projection(self, entity_id: str) -> ActionProjection | None:
        """加载 Action 投影"""
        return self.storage.load_action_projection(action_id=entity_id)

    def _extract_entity_id(self, event):
        """ActionProjector 适配：基类的子实体分支按 partition_key 兜底时需要回退到
        action_id 而非 workflow_id。Action 事件通常 payload 中携带 action_id（基类逻辑
        已优先处理），此处仅为兜底：当 payload 中没有 action_id 时，从 partition_key
        命名空间兜底取 action_id。
        """
        event_type = event.get("event_type", "")
        partition_key = event.get("partition_key", "")
        payload = event.get("payload", {})

        # 子实体（Observation/Artifact 等）事件 → 从 partition_key 取 action_id
        if event_type.startswith(("Observation", "Artifact")):
            if "action_id" in payload:
                return payload["action_id"]
            if ":" in partition_key:
                head = partition_key.split(":", 1)[1]
                if head.startswith(("act_", "action_")):
                    return head

        # Action 生命周期事件：走基类逻辑
        return super()._extract_entity_id(event)
