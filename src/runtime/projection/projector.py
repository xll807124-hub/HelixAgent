"""
投影器基类（REQ-RT-004 §6）

定义事件应用的通用流程和处理规则。

核心流程（REQ-RT-004 §6.1）：
1. 校验 Event Envelope 和事件版本
2. 校验租户、父级实体和引用关系
3. 查询投影消费者进度
4. 判断重复、下一序列或序列缺口
5. 按事件类型执行纯函数式状态转换
6. 校验转换后的状态机不变量
7. 在同一事务中写入投影、去重记录和消费者进度
8. 提交后发布投影更新通知
"""

import hashlib
import json
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from .checkpoint import ProjectionCheckpoint, ProjectionStatus

# ============ 事件应用结果 ============


class EventApplicationResult(str, Enum):
    """事件应用结果"""

    APPLIED = "APPLIED"  # 成功应用
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"  # 重复事件，已忽略
    GAP_DETECTED = "GAP_DETECTED"  # 检测到序列缺口
    OUT_OF_ORDER = "OUT_OF_ORDER"  # 乱序事件
    VERSION_MISMATCH = "VERSION_MISMATCH"  # 版本不兼容
    REFERENCE_CONFLICT = "REFERENCE_CONFLICT"  # 引用冲突（跨组织、父级不存在）
    STATE_MACHINE_VIOLATION = "STATE_MACHINE_VIOLATION"  # 状态机约束违反
    BLOCKED = "BLOCKED"  # 投影已被阻塞
    FAILED = "FAILED"  # 不可恢复失败


class EventApplicationResponse(BaseModel):
    """事件应用响应"""

    result: EventApplicationResult
    message: str
    applied_sequence: int | None = None
    gap_from: int | None = None
    gap_to: int | None = None
    conflict_details: dict[str, Any] | None = None


# ============ 泛型投影模型 ============

TProjection = TypeVar("TProjection", bound=BaseModel)


# ============ 投影器基类 ============


class BaseProjector(ABC, Generic[TProjection]):
    """
    投影器基类

    子类必须实现：
    1. projection_name: 投影名称
    2. projection_version: 投影版本
    3. _apply_event_to_projection: 事件到投影的纯函数转换
    4. _validate_state_invariants: 状态不变量校验
    5. _save_projection_transaction: 事务保存（投影 + Checkpoint + 去重记录）
    """

    def __init__(self) -> None:
        self.projection_name = self.get_projection_name()
        self.projection_version = self.get_projection_version()

    # ============ 抽象方法（子类必须实现） ============

    @abstractmethod
    def get_projection_name(self) -> str:
        """返回投影名称"""
        pass

    @abstractmethod
    def get_projection_version(self) -> str:
        """返回投影版本"""
        pass

    @abstractmethod
    def _apply_event_to_projection(
        self,
        projection: TProjection | None,
        event: dict[str, Any],
    ) -> TProjection:
        """
        将事件应用到投影（纯函数）

        Args:
            projection: 当前投影状态（首次为 None）
            event: 规范化后的事件数据

        Returns:
            更新后的投影状态

        Raises:
            ValueError: 事件类型未知或不支持
            RuntimeError: 状态转换逻辑错误
        """
        pass

    @abstractmethod
    def _validate_state_invariants(self, projection: TProjection) -> tuple[bool, str]:
        """
        校验状态不变量

        Args:
            projection: 待校验的投影状态

        Returns:
            (是否有效, 错误信息)
        """
        pass

    @abstractmethod
    def _save_projection_transaction(
        self,
        projection: TProjection,
        checkpoint: ProjectionCheckpoint,
        event_id: str,
        event_hash: str,
    ) -> None:
        """
        在同一事务中保存投影、Checkpoint 和去重记录

        Args:
            projection: 更新后的投影状态
            checkpoint: 更新后的 Checkpoint
            event_id: 事件 ID（用于去重）
            event_hash: 事件哈希（用于一致性校验）

        Raises:
            Exception: 事务失败时抛出异常
        """
        pass

    @abstractmethod
    def _load_checkpoint(self, partition_key: str) -> ProjectionCheckpoint:
        """
        加载指定分区的 Checkpoint

        Args:
            partition_key: 分区键（如 'workflow:wf_xxx'）

        Returns:
            Checkpoint（若不存在则返回初始状态）
        """
        pass

    @abstractmethod
    def _load_projection(self, entity_id: str) -> TProjection | None:
        """
        加载指定实体的当前投影

        Args:
            entity_id: 实体 ID（task_id/workflow_id/worker_id/action_id）

        Returns:
            投影状态（若不存在则返回 None）
        """
        pass

    # ============ 通用处理流程 ============

    def apply_event(
        self,
        event: dict[str, Any],
    ) -> EventApplicationResponse:
        """
        应用事件到投影（REQ-RT-004 §6.1 通用处理流程）

        流程：
        1. 校验事件格式和版本
        2. 加载 Checkpoint
        3. 判断重复/下一序列/缺口
        4. 应用事件转换
        5. 校验状态不变量
        6. 事务保存
        7. 返回结果
        """
        try:
            # Step 1: 校验事件基本格式
            validation_result = self._validate_event_envelope(event)
            if not validation_result[0]:
                return EventApplicationResponse(
                    result=EventApplicationResult.FAILED,
                    message=f"事件格式校验失败: {validation_result[1]}",
                )

            event_id = event["event_id"]
            sequence = event["sequence"]
            partition_key = event["partition_key"]
            event_type = event["event_type"]

            # Step 2: 加载 Checkpoint
            checkpoint = self._load_checkpoint(partition_key)

            # 检查投影状态
            if checkpoint.status == ProjectionStatus.FAILED:
                return EventApplicationResponse(
                    result=EventApplicationResult.FAILED,
                    message=f"投影已失败: {checkpoint.failure_ref}",
                )

            # Step 3: 判断事件处理策略
            can_apply, reason = checkpoint.can_apply_sequence(sequence)

            # 处理重复事件（REQ-RT-004 §6.2）
            if sequence <= checkpoint.last_applied_sequence:
                if event_id == checkpoint.last_applied_event_id:
                    event_hash = self._compute_event_hash(event)
                    if event_hash == checkpoint.last_applied_event_hash:
                        return EventApplicationResponse(
                            result=EventApplicationResult.DUPLICATE_IGNORED,
                            message=f"重复事件已忽略: {event_id}",
                            applied_sequence=checkpoint.last_applied_sequence,
                        )
                    else:
                        # 相同 event_id 但内容不同 - 严重冲突
                        return EventApplicationResponse(
                            result=EventApplicationResult.REFERENCE_CONFLICT,
                            message=f"事件 ID {event_id} 内容哈希冲突",
                            conflict_details={
                                "expected_hash": checkpoint.last_applied_event_hash,
                                "actual_hash": event_hash,
                            },
                        )

            # 处理序列缺口（REQ-RT-004 §6.4）
            if not can_apply and "缺口" in reason:
                expected_seq = checkpoint.last_applied_sequence + 1
                checkpoint.mark_gap(expected_seq, sequence - 1)
                # 这里不保存 checkpoint，等待缺口补齐
                return EventApplicationResponse(
                    result=EventApplicationResult.GAP_DETECTED,
                    message=reason,
                    gap_from=expected_seq,
                    gap_to=sequence - 1,
                )

            # 处理已阻塞状态
            if checkpoint.status == ProjectionStatus.BLOCKED:
                # 检查是否填补了缺口
                if (
                    checkpoint.pending_gap_from
                    and sequence == checkpoint.pending_gap_from
                ):
                    # 可以继续处理，填补缺口
                    pass
                else:
                    # 兼容性补丁：BLOCKED 状态下若新事件的 sequence 落在已应用序列的下一个
                    # （即 pending_gap_from 已 < sequence，且 gap 段实际上已被新事件跨越），
                    # 自动清除缺口并继续处理。否则会陷入 e2 应用后 e3/e4 永远被 BLOCKED
                    # 拒绝的卡死状态（advance() 内 clear_gap 条件 sequence>=pending_gap_to
                    # 在缺口 >1 段时不立即触发）。
                    if (
                        checkpoint.pending_gap_from
                        and sequence > checkpoint.pending_gap_from
                    ):
                        # 新事件序列大于 pending_gap_from，意味着 gap 段已被越过。
                        # 清掉缺口，让本事件进入正常处理；下一个序列检查会继续判
                        # 缺口是否真的补齐。
                        checkpoint.clear_gap()
                    else:
                        return EventApplicationResponse(
                            result=EventApplicationResult.BLOCKED,
                            message=f"投影已阻塞，等待序列 {checkpoint.pending_gap_from} 补齐",
                        )

            # Step 4: 加载当前投影
            entity_id = self._extract_entity_id(event)
            current_projection = self._load_projection(entity_id)

            # Step 5: 应用事件转换（纯函数）
            try:
                updated_projection = self._apply_event_to_projection(
                    current_projection, event
                )
            except ValueError as e:
                return EventApplicationResponse(
                    result=EventApplicationResult.VERSION_MISMATCH,
                    message=f"事件应用失败: {str(e)}",
                )

            # Step 6: 校验状态不变量
            is_valid, error_msg = self._validate_state_invariants(updated_projection)
            if not is_valid:
                return EventApplicationResponse(
                    result=EventApplicationResult.STATE_MACHINE_VIOLATION,
                    message=f"状态不变量违反: {error_msg}",
                )

            # Step 7: 事务保存
            event_hash = self._compute_event_hash(event)
            checkpoint.advance(sequence, event_id, event_hash)

            self._save_projection_transaction(
                projection=updated_projection,
                checkpoint=checkpoint,
                event_id=event_id,
                event_hash=event_hash,
            )

            # Step 8: 返回成功结果
            return EventApplicationResponse(
                result=EventApplicationResult.APPLIED,
                message=f"事件 {event_type} 已应用到序列 {sequence}",
                applied_sequence=sequence,
            )

        except Exception as e:
            # 不可恢复失败
            return EventApplicationResponse(
                result=EventApplicationResult.FAILED,
                message=f"投影应用失败: {str(e)}",
            )

    # ============ 辅助方法 ============

    def _validate_event_envelope(self, event: dict[str, Any]) -> tuple[bool, str]:
        """
        校验事件 Envelope 格式（REQ-RT-003）

        必需字段：
        - event_id
        - event_type
        - event_type_version
        - sequence
        - partition_key
        - occurred_at
        - payload
        """
        required_fields = [
            "event_id",
            "event_type",
            "event_type_version",
            "sequence",
            "partition_key",
            "occurred_at",
            "payload",
        ]

        for field in required_fields:
            if field not in event:
                return False, f"缺少必需字段: {field}"

        # 校验序列号
        if not isinstance(event["sequence"], int) or event["sequence"] < 0:
            return False, f"无效的序列号: {event['sequence']}"

        return True, "OK"

    def _compute_event_hash(self, event: dict[str, Any]) -> str:
        """
        计算事件内容哈希（用于幂等检查）

        使用规范化 JSON + SHA-256
        """
        # 排除时间戳等非关键字段
        hash_fields = {
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "event_type_version": event["event_type_version"],
            "sequence": event["sequence"],
            "partition_key": event["partition_key"],
            "payload": event["payload"],
        }

        canonical_json = json.dumps(hash_fields, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def _extract_entity_id(self, event: dict[str, Any]) -> str:
        """
        从事件中提取实体 ID

        根据事件类型判断：
        - TaskCreated -> task_id
        - WorkflowStarted -> workflow_id
        - WorkerStarted -> worker_id
        - ActionProposed -> action_id

        注意：不同投影器对 Worker 事件有不同的实体 ID 期望：
        - WorkerProjector 自身用 worker_id 加载 WorkerProjection（聚合根是 worker）
        - WorkflowProjector 用 worker_id 的子事件来汇聚父 Workflow 计数（聚合根是 workflow_id），
          该投影器在子类中重写 _extract_entity_id 来适配。

        本基类规则只覆盖 worker_id 走 WorkerProjector 的场景；workflow_id 路径由
        WorkflowProjector 的子类重写处理。
        """
        payload = event.get("payload", {})
        event_type = event.get("event_type", "")
        partition_key = event.get("partition_key", "")

        # Worker 生命周期事件如果走到基类（即不是 WorkflowProjector 子类），按 worker_id
        # 解析（WorkerProjector 的常规路径）。WorkflowProjector 子类应当重写本方法。
        if event_type.startswith("Worker") and "worker_id" in payload:
            return payload["worker_id"]

        # 优先从 payload 提取（按业务字段优先级）
        if "task_id" in payload:
            return payload["task_id"]
        elif "workflow_id" in payload:
            return payload["workflow_id"]
        elif "worker_id" in payload:
            return payload["worker_id"]
        elif "action_id" in payload:
            return payload["action_id"]
        elif "entity_id" in payload:
            # 通用测试/最小投影场景：业务实体的实体 ID（如 SimpleProjection 单元测试）。
            return payload["entity_id"]

        # 兜底：使用 partition_key
        if ":" in partition_key:
            return partition_key.split(":", 1)[1]

        raise ValueError(f"无法从事件中提取实体 ID: {event}")

    # ============ 批量处理 ============

    def apply_events_batch(
        self,
        events: list[dict[str, Any]],
    ) -> list[EventApplicationResponse]:
        """
        批量应用事件（按序列号排序后逐个处理）

        Args:
            events: 事件列表

        Returns:
            应用结果列表
        """
        # 按序列号排序
        sorted_events = sorted(events, key=lambda e: e["sequence"])

        results = []
        for event in sorted_events:
            result = self.apply_event(event)
            results.append(result)

            # 如果遇到不可恢复错误，停止批处理
            if result.result in [
                EventApplicationResult.FAILED,
                EventApplicationResult.REFERENCE_CONFLICT,
            ]:
                break

        return results
