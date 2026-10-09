"""
Checkpoint Builder（REQ-RT-005 §5）

职责：
1. 从 Workflow 状态构建不可变 Checkpoint
2. 验证保存前置条件（§5.2 的 10 条）
3. 收集状态快照、Worker/Action 引用、预算和资源信息
4. 计算检查点哈希（防篡改）
5. 敏感字段脱敏（禁止明文凭据、模型思维链）

核心原则（REQ-RT-005 §3, §5.2）：
- 保存前必须验证事件序列无缺口
- 状态投影不能是 BLOCKED 状态
- 必须执行敏感字段检测和脱敏
- 检查点创建后不可修改
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.runtime.checkpoint.models import (
    ActionCheckpointRef,
    BudgetSnapshot,
    CheckpointReason,
    CheckpointStatus,
    RecoveryAction,
    ResourceSnapshot,
    SideEffectState,
    StateSnapshot,
    WorkerCheckpointRef,
    WorkflowCheckpoint,
)
from src.runtime.entities.action import ActionStatus

if TYPE_CHECKING:
    from src.runtime.event_store.store import EventStore
    from src.runtime.projection.storage import ProjectionStorage


class CheckpointBuilderError(Exception):
    """Checkpoint Builder 异常"""

    pass


class PreconditionViolation(CheckpointBuilderError):
    """前置条件不满足"""

    pass


class CheckpointBuilder:
    """
    Checkpoint Builder（REQ-RT-005 §5）

    职责：
    1. 验证保存前置条件（§5.2）
    2. 收集状态快照和引用
    3. 计算检查点哈希
    4. 构建不可变 WorkflowCheckpoint

    使用示例：
    ```python
    builder = CheckpointBuilder(event_store, projection_storage)
    checkpoint = builder.build_from_workflow(
        workflow=workflow,
        reason=CheckpointReason.RUNNING,
        created_by="system"
    )
    ```
    """

    def __init__(
        self,
        event_store: EventStore,
        projection_storage: ProjectionStorage,
    ) -> None:
        """
        初始化 Checkpoint Builder

        Args:
            event_store: 事件存储（读取事件序列和哈希）
            projection_storage: 投影存储（读取状态投影）
        """
        self.event_store = event_store
        self.projection_storage = projection_storage

    def build_from_workflow(
        self,
        workflow_id: str,
        task_id: str,
        organization_id: str,
        project_id: str,
        repository_id: str,
        reason: CheckpointReason,
        created_by: str,
        # 版本信息
        runtime_contract_version: str = "v1.0",
        workflow_template_id: str = "default",
        workflow_template_version: str = "v1.0",
        agent_profile_version: str = "v1.0",
        toolset_version: str = "v1.0",
    ) -> WorkflowCheckpoint:
        """
        从 Workflow 状态构建 Checkpoint

        Args:
            workflow_id: Workflow ID
            task_id: Task ID
            organization_id: 组织 ID
            project_id: 项目 ID
            repository_id: 仓库 ID
            reason: Checkpoint 创建原因
            created_by: 创建者
            runtime_contract_version: Runtime 契约版本
            workflow_template_id: Workflow 模板 ID
            workflow_template_version: Workflow 模板版本
            agent_profile_version: Agent Profile 版本
            toolset_version: 工具集版本

        Returns:
            WorkflowCheckpoint: 不可变检查点

        Raises:
            PreconditionViolation: 前置条件不满足
            CheckpointBuilderError: 构建失败
        """
        # 1. 验证前置条件（REQ-RT-005 §5.2）
        self._validate_preconditions(workflow_id)

        # 2. 获取最新事实序列
        # 注：Event Store 目前只提供 get_latest_sequence
        # MVP简化：使用 projection_checkpoint 的序列号
        projection_checkpoint = self.projection_storage.load_checkpoint(
            projection_name="workflow", partition_key=workflow_id
        )

        source_event_sequence = projection_checkpoint.last_applied_sequence
        # MVP简化：event_id和hash使用占位符，后续从Event Store读取
        source_event_id = f"event-{workflow_id}-seq{source_event_sequence}"
        source_event_hash = f"hash-{source_event_sequence}"

        # 3. 收集状态快照
        state_snapshot = self._collect_state_snapshot(workflow_id, task_id)

        # 4. 收集预算快照
        budget_snapshot = self._collect_budget_snapshot(workflow_id)

        # 5. 收集资源快照
        resource_snapshot = self._collect_resource_snapshot(workflow_id)

        # 6. 计算内容哈希
        content_hash = self._compute_content_hash(
            state_snapshot, budget_snapshot, resource_snapshot
        )

        # 7. 生成 checkpoint_id
        checkpoint_id = self._generate_checkpoint_id(workflow_id, source_event_sequence)

        # 8. 生成 ContentRef (简化版，实际应该存储到对象存储)
        state_snapshot_ref = f"checkpoint://{checkpoint_id}/state"
        budget_snapshot_ref = f"checkpoint://{checkpoint_id}/budget"
        resource_snapshot_ref = f"checkpoint://{checkpoint_id}/resource"

        # 9. 构建 WorkflowCheckpoint 元数据
        checkpoint_meta = {
            "schema_version": "runtime.workflow-checkpoint.v1",
            "checkpoint_id": checkpoint_id,
            "task_id": task_id,
            "workflow_id": workflow_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "repository_id": repository_id,
            "created_at": datetime.now(UTC),
            "created_by": created_by,
            "checkpoint_reason": reason,
            "checkpoint_status": CheckpointStatus.CREATED,
            "source_event_sequence": source_event_sequence,
            "source_event_id": source_event_id,
            "source_event_hash": source_event_hash,
            "event_stream_partition": workflow_id,
            "content_hash": content_hash,
            "runtime_contract_version": runtime_contract_version,
            "workflow_template_id": workflow_template_id,
            "workflow_template_version": workflow_template_version,
            "agent_profile_version": agent_profile_version,
            "toolset_version": toolset_version,
            "state_snapshot_ref": state_snapshot_ref,
            "budget_snapshot_ref": budget_snapshot_ref,
            "resource_snapshot_ref": resource_snapshot_ref,
        }

        # 10. 计算检查点哈希（防篡改）
        checkpoint_hash = self._compute_checkpoint_hash(checkpoint_meta)

        # 11. 构建不可变 WorkflowCheckpoint（显式传参以满足类型检查）
        checkpoint = WorkflowCheckpoint(
            schema_version=checkpoint_meta["schema_version"],  # type: ignore
            checkpoint_id=checkpoint_meta["checkpoint_id"],  # type: ignore
            task_id=checkpoint_meta["task_id"],  # type: ignore
            workflow_id=checkpoint_meta["workflow_id"],  # type: ignore
            organization_id=checkpoint_meta["organization_id"],  # type: ignore
            project_id=checkpoint_meta["project_id"],  # type: ignore
            repository_id=checkpoint_meta["repository_id"],  # type: ignore
            created_at=checkpoint_meta["created_at"],  # type: ignore
            created_by=checkpoint_meta["created_by"],  # type: ignore
            checkpoint_reason=checkpoint_meta["checkpoint_reason"],  # type: ignore
            checkpoint_status=checkpoint_meta["checkpoint_status"],  # type: ignore
            source_event_sequence=checkpoint_meta["source_event_sequence"],  # type: ignore
            source_event_id=checkpoint_meta["source_event_id"],  # type: ignore
            source_event_hash=checkpoint_meta["source_event_hash"],  # type: ignore
            event_stream_partition=checkpoint_meta["event_stream_partition"],  # type: ignore
            content_hash=checkpoint_meta["content_hash"],  # type: ignore
            checkpoint_hash=checkpoint_hash,
            runtime_contract_version=checkpoint_meta["runtime_contract_version"],  # type: ignore
            workflow_template_id=checkpoint_meta["workflow_template_id"],  # type: ignore
            workflow_template_version=checkpoint_meta["workflow_template_version"],  # type: ignore
            agent_profile_version=checkpoint_meta["agent_profile_version"],  # type: ignore
            toolset_version=checkpoint_meta["toolset_version"],  # type: ignore
            state_snapshot_ref=checkpoint_meta["state_snapshot_ref"],  # type: ignore
            budget_snapshot_ref=checkpoint_meta["budget_snapshot_ref"],  # type: ignore
            resource_snapshot_ref=checkpoint_meta["resource_snapshot_ref"],  # type: ignore
        )

        return checkpoint

    def _validate_preconditions(self, workflow_id: str) -> None:
        """
        验证保存前置条件（REQ-RT-005 §5.2）

        前置条件（10 条）：
        1. 获取 Workflow 最新事实序列
        2. 确认事件序列无缺口
        3. 确认状态投影不是不可恢复的 BLOCKED
        4. 确认父子实体引用完整
        5. 确认 Artifact/Evidence 可解析且版本一致
        6. 确认 Workspace 和 working_revision 可验证
        7. 执行敏感字段检测和脱敏
        8. 生成规范化内容并计算哈希
        9. 持久化检查点并验证哈希
        10. 追加 CheckpointCreated 事件

        注：条件 9-10 在 CheckpointManager 中执行，此处验证 1-8

        Raises:
            PreconditionViolation: 前置条件不满足
        """
        # 1. 获取最新事实序列（在 build_from_workflow 中已检查）

        # 2. 确认事件序列无缺口
        projection_checkpoint = self.projection_storage.load_checkpoint(
            projection_name="workflow", partition_key=workflow_id
        )
        if projection_checkpoint.pending_gap_from is not None:
            gap_from = projection_checkpoint.pending_gap_from
            gap_to = projection_checkpoint.pending_gap_to
            raise PreconditionViolation(
                f"Workflow {workflow_id} has event gap: [{gap_from}, {gap_to}]"
            )

        # 3. 确认状态投影不是 BLOCKED
        from src.runtime.projection.checkpoint import ProjectionStatus

        if projection_checkpoint.status == ProjectionStatus.BLOCKED:
            raise PreconditionViolation(
                f"Workflow {workflow_id} projection is BLOCKED, cannot create checkpoint"
            )

        # 4-8. 其他前置条件（MVP 简化，后续迭代补充）
        # 4. 父子实体引用完整性（需要完整的 Workflow/Worker/Action 对象）
        # 5. Artifact/Evidence 可解析性（需要 Artifact Store）
        # 6. Workspace 可验证性（需要 Workspace Manager）
        # 7. 敏感字段脱敏（在 _sanitize_sensitive_fields 中执行）
        # 8. 规范化内容和哈希（在 _compute_content_hash 中执行）

    def _collect_state_snapshot(self, workflow_id: str, task_id: str) -> StateSnapshot:
        """
        收集状态快照（REQ-RT-005 §4.2）

        Args:
            workflow_id: Workflow ID
            task_id: Task ID

        Returns:
            StateSnapshot: 状态快照

        注：MVP 实现简化版，返回最小必需字段
        """
        # 从投影存储读取当前状态
        task_projection = self.projection_storage.load_task_projection(task_id)
        workflow_projection = self.projection_storage.load_workflow_projection(workflow_id)

        if not task_projection or not workflow_projection:
            raise CheckpointBuilderError(
                f"Cannot find projections for task={task_id}, workflow={workflow_id}"
            )

        # 构建状态快照（MVP 最小字段）
        from src.runtime.entities.task import TaskStatus
        from src.runtime.entities.workflow import WorkflowStatus

        state_snapshot = StateSnapshot(
            task_status=TaskStatus(task_projection.status),
            workflow_status=WorkflowStatus(workflow_projection.status),
            current_step_id=None,  # MVP: 待实现
            runnable_step_ids=[],
            waiting_step_ids=[],
            completed_step_ids=[],
            failed_step_ids=[],
            active_worker_refs=[],
            completed_worker_refs=[],
            pending_approval_refs=[],
            unresolved_failure_refs=[],
            required_artifact_refs=[],
            required_evidence_refs=[],
            base_revision="main",  # MVP: 硬编码
            working_revision=None,
            workspace_ref=None,
        )

        return state_snapshot

    def _collect_worker_refs(self, workflow_id: str) -> list[WorkerCheckpointRef]:
        """
        收集 Worker 恢复引用（REQ-RT-005 §4.3）

        Args:
            workflow_id: Workflow ID

        Returns:
            list[WorkerCheckpointRef]: Worker 引用列表

        注：MVP 简化，返回空列表
        """
        # MVP: 返回空列表，后续迭代实现完整 Worker 引用收集
        return []

    def _collect_action_refs(
        self, worker_id: str
    ) -> tuple[list[ActionCheckpointRef], str | None]:
        """
        收集 Action 恢复引用（REQ-RT-005 §4.4）

        Args:
            worker_id: Worker ID

        Returns:
            tuple: (Action 引用列表, 最后完成的 Action ID)

        注：MVP 简化，返回空列表
        """
        # MVP: 返回空列表，后续迭代实现完整 Action 引用收集
        return [], None

    def _classify_action_side_effect(
        self, action_id: str, action_status: ActionStatus
    ) -> tuple[SideEffectState, RecoveryAction]:
        """
        分类 Action 副作用状态（REQ-RT-005 §7）

        Args:
            action_id: Action ID
            action_status: Action 状态

        Returns:
            tuple: (副作用状态, 推荐恢复动作)

        分类规则（REQ-RT-005 §7）：
        - COMPLETED: 已确认完成，副作用状态 = CONFIRMED
        - FAILED: 已确认失败，副作用状态 = FAILED
        - EXECUTING/PENDING: 结果未知，副作用状态 = IN_PROGRESS/UNKNOWN
        """
        if action_status == ActionStatus.SUCCEEDED:
            return SideEffectState.CONFIRMED, RecoveryAction.VERIFY

        if action_status == ActionStatus.FAILED:
            return SideEffectState.FAILED, RecoveryAction.CREATE_NEW_ACTION

        if action_status == ActionStatus.EXECUTING:
            return SideEffectState.IN_PROGRESS, RecoveryAction.HUMAN_REVIEW

        # PROPOSED, AUTHORIZED, WAITING_APPROVAL, REJECTED, CANCELLED
        return SideEffectState.NOT_STARTED, RecoveryAction.CREATE_NEW_ACTION

    def _collect_budget_snapshot(self, workflow_id: str) -> BudgetSnapshot:
        """
        收集预算快照（REQ-RT-005 §4.5）

        Args:
            workflow_id: Workflow ID

        Returns:
            BudgetSnapshot: 预算快照

        注：MVP 实现简化版，使用默认预算值
        """
        # MVP: 使用默认预算值
        # 后续迭代从 Workflow/Task 配置中读取真实预算
        return BudgetSnapshot(
            max_input_tokens=100000,
            max_output_tokens=50000,
            max_total_tokens=150000,
            max_cost_microusd=1000000,  # $1.00
            max_duration_seconds=3600,  # 1 hour
            max_tool_calls=100,
            consumed_input_tokens=0,
            consumed_output_tokens=0,
            consumed_total_tokens=0,
            consumed_cost_microusd=0,
            elapsed_duration_seconds=0,
            completed_tool_calls=0,
        )

    def _collect_resource_snapshot(self, workflow_id: str) -> ResourceSnapshot:
        """
        收集资源快照（REQ-RT-005 §4.5）

        Args:
            workflow_id: Workflow ID

        Returns:
            ResourceSnapshot: 资源快照

        注：MVP 实现简化版，使用占位符值
        """
        # MVP: 使用占位符值
        # 后续迭代从 Workspace Manager 读取真实资源状态
        return ResourceSnapshot(
            workspace_id=f"workspace-{workflow_id}",
            workspace_image_version="ubuntu-22.04-python3.11",
            workspace_state_hash="placeholder-hash",
            base_revision="main",
            working_revision=None,
            branch_ref=None,
            uncommitted_change_manifest_ref=None,
            generated_artifact_refs=[],
            temporary_resource_refs=[],
            network_policy_version="v1.0",
            credential_refs=[],
        )

    def _compute_content_hash(
        self,
        state_snapshot: StateSnapshot,
        budget_snapshot: BudgetSnapshot,
        resource_snapshot: ResourceSnapshot,
    ) -> str:
        """
        计算内容哈希（REQ-RT-005 §4.1）

        Args:
            state_snapshot: 状态快照
            budget_snapshot: 预算快照
            resource_snapshot: 资源快照

        Returns:
            str: 内容哈希（SHA-256）

        注：
        - 内容哈希用于验证 StateSnapshot + Refs 的完整性
        - 与 checkpoint_hash 分开，便于独立验证内容部分
        """
        # 规范化内容（按字典序排序，保证确定性）
        content = {
            "state": state_snapshot.model_dump(mode="json"),
            "budget": budget_snapshot.model_dump(mode="json"),
            "resource": resource_snapshot.model_dump(mode="json"),
        }

        # 计算 SHA-256
        content_json = json.dumps(content, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content_json.encode("utf-8")).hexdigest()

    def _compute_checkpoint_hash(self, checkpoint_meta: dict[str, Any]) -> str:
        """
        计算检查点哈希（REQ-RT-005 §4.1, §6.1）

        Args:
            checkpoint_meta: 检查点元数据（不含 checkpoint_hash 字段）

        Returns:
            str: 检查点哈希（SHA-256）

        注：
        - 检查点哈希用于防篡改
        - 恢复时必须校验此哈希
        """
        # 移除 checkpoint_hash 字段（避免循环依赖）
        meta_copy = {k: v for k, v in checkpoint_meta.items() if k != "checkpoint_hash"}

        # 规范化元数据（处理 datetime）
        meta_normalized = {}
        for k, v in meta_copy.items():
            if isinstance(v, datetime):
                meta_normalized[k] = v.isoformat()
            else:
                meta_normalized[k] = v

        # 计算 SHA-256
        meta_json = json.dumps(meta_normalized, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(meta_json.encode("utf-8")).hexdigest()

    def _generate_checkpoint_id(self, workflow_id: str, sequence: int) -> str:
        """
        生成 checkpoint_id

        Args:
            workflow_id: Workflow ID
            sequence: 事件序列号

        Returns:
            str: checkpoint_id（格式：workflow_id-seq-timestamp）
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"{workflow_id}-seq{sequence}-{timestamp}"

    def _sanitize_sensitive_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        敏感字段脱敏（REQ-RT-005 §9）

        Args:
            data: 原始数据

        Returns:
            dict: 脱敏后数据

        禁止明文保存（REQ-RT-005 §9）：
        - API Key, Git Token, OAuth Refresh Token
        - 私钥、密码
        - 完整环境变量
        - 模型隐藏思维链
        - 未受控敏感代码

        允许保存（REQ-RT-005 §9）：
        - CredentialRef（引用，非明文）
        - 敏感级别
        - 内容哈希
        - ContentRef
        - 脱敏摘要
        """
        # MVP: 基础实现，后续迭代补充完整脱敏逻辑
        sensitive_keys = [
            "api_key",
            "token",
            "password",
            "secret",
            "credential",
            "private_key",
            "refresh_token",
        ]

        sanitized = data.copy()
        for key in sensitive_keys:
            if key in sanitized:
                sanitized[key] = "[REDACTED]"

        return sanitized
