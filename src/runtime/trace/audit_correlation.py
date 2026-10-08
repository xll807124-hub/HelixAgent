"""
审计关联逻辑。

对应契约：docs/design-specs/REQ-RT-006-Trace-传播和审计关联.md §6（审计关联与查询需求）

实现审计记录与 Trace 的关联：
- 审计记录独立于 Trace（不受采样影响，100% 写入）
- 审计记录包含 TraceId 引用（如果存在）
- 支持按 TaskId/TraceId/ActorId 查询审计记录
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..common.types import ActorRef, ResourceRef, utc_now
from .context import TraceContext


class AuditRecord(BaseModel):
    """审计记录（REQ-RT-006 §6.1/§6.2）。

    核心原则：
    - 审计记录 100% 写入（不受 Trace 采样影响）
    - 包含主体、资源、决策、结果的完整关联
    - 审计事实来自平台控制点，而非模型输出

    必须审计的操作（REQ-RT-006 §6.1）：
    - Task 创建/取消
    - 权限与策略决定
    - 审批请求与结果
    - Action 授权/拒绝
    - 工具开始/结束/失败
    - 凭据签发/撤销
    - 沙箱创建/销毁
    - Kill Switch 操作
    - 最终交付状态
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # 审计记录唯一标识
    audit_id: str = Field(description="审计记录唯一标识（UUIDv7）")

    # 时间戳
    timestamp: datetime = Field(
        default_factory=utc_now,
        description="审计时间（UTC）",
    )

    # 业务关联坐标（REQ-RT-006 §6.2）
    organization_id: str | None = Field(default=None, description="组织 ID")
    project_id: str | None = Field(default=None, description="项目 ID")
    repository_id: str | None = Field(default=None, description="仓库 ID")
    task_id: str | None = Field(default=None, description="Task ID")
    workflow_id: str | None = Field(default=None, description="Workflow ID")
    action_id: str | None = Field(default=None, description="Action ID")

    # Trace 关联（如果存在）
    trace_id: str | None = Field(
        default=None,
        description="关联的 TraceId（可能为空，因为 Trace 可能未采样）",
    )
    span_id: str | None = Field(
        default=None,
        description="关联的 SpanId（可能为空）",
    )

    # 操作主体与目标
    actor: ActorRef = Field(description="操作主体（用户/Worker/工具/系统）")
    action_type: str = Field(description="操作类型（如 'task.create', 'policy.deny'）")
    resource: ResourceRef | None = Field(default=None, description="目标资源")

    # 决策与结果
    decision: str = Field(
        description="决策结果（ALLOW/DENY/PENDING/ERROR）"
    )
    result_status: str | None = Field(
        default=None,
        description="执行结果状态（SUCCESS/FAILURE/TIMEOUT/UNKNOWN）",
    )
    reason: str | None = Field(
        default=None,
        description="决策或失败原因",
    )

    # 策略与证据引用
    policy_version: str | None = Field(
        default=None,
        description="策略版本引用",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="证据引用（Evidence ID 列表）",
    )

    # 额外元数据（不含敏感信息）
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="额外元数据（不含凭据/代码）",
    )


class AuditCorrelation:
    """审计关联管理器（REQ-RT-006 §6）。

    提供审计记录创建和查询接口。
    """

    @staticmethod
    def create_audit_record(
        action_type: str,
        actor: ActorRef,
        decision: str,
        trace_context: TraceContext | None = None,
        task_id: str | None = None,
        workflow_id: str | None = None,
        action_id: str | None = None,
        resource: ResourceRef | None = None,
        result_status: str | None = None,
        reason: str | None = None,
        policy_version: str | None = None,
        evidence_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditRecord:
        """创建审计记录。

        Args:
            action_type: 操作类型
            actor: 操作主体
            decision: 决策结果
            trace_context: Trace 上下文（可选，可能不存在因为未采样）
            task_id: Task ID
            workflow_id: Workflow ID
            action_id: Action ID
            resource: 目标资源
            result_status: 执行结果状态
            reason: 原因
            policy_version: 策略版本
            evidence_refs: 证据引用
            metadata: 额外元数据

        Returns:
            审计记录

        核心原则（REQ-RT-006 §4.3/§6.1）：
        - 审计记录独立于 Trace（即使 Trace 未采样也要写入）
        - 审计事实来自平台控制点，而非模型输出
        """
        from ..common.types import generate_entity_id

        return AuditRecord(
            audit_id=generate_entity_id(),
            timestamp=utc_now(),
            task_id=task_id,
            workflow_id=workflow_id,
            action_id=action_id,
            trace_id=trace_context.trace_id if trace_context else None,
            span_id=trace_context.span_id if trace_context else None,
            actor=actor,
            action_type=action_type,
            resource=resource,
            decision=decision,
            result_status=result_status,
            reason=reason,
            policy_version=policy_version,
            evidence_refs=evidence_refs or [],
            metadata=metadata or {},
        )

    @staticmethod
    def should_audit(action_type: str) -> bool:
        """判断操作是否需要审计（REQ-RT-006 §6.1）。

        必须审计的操作类别：
        - task.* (创建/取消/完成)
        - policy.* (决策/拒绝)
        - approval.* (请求/批准/拒绝)
        - action.* (授权/拒绝/执行)
        - tool.* (开始/结束/失败)
        - credential.* (签发/撤销)
        - sandbox.* (创建/销毁)
        - kill_switch.* (触发/恢复)
        """
        audit_prefixes = [
            "task.",
            "policy.",
            "approval.",
            "action.",
            "tool.",
            "credential.",
            "sandbox.",
            "kill_switch.",
        ]
        return any(action_type.startswith(prefix) for prefix in audit_prefixes)
