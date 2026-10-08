"""
RT-005 Checkpoint Protocol — 数据模型层（REQ-RT-005 §4）

本模块定义业务恢复 Checkpoint 的所有 Pydantic 数据类：
- CheckpointReason / CheckpointStatus: 枚举（§5.1、§4.1）
- StateSnapshot / WorkerCheckpointRef / ActionCheckpointRef: 内容容器（§4.2-4.4）
- BudgetSnapshot / ResourceSnapshot: 资源与预算（§4.5）
- WorkflowCheckpoint: 顶层 Checkpoint（§4.1）

设计原则：
- 所有版本/schema 字段在写入后不可变（§9）
- 不接受任何凭据明文进入 Checkpoint（§9），由 CredentialsGuard 校验
- ActionCheckpointRef.side_effect_state 字段占位（待 RT-007 冻结后补）
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ============ §5.1 / §4.1 Enums ============

class CheckpointReason(str, Enum):
    """Checkpoint 保存原因（REQ-RT-005 §5.1）

    MVP 实现：仅 RUNNING / PAUSE 两种。
    其余 3 种（APPROVAL / RECOVERY / HISTORY_BOUNDARY）保留枚举位，留待 P2 阶段。
    """
    RUNNING = "RUNNING"            # ✅ MVP 实现（自动、Worker 事件边界）
    PAUSE = "PAUSE"                # ✅ MVP 实现（用户 / 系统暂停命令）
    APPROVAL = "APPROVAL"          # ⚠️ 占位（待 RT-005-P2 实现）
    RECOVERY = "RECOVERY"          # ⚠️ 占位（待 RT-005-P2 实现）
    HISTORY_BOUNDARY = "HISTORY_BOUNDARY"  # ⚠️ 占位（待 RT-005-P2 实现）


class CheckpointStatus(str, Enum):
    """Checkpoint 状态机（REQ-RT-005 §4.1）

    状态迁移：
        CREATED -> VERIFIED          （哈希校验通过）
        CREATED -> INVALID          （哈希校验失败 / §10）
        VERIFIED -> SUPERSEDED      （被更新的 Checkpoint 取代）
    """
    CREATED = "CREATED"            # 刚写入，等待哈希校验
    VERIFIED = "VERIFIED"          # 哈希校验通过，可用于恢复
    INVALID = "INVALID"            # 哈希失败或 Schema 失效（§10）
    SUPERSEDED = "SUPERSEDED"      # 已被更新的 Checkpoint 取代


# ============ §4.4 ActionCheckpointRef ============

class ActionCheckpointRef(BaseModel):
    """REQ-RT-005 §4.4 Action 恢复引用

    注意：
    - side_effect_state 与 recovery_action 字段依赖 REQ-RT-007（Idempotency）冻结，
      本轮 MVP 保留字段占位但不在构建路径上注入副作用状态。
    - observation_artifact_id 是引用 ID，不是产物内容（§9 禁忌）。
    """
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(..., description="Action 业务唯一 ID")
    worker_id: str = Field(..., description="所属 Worker ID")
    attempt: int = Field(..., ge=1, description="重试次数")
    action_type: str = Field(..., description="Action 类型（如 TOOL_CALL）")
    tool_name: str = Field(..., description="工具名称")
    tool_schema_version: str = Field(..., description="工具 Schema 版本")
    target_resource_hash: str = Field(
        ..., description="目标资源哈希（用于幂等检查）"
    )
    source_revision: str = Field(..., description="操作的源 revision")
    action_status: str = Field(..., description="Action 状态（ActionStatus 枚举值）")
    policy_decision_id: str | None = Field(
        default=None, description="策略决策 ID（引用 Policy Gateway）"
    )
    idempotency_key_ref: str | None = Field(
        default=None, description="幂等键引用（来自 RT-007）"
    )
    observation_artifact_id: str | None = Field(
        default=None, description="观察结果产物 ID（不保存产物内容）"
    )
    # side_effect_state 与 recovery_action 字段预留下游 RT-007 契约
    # 本轮不实现，故不在此处声明具体字段以避免锁死语义


# ============ §4.3 WorkerCheckpointRef ============

class WorkerCheckpointRef(BaseModel):
    """REQ-RT-005 §4.3 Worker 恢复引用

    worker_state_ref 引用状态对象的版本化 Schema 内容，
    不能存凭据值（§9 禁忌，由 CredentialsGuard 拦截）。
    """
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(..., description="Worker 业务 ID")
    step_id: str = Field(..., description="所属 step ID")
    worker_type: str = Field(..., description="Worker 类型（如 PLANNER/CODER/TESTER/REVIEWER）")
    attempt: int = Field(..., ge=1, description="重试次数")
    status: str = Field(..., description="Worker 状态（WorkerStatus 枚举值）")
    source_revision: str = Field(..., description="Worker 操作的源 revision")
    last_applied_event_sequence: int = Field(
        ..., ge=0, description="最后应用的事件序列"
    )
    last_completed_action_id: str | None = Field(
        default=None, description="最后完成的 Action ID"
    )
    pending_action_refs: list[ActionCheckpointRef] = Field(
        default_factory=list, description="待执行的 Action 列表"
    )
    input_artifact_ids: list[str] = Field(
        default_factory=list, description="输入产物 ID 列表（不保存内容）"
    )
    output_artifact_ids: list[str] = Field(
        default_factory=list, description="输出产物 ID 列表"
    )
    context_manifest_ref: str | None = Field(
        default=None, description="上下文清单引用"
    )
    worker_state_ref: str | None = Field(
        default=None, description="Worker 状态对象引用（引用版本化 Schema 内容）"
    )


# ============ §4.2 StateSnapshot ============

class StateSnapshot(BaseModel):
    """REQ-RT-005 §4.2 状态快照

    状态快照可由 source_event_sequence 重建，因此只存
    不能从事实重建的查询视图（completed_step_ids、approval_refs、失败引用等）。
    注意：completed_step_ids 不能视为外部副作用完成的证明。
    """
    model_config = ConfigDict(extra="forbid")

    task_status: str = Field(..., description="Task 状态（TaskStatus 枚举值）")
    workflow_status: str = Field(..., description="Workflow 状态（WorkflowStatus 枚举值）")
    current_step_id: str | None = Field(
        default=None, description="当前执行的步骤 ID"
    )
    runnable_step_ids: list[str] = Field(default_factory=list)
    waiting_step_ids: list[str] = Field(default_factory=list)
    completed_step_ids: list[str] = Field(default_factory=list)
    failed_step_ids: list[str] = Field(default_factory=list)
    active_worker_refs: list[WorkerCheckpointRef] = Field(default_factory=list)
    completed_worker_refs: list[WorkerCheckpointRef] = Field(default_factory=list)
    pending_approval_refs: list[Any] = Field(
        default_factory=list, description="待审批引用列表（ApprovalRef 来自 RT-002）"
    )
    unresolved_failure_refs: list[Any] = Field(
        default_factory=list, description="未解决失败引用列表"
    )
    required_artifact_refs: list[str] = Field(default_factory=list)
    required_evidence_refs: list[str] = Field(default_factory=list)
    base_revision: str = Field(..., description="基础 Git revision")
    working_revision: str | None = Field(
        default=None, description="工作 revision（Agent 修改后）"
    )
    workspace_ref: str | None = Field(
        default=None, description="Workspace 引用"
    )


# ============ §4.5 BudgetSnapshot ============

class BudgetSnapshot(BaseModel):
    """REQ-RT-005 §4.5 预算快照

    一个 Worker 一个预算快照（按 Worker 聚合，§4.5）。
    所有计数字段均为 consumed/max 的累计值。
    """
    model_config = ConfigDict(extra="forbid")

    max_input_tokens: int = Field(default=0, ge=0)
    max_output_tokens: int = Field(default=0, ge=0)
    max_total_tokens: int = Field(default=0, ge=0)
    max_cost_microusd: int = Field(default=0, ge=0)
    max_duration_seconds: int = Field(default=0, ge=0)
    max_tool_calls: int = Field(default=0, ge=0)

    consumed_input_tokens: int = Field(default=0, ge=0)
    consumed_output_tokens: int = Field(default=0, ge=0)
    consumed_total_tokens: int = Field(default=0, ge=0)
    consumed_cost_microusd: int = Field(default=0, ge=0)
    elapsed_duration_seconds: int = Field(default=0, ge=0)
    completed_tool_calls: int = Field(default=0, ge=0)


# ============ §4.5 ResourceSnapshot ============

class ResourceSnapshot(BaseModel):
    """REQ-RT-005 §4.5 资源快照

    credential_refs 只存 CredentialRef 类型，不能存凭据值（§9 禁忌）。
    """
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(..., description="Workspace 唯一 ID")
    workspace_image_version: str = Field(..., description="Workspace 镜像版本")
    workspace_state_hash: str = Field(..., description="Workspace 状态哈希")
    base_revision: str = Field(..., description="基础 Git revision")
    working_revision: str | None = Field(default=None)
    branch_ref: str | None = Field(default=None, description="Git 分支引用")
    uncommitted_change_manifest_ref: str | None = Field(
        default=None, description="未提交变更清单引用"
    )
    generated_artifact_refs: list[str] = Field(
        default_factory=list, description="已生成产物 ID 列表"
    )
    temporary_resource_refs: list[str] = Field(
        default_factory=list, description="临时资源 ID 列表"
    )
    network_policy_version: str = Field(
        default="", description="网络策略版本"
    )
    credential_refs: list[Any] = Field(
        default_factory=list, description="凭据引用（仅引用，不含凭据值）"
    )


# ============ Content Container ============

class WorkflowCheckpointContent(BaseModel):
    """REQ-RT-005 §4.2-§4.5 容器

    聚合 StateSnapshot、WorkerCheckpointRef 列表、BudgetSnapshot 列表、ResourceSnapshot。
    """
    model_config = ConfigDict(extra="forbid")

    state: StateSnapshot = Field(..., description="Workflow 状态快照")
    worker_refs: list[WorkerCheckpointRef] = Field(
        default_factory=list, description="所有 Worker 恢复引用（含活跃与已完成）"
    )
    budgets: list[BudgetSnapshot] = Field(
        default_factory=list, description="Worker 预算快照列表"
    )
    resources: ResourceSnapshot | None = Field(
        default=None, description="资源快照（RUNNING 时可选，§6.2 开放问题答案 A）"
    )


# ============ §4.1 WorkflowCheckpoint（顶层）============


class WorkflowCheckpoint(BaseModel):
    """REQ-RT-005 §4.1 顶层业务恢复 Checkpoint 容器

    写后不可变字段（§9）：
    - schema_version / runtime_contract_version
    - 6 个版本字段（workflow_template_*, agent_profile_version, toolset_version）

    严禁字段（§9）：
    - 不存 API Key / Token / Secret / private_key / 私钥值
      （由 CredentialsGuard 字段名 + 内容双重检测拦截）
    """
    # schema_version 一经写入不可变
    schema_version: str = Field(
        default="runtime.workflow-checkpoint.v1",
        frozen=True,
        description="Checkpoint Schema 版本",
    )
    runtime_contract_version: str = Field(
        default="v1",
        frozen=True,
        description="运行时契约版本（RT 跨模块落地）",
    )

    checkpoint_id: str = Field(..., description="Checkpoint 业务唯一 ID（UUID）")
    task_id: str = Field(..., description="所属 Task ID")
    workflow_id: str = Field(..., description="所属 Workflow ID")
    organization_id: str = Field(..., description="组织 ID")
    project_id: str = Field(..., description="项目 ID")
    repository_id: str = Field(..., description="仓库 ID")

    created_at: datetime = Field(..., description="创建时间（UTC）")
    created_by: str = Field(..., description="触发方（ActorRef 简化本轮用 str）")

    checkpoint_reason: CheckpointReason = Field(..., description="保存原因")
    checkpoint_status: CheckpointStatus = Field(
        default=CheckpointStatus.CREATED,
        description="Checkpoint 状态机（CREATED/VERIFIED/INVALID/SUPERSEDED）",
    )

    # 源事件追溯
    source_event_sequence: int = Field(..., ge=0, description="触发保存的事件序列")
    source_event_id: str = Field(..., description="触发保存的事件 ID")
    source_event_hash: str = Field(..., description="触发保存的事件内容哈希")
    event_stream_partition: str = Field(
        ..., description="事件流分区（形如 workflow:{workflow_id}）"
    )

    # 哈希字段（写入前由 CheckpointHasher 计算）
    checkpoint_hash: str = Field(default="", description="Checkpoint 整体哈希")
    content_hash: str = Field(default="", description="内容哈希")

    # 6 个不可变版本字段
    workflow_template_id: str = Field(..., frozen=True)
    workflow_template_version: str = Field(..., frozen=True)
    agent_profile_version: str = Field(..., frozen=True)
    toolset_version: str = Field(..., frozen=True)

    # 内容容器
    content: WorkflowCheckpointContent = Field(..., description="Checkpoint 内容")

    model_config = ConfigDict(extra="forbid")

    def is_writable(self) -> bool:
        """Checkpoint 是否仍处于 CREATED 阶段（哈希未校验）

        用于：
        - hash 写入：CREATED -> VERIFIED
        - 防止 hash 写两次
        """
        return self.checkpoint_status == CheckpointStatus.CREATED