"""
投影状态模型（REQ-RT-004 §5）

定义 Task/Workflow/Worker/Action 的查询投影结构。

设计原则：
1. 投影状态只服务查询，不能作为状态迁移的唯一依据
2. 必须包含 last_event_id 和 last_sequence 用于追溯事实来源
3. 不保存完整敏感数据（凭据、完整代码），使用 ContentRef
4. completion_summary 只是查询摘要，不能单独证明完成条件
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ============ Task Projection ============


class TaskProjection(BaseModel):
    """
    Task 当前状态投影（REQ-RT-004 §5.2）

    用于：
    - Web UI 查询任务列表和详情
    - 判断任务当前阶段和等待原因
    - 统计任务产物和失败次数
    """

    task_id: str = Field(..., description="任务 ID（业务主键）")
    organization_id: str = Field(..., description="组织 ID")
    project_id: str = Field(..., description="项目 ID")
    repository_id: str = Field(..., description="仓库 ID")
    creator_id: str = Field(..., description="创建者 ID")

    current_workflow_id: str | None = Field(
        default=None,
        description="当前执行的 Workflow ID",
    )

    status: str = Field(
        ...,
        description="任务状态（来自 TaskStatus 枚举）",
        examples=["PENDING", "PLANNING", "EXECUTING", "COMPLETED", "FAILED"],
    )

    status_reason: str | None = Field(
        default=None,
        description="状态原因说明（等待审批、失败原因等）",
    )

    risk_level: str = Field(
        ...,
        description="风险级别",
        examples=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    )

    base_revision: str = Field(
        ...,
        description="基础 Git revision（任务开始时的提交）",
    )

    working_revision: str | None = Field(
        default=None,
        description="工作 revision（Agent 修改后的提交）",
    )

    current_step_id: str | None = Field(
        default=None,
        description="当前执行步骤 ID",
    )

    required_approval_count: int = Field(
        default=0,
        ge=0,
        description="需要审批的操作数量",
    )

    unresolved_failure_count: int = Field(
        default=0,
        ge=0,
        description="未解决的失败次数",
    )

    artifact_count: int = Field(
        default=0,
        ge=0,
        description="产物总数",
    )

    evidence_count: int = Field(
        default=0,
        ge=0,
        description="证据总数",
    )

    completion_summary: dict[str, Any] | None = Field(
        default=None,
        description="完成摘要（仅查询用，不能单独证明完成条件）",
    )

    # 事实追溯字段
    last_event_id: str = Field(
        ...,
        description="最后应用的事件 ID（用于追溯事实来源）",
    )

    last_sequence: int = Field(
        ...,
        ge=0,
        description="最后应用的事件序列号",
    )

    last_event_type: str = Field(
        ...,
        description="最后应用的事件类型",
    )

    projection_version: str = Field(
        ...,
        description="投影器版本",
    )

    # 时间戳
    created_at: datetime = Field(..., description="任务创建时间（UTC）")
    started_at: datetime | None = Field(
        default=None, description="任务开始执行时间"
    )
    completed_at: datetime | None = Field(
        default=None, description="任务完成时间"
    )
    updated_at: datetime = Field(..., description="投影最后更新时间")


# ============ Workflow Projection ============


class WorkflowProjection(BaseModel):
    """
    Workflow 当前状态投影（REQ-RT-004 §5.3）

    用于：
    - Coordinator 判断可调度节点和父级状态
    - 查询并行 Worker 的计数和完成情况
    - 监控工作流执行进度
    """

    workflow_id: str = Field(..., description="Workflow ID（业务主键）")
    task_id: str = Field(..., description="所属任务 ID")
    organization_id: str = Field(..., description="组织 ID")
    project_id: str = Field(..., description="项目 ID")
    repository_id: str = Field(..., description="仓库 ID")

    status: str = Field(
        ...,
        description="工作流状态",
        examples=["READY", "RUNNING", "WAITING_APPROVAL", "COMPLETED", "FAILED"],
    )

    status_reason: str | None = Field(
        default=None,
        description="状态原因说明",
    )

    workflow_template_id: str = Field(
        ...,
        description="工作流模板 ID",
    )

    workflow_template_version: str = Field(
        ...,
        description="工作流模板版本",
    )

    agent_profile_version: str = Field(
        ...,
        description="Agent Profile 版本",
    )

    toolset_version: str = Field(
        ...,
        description="工具集版本",
    )

    base_revision: str = Field(
        ...,
        description="基础 Git revision",
    )

    working_revision: str | None = Field(
        default=None,
        description="工作 revision",
    )

    # 并行 Worker 计数（必须由 Worker 投影汇聚，不能由单个 Worker 直接写入）
    runnable_worker_count: int = Field(
        default=0,
        ge=0,
        description="可运行的 Worker 数量",
    )

    running_worker_count: int = Field(
        default=0,
        ge=0,
        description="正在运行的 Worker 数量",
    )

    waiting_approval_count: int = Field(
        default=0,
        ge=0,
        description="等待审批的 Worker 数量",
    )

    failed_worker_count: int = Field(
        default=0,
        ge=0,
        description="失败的 Worker 数量",
    )

    completed_worker_count: int = Field(
        default=0,
        ge=0,
        description="已完成的 Worker 数量",
    )

    required_worker_count: int = Field(
        default=0,
        ge=0,
        description="需要完成的 Worker 总数",
    )

    active_attempt_count: int = Field(
        default=0,
        ge=0,
        description="活跃的重试次数",
    )

    # 事实追溯字段
    last_event_id: str = Field(..., description="最后应用的事件 ID")
    last_sequence: int = Field(..., ge=0, description="最后应用的事件序列号")
    projection_version: str = Field(..., description="投影器版本")

    # 时间戳
    created_at: datetime = Field(..., description="创建时间（UTC）")
    started_at: datetime | None = Field(default=None, description="开始执行时间")
    completed_at: datetime | None = Field(default=None, description="完成时间")
    updated_at: datetime = Field(..., description="投影最后更新时间")


# ============ Worker Projection ============


class WorkerProjection(BaseModel):
    """
    Worker 当前状态投影（REQ-RT-004 §5.4）

    用于：
    - 查询 Worker 执行状态和输入输出
    - 统计 Worker 的 Action 计数
    - 追溯不同 attempt 的独立运行实例
    """

    worker_id: str = Field(..., description="Worker ID（业务主键）")
    workflow_id: str = Field(..., description="所属 Workflow ID")
    task_id: str = Field(..., description="所属任务 ID")

    step_id: str = Field(..., description="步骤 ID（用于区分并行实例）")
    worker_type: str = Field(
        ...,
        description="Worker 类型",
        examples=["PLANNER", "CODER", "TESTER", "REVIEWER"],
    )

    attempt: int = Field(
        ...,
        ge=1,
        description="重试次数（不同 attempt 必须有独立 worker_id）",
    )

    status: str = Field(
        ...,
        description="Worker 状态",
        examples=["READY", "RUNNING", "WAITING_TOOL", "COMPLETED", "FAILED"],
    )

    status_reason: str | None = Field(
        default=None,
        description="状态原因说明",
    )

    source_revision: str = Field(
        ...,
        description="Worker 操作的源 revision",
    )

    input_artifact_ids: list[str] = Field(
        default_factory=list,
        description="输入产物 ID 列表",
    )

    output_artifact_ids: list[str] = Field(
        default_factory=list,
        description="输出产物 ID 列表",
    )

    # Action 计数
    active_action_count: int = Field(
        default=0,
        ge=0,
        description="活跃的 Action 数量",
    )

    waiting_action_count: int = Field(
        default=0,
        ge=0,
        description="等待执行的 Action 数量",
    )

    failed_action_count: int = Field(
        default=0,
        ge=0,
        description="失败的 Action 数量",
    )

    last_action_id: str | None = Field(
        default=None,
        description="最后执行的 Action ID",
    )

    # 事实追溯字段
    last_event_id: str = Field(..., description="最后应用的事件 ID")
    last_sequence: int = Field(..., ge=0, description="最后应用的事件序列号")
    projection_version: str = Field(..., description="投影器版本")

    # 时间戳
    created_at: datetime = Field(..., description="创建时间（UTC）")
    started_at: datetime | None = Field(default=None, description="开始执行时间")
    completed_at: datetime | None = Field(default=None, description="完成时间")
    updated_at: datetime = Field(..., description="投影最后更新时间")


# ============ Action Projection ============


class ActionProjection(BaseModel):
    """
    Action 当前状态投影（REQ-RT-004 §5.5）

    用于：
    - 查询 Action 执行状态和审批信息
    - 追溯 Action 的策略决策和观察结果
    - 监控工具调用的风险级别和完成情况
    """

    action_id: str = Field(..., description="Action ID（业务主键）")
    task_id: str = Field(..., description="所属任务 ID")
    workflow_id: str = Field(..., description="所属 Workflow ID")
    worker_id: str = Field(..., description="所属 Worker ID")

    step_id: str = Field(..., description="步骤 ID")
    attempt: int = Field(..., ge=1, description="重试次数")

    type: str = Field(
        ...,
        description="Action 类型",
        examples=["TOOL_CALL", "MODEL_CALL", "APPROVAL_REQUEST"],
    )

    tool_name: str = Field(..., description="工具名称")
    tool_schema_version: str = Field(..., description="工具 Schema 版本")

    target_resource_hash: str = Field(
        ...,
        description="目标资源哈希（用于幂等检查，不保存完整敏感数据）",
    )

    source_revision: str = Field(
        ...,
        description="操作的源 revision",
    )

    risk_level: str = Field(
        ...,
        description="风险级别",
        examples=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    )

    status: str = Field(
        ...,
        description="Action 状态",
        examples=["PROPOSED", "APPROVED", "EXECUTING", "COMPLETED", "FAILED"],
    )

    policy_decision_id: str | None = Field(
        default=None,
        description="策略决策 ID（引用 Policy Gateway 的决策记录）",
    )

    approval_id: str | None = Field(
        default=None,
        description="审批 ID（若需要人工审批）",
    )

    observation_artifact_id: str | None = Field(
        default=None,
        description="观察结果产物 ID（引用 Artifact，不直接保存完整输出）",
    )

    failure_ref: str | None = Field(
        default=None,
        description="失败引用（错误分类和内容哈希，不保存完整敏感错误）",
    )

    # 事实追溯字段
    last_event_id: str = Field(..., description="最后应用的事件 ID")
    last_sequence: int = Field(..., ge=0, description="最后应用的事件序列号")
    projection_version: str = Field(..., description="投影器版本")

    # 时间戳
    proposed_at: datetime = Field(..., description="提议时间（UTC）")
    started_at: datetime | None = Field(default=None, description="开始执行时间")
    completed_at: datetime | None = Field(default=None, description="完成时间")
    updated_at: datetime = Field(..., description="投影最后更新时间")
