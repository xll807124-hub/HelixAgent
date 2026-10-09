"""
Checkpoint Schema 定义（REQ-RT-005 §4）

本模块定义 Workflow Checkpoint 的完整数据模型，包括：
- 检查点元数据（§4.1）
- 状态快照（§4.2）
- Worker 恢复引用（§4.3）
- Action 恢复引用（§4.4）
- 预算和资源快照（§4.5）

所有模型均为不可变（frozen=True），创建后不可修改。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from src.runtime.entities.action import ActionStatus, ActionType
from src.runtime.entities.task import RiskLevel, TaskStatus
from src.runtime.entities.worker import WorkerStatus, WorkerType
from src.runtime.entities.workflow import WorkflowStatus

# ============================================================================
# 枚举类型
# ============================================================================


class CheckpointReason(str, Enum):
    """检查点创建原因（REQ-RT-005 §5.1）"""

    RUNNING = "RUNNING"  # Workflow 启动、Worker 完成后、周期性边界
    PAUSE = "PAUSE"  # 用户暂停、系统暂停、Kill Switch
    APPROVAL = "APPROVAL"  # 计划审批、高风险 Action 审批
    RECOVERY = "RECOVERY"  # 恢复流程完成后保存新边界
    HISTORY_BOUNDARY = "HISTORY_BOUNDARY"  # 事件历史分段


class CheckpointStatus(str, Enum):
    """检查点状态（REQ-RT-005 §4.1）"""

    CREATED = "CREATED"  # 已创建，待验证
    VERIFIED = "VERIFIED"  # 已验证，可用于恢复
    INVALID = "INVALID"  # 校验失败或损坏
    SUPERSEDED = "SUPERSEDED"  # 被更新的检查点替代


class SideEffectState(str, Enum):
    """Action 副作用状态（REQ-RT-005 §4.4, §7）"""

    UNKNOWN = "UNKNOWN"  # 未知，需核查
    NOT_STARTED = "NOT_STARTED"  # 已确认未开始
    IN_PROGRESS = "IN_PROGRESS"  # 已开始但结果未知
    CONFIRMED = "CONFIRMED"  # 已确认完成
    FAILED = "FAILED"  # 已确认失败


class RecoveryAction(str, Enum):
    """恢复决策（REQ-RT-005 §4.4）"""

    VERIFY = "VERIFY"  # 核查副作用状态
    REPLAY_SAFE = "REPLAY_SAFE"  # 只读操作，可安全重放
    CREATE_NEW_ACTION = "CREATE_NEW_ACTION"  # 创建新 Action
    HUMAN_REVIEW = "HUMAN_REVIEW"  # 人工审查


# ============================================================================
# Checkpoint 元数据（§4.1）
# ============================================================================


class WorkflowCheckpoint(BaseModel):
    """
    Workflow Checkpoint 元数据（REQ-RT-005 §4.1）

    不可变检查点，绑定事件序列和运行资产版本。

    职责：
    1. 唯一标识检查点和关联的 Workflow
    2. 绑定事实事件序列（source_event_sequence + source_event_hash）
    3. 记录检查点创建原因和状态
    4. 包含完整的版本信息（runtime/workflow/agent/toolset）
    5. 提供完整性校验（checkpoint_hash + content_hash）

    不变量（REQ-RT-005 §3）：
    1. checkpoint_id 全局唯一
    2. source_event_sequence 必须 >= 0
    3. source_event_hash 必须与 Event Store 中的事件哈希一致
    4. checkpoint_hash 必须与内容哈希一致
    5. 创建后不可修改（frozen=True）
    """

    model_config = ConfigDict(frozen=True, strict=True)

    # 基础标识
    schema_version: str = Field(
        default="runtime.workflow-checkpoint.v1",
        description="Checkpoint Schema 版本",
    )
    checkpoint_id: str = Field(..., description="检查点唯一 ID")
    task_id: str = Field(..., description="关联的 Task ID")
    workflow_id: str = Field(..., description="关联的 Workflow ID")
    organization_id: str = Field(..., description="组织 ID（权限隔离）")
    project_id: str = Field(..., description="项目 ID（权限隔离）")
    repository_id: str = Field(..., description="仓库 ID（权限隔离）")

    # 元数据
    created_at: datetime = Field(..., description="创建时间（UTC）")
    created_by: str = Field(..., description="创建者（ActorRef）")
    checkpoint_reason: CheckpointReason = Field(..., description="创建原因")
    checkpoint_status: CheckpointStatus = Field(
        default=CheckpointStatus.CREATED, description="检查点状态"
    )

    # 事件绑定（唯一事实来源）
    source_event_sequence: int = Field(..., ge=0, description="源事件序列号")
    source_event_id: str = Field(..., description="源事件 ID")
    source_event_hash: str = Field(..., description="源事件哈希")
    event_stream_partition: str = Field(..., description="事件流分区键（workflow_id）")

    # 完整性校验
    checkpoint_hash: str = Field(..., description="检查点哈希（防篡改）")
    content_hash: str = Field(..., description="内容哈希（StateSnapshot + Refs）")

    # 版本信息（REQ-RT-005 §9）
    runtime_contract_version: str = Field(..., description="运行时契约版本")
    workflow_template_id: str = Field(..., description="Workflow 模板 ID")
    workflow_template_version: str = Field(..., description="Workflow 模板版本")
    agent_profile_version: str = Field(..., description="Agent Profile 版本")
    toolset_version: str = Field(..., description="工具集版本")

    # 状态快照和引用（通过 content_ref 引用，避免直接嵌套过大对象）
    state_snapshot_ref: str = Field(..., description="状态快照引用（ContentRef）")
    budget_snapshot_ref: str = Field(..., description="预算快照引用（ContentRef）")
    resource_snapshot_ref: str = Field(..., description="资源快照引用（ContentRef）")

    @property
    def is_valid(self) -> bool:
        """检查点是否有效可用"""
        return self.checkpoint_status == CheckpointStatus.VERIFIED


# ============================================================================
# 状态快照（§4.2）
# ============================================================================


class StateSnapshot(BaseModel):
    """
    Workflow 状态快照（REQ-RT-005 §4.2）

    职责：
    1. 记录 Task/Workflow 的当前状态（必须可由 source_event_sequence 重建）
    2. 记录 Worker 和 Action 的引用（不复制完整历史）
    3. 记录工作流执行上下文（步骤、审批、失败）
    4. 记录工作区和代码修订引用

    注意（REQ-RT-005 §4.2）：
    - 状态快照必须能由事件重建，不能成为新的状态事实
    - completed_step_ids 不能单独证明外部副作用已完成
    """

    model_config = ConfigDict(frozen=True, strict=True)

    # Task/Workflow 状态
    task_status: TaskStatus = Field(..., description="Task 当前状态")
    workflow_status: WorkflowStatus = Field(..., description="Workflow 当前状态")

    # 工作流执行状态
    current_step_id: str | None = Field(None, description="当前执行步骤 ID")
    runnable_step_ids: list[str] = Field(default_factory=list, description="可运行步骤")
    waiting_step_ids: list[str] = Field(default_factory=list, description="等待中步骤")
    completed_step_ids: list[str] = Field(default_factory=list, description="已完成步骤")
    failed_step_ids: list[str] = Field(default_factory=list, description="失败步骤")

    # Worker 引用
    active_worker_refs: list[str] = Field(
        default_factory=list, description="活跃 Worker 引用（WorkerCheckpointRef ID）"
    )
    completed_worker_refs: list[str] = Field(
        default_factory=list, description="已完成 Worker 引用"
    )

    # 审批和失败
    pending_approval_refs: list[str] = Field(
        default_factory=list, description="待审批引用（ApprovalRef）"
    )
    unresolved_failure_refs: list[str] = Field(
        default_factory=list, description="未解决失败引用（FailureRef）"
    )

    # Artifact 和 Evidence 引用
    required_artifact_refs: list[str] = Field(
        default_factory=list, description="必需的 Artifact 引用"
    )
    required_evidence_refs: list[str] = Field(
        default_factory=list, description="必需的 Evidence 引用"
    )

    # 代码修订引用
    base_revision: str = Field(..., description="基准修订（RevisionRef）")
    working_revision: str | None = Field(None, description="工作修订（RevisionRef）")
    workspace_ref: str | None = Field(None, description="工作区引用（WorkspaceRef）")


# ============================================================================
# Worker 恢复引用（§4.3）
# ============================================================================


class WorkerCheckpointRef(BaseModel):
    """
    Worker 恢复引用（REQ-RT-005 §4.3）

    职责：
    1. 记录 Worker 的最小恢复信息
    2. 引用 Worker 的输入/输出 Artifact
    3. 引用 Worker 的上下文清单和状态
    4. 记录最后应用的事件序列

    注意（REQ-RT-005 §4.3）：
    - worker_state_ref 必须引用经过 Schema 校验的状态
    - 禁止保存模型隐藏推理、未脱敏环境变量、长期凭据
    """

    model_config = ConfigDict(frozen=True, strict=True)

    # Worker 标识
    worker_id: str = Field(..., description="Worker ID")
    step_id: str = Field(..., description="关联的步骤 ID")
    worker_type: WorkerType = Field(..., description="Worker 类型")
    attempt: int = Field(..., ge=1, description="执行尝试次数")
    status: WorkerStatus = Field(..., description="Worker 状态")

    # 代码修订
    source_revision: str = Field(..., description="源代码修订（RevisionRef）")

    # 事件序列
    last_applied_event_sequence: int = Field(..., ge=0, description="最后应用的事件序列")

    # Action 引用
    last_completed_action_id: str | None = Field(None, description="最后完成的 Action ID")
    pending_action_refs: list[str] = Field(
        default_factory=list, description="待处理 Action 引用（ActionCheckpointRef ID）"
    )

    # Artifact 引用
    input_artifact_ids: list[str] = Field(default_factory=list, description="输入 Artifact")
    output_artifact_ids: list[str] = Field(default_factory=list, description="输出 Artifact")

    # 上下文和状态引用（不直接嵌套）
    context_manifest_ref: str | None = Field(None, description="上下文清单引用（ContentRef）")
    worker_state_ref: str | None = Field(None, description="Worker 状态引用（ContentRef）")


# ============================================================================
# Action 恢复引用（§4.4）
# ============================================================================


class ActionCheckpointRef(BaseModel):
    """
    Action 恢复引用（REQ-RT-005 §4.4, §7）

    职责：
    1. 记录 Action 的最小恢复信息
    2. 记录副作用状态（用于恢复决策）
    3. 记录工具调用信息（类型、Schema 版本、目标资源）
    4. 记录策略决策和幂等键引用

    副作用状态分类（REQ-RT-005 §7）：
    - CONFIRMED: 已确认完成，不重复执行（§7.1）
    - NOT_STARTED: 已确认未开始，可创建新 Action（§7.2）
    - IN_PROGRESS/UNKNOWN: 需核查副作用（§7.3）

    注意（REQ-RT-005 §4.4）：
    - side_effect_state 只表达恢复决策所需状态
    - 不替代 REQ-RT-007 的幂等协议
    """

    model_config = ConfigDict(frozen=True, strict=True)

    # Action 标识
    action_id: str = Field(..., description="Action ID")
    worker_id: str = Field(..., description="所属 Worker ID")
    attempt: int = Field(..., ge=1, description="执行尝试次数")
    action_type: ActionType = Field(..., description="Action 类型")

    # 工具信息
    tool_name: str = Field(..., description="工具名称")
    tool_schema_version: str = Field(..., description="工具 Schema 版本")
    target_resource_hash: str = Field(..., description="目标资源哈希")

    # 代码修订
    source_revision: str = Field(..., description="源代码修订（RevisionRef）")

    # Action 状态
    action_status: ActionStatus = Field(..., description="Action 状态")
    risk_level: RiskLevel = Field(..., description="风险级别（继承自 Action）")

    # 策略和幂等
    policy_decision_id: str | None = Field(None, description="策略决策 ID")
    idempotency_key_ref: str | None = Field(None, description="幂等键引用")

    # Observation 引用
    observation_artifact_id: str | None = Field(None, description="观察结果 Artifact")

    # 副作用状态（恢复决策核心）
    side_effect_state: SideEffectState = Field(..., description="副作用状态")
    recovery_action: RecoveryAction = Field(..., description="推荐的恢复动作")


# ============================================================================
# 预算快照（§4.5）
# ============================================================================


class BudgetSnapshot(BaseModel):
    """
    预算快照（REQ-RT-005 §4.5）

    职责：
    1. 记录 Workflow 的预算限制（max_*）
    2. 记录已消耗的预算（consumed_*）
    3. 恢复时重新校验剩余预算

    注意：
    - 预算限制必须在恢复时重新验证
    - 超预算必须阻止恢复或进入审批
    """

    model_config = ConfigDict(frozen=True, strict=True)

    # 预算限制
    max_input_tokens: int = Field(..., ge=0, description="最大输入 Token")
    max_output_tokens: int = Field(..., ge=0, description="最大输出 Token")
    max_total_tokens: int = Field(..., ge=0, description="最大总 Token")
    max_cost_microusd: int = Field(..., ge=0, description="最大成本（微美元）")
    max_duration_seconds: int = Field(..., ge=0, description="最大执行时长（秒）")
    max_tool_calls: int = Field(..., ge=0, description="最大工具调用次数")

    # 已消耗预算
    consumed_input_tokens: int = Field(..., ge=0, description="已消耗输入 Token")
    consumed_output_tokens: int = Field(..., ge=0, description="已消耗输出 Token")
    consumed_total_tokens: int = Field(..., ge=0, description="已消耗总 Token")
    consumed_cost_microusd: int = Field(..., ge=0, description="已消耗成本（微美元）")
    elapsed_duration_seconds: int = Field(..., ge=0, description="已用时长（秒）")
    completed_tool_calls: int = Field(..., ge=0, description="已完成工具调用次数")

    @property
    def is_budget_exceeded(self) -> bool:
        """是否超预算"""
        return (
            self.consumed_total_tokens >= self.max_total_tokens
            or self.consumed_cost_microusd >= self.max_cost_microusd
            or self.elapsed_duration_seconds >= self.max_duration_seconds
            or self.completed_tool_calls >= self.max_tool_calls
        )

    @property
    def remaining_tokens(self) -> int:
        """剩余 Token 预算"""
        return max(0, self.max_total_tokens - self.consumed_total_tokens)


# ============================================================================
# 资源快照（§4.5）
# ============================================================================


class ResourceSnapshot(BaseModel):
    """
    资源快照（REQ-RT-005 §4.5）

    职责：
    1. 记录工作区状态（workspace_id + image + state_hash）
    2. 记录代码修订（base_revision + working_revision）
    3. 记录变更清单和生成的 Artifact
    4. 记录临时资源（需在恢复后清理或验证）
    5. 记录网络策略和凭据引用

    注意（REQ-RT-005 §4.5）：
    - credential_refs 只能是不可逆引用，不能保存凭据值
    - 工作区必须通过 Revision + 变更清单 + 哈希验证
    - 不能仅凭路径恢复信任
    """

    model_config = ConfigDict(frozen=True, strict=True)

    # 工作区
    workspace_id: str = Field(..., description="工作区 ID")
    workspace_image_version: str = Field(..., description="工作区镜像版本")
    workspace_state_hash: str = Field(..., description="工作区状态哈希")

    # 代码修订
    base_revision: str = Field(..., description="基准修订（RevisionRef）")
    working_revision: str | None = Field(None, description="工作修订（RevisionRef）")
    branch_ref: str | None = Field(None, description="分支引用（ResourceRef）")

    # 变更清单
    uncommitted_change_manifest_ref: str | None = Field(
        None, description="未提交变更清单引用（ContentRef）"
    )
    generated_artifact_refs: list[str] = Field(
        default_factory=list, description="生成的 Artifact 引用"
    )

    # 临时资源（恢复后需验证）
    temporary_resource_refs: list[str] = Field(
        default_factory=list, description="临时资源引用（ResourceRef）"
    )

    # 网络和凭据
    network_policy_version: str = Field(..., description="网络策略版本")
    credential_refs: list[str] = Field(
        default_factory=list, description="凭据引用（不可逆，不含凭据值）"
    )
