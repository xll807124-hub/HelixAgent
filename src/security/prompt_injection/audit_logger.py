"""
Prompt 注入审计日志记录 - Task 2.3 Day 2

对齐设计：REQ-SEC-006 (Prompt 注入防护) + REQ-RT-006 (审计关联)

职责：
- 记录所有 Prompt 注入检测事件
- 关联 TraceId / ActorRef / ResourceRef
- 支持按 TaskId/TraceId/ActorId 查询
- 记录所有 Policy 决策和 Kill Switch 覆盖
- 永久不可删除的审计记录

审计操作类型：
- prompt_injection.detected      : 检测到注入
- prompt_injection.policy_allow  : 允许处理
- prompt_injection.policy_review : 建议审核
- prompt_injection.policy_reject : 拒绝处理
- prompt_injection.override      : Kill Switch 覆盖
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.runtime.common.types import ActorRef, ActorType, ResourceRef, ResourceType
from src.runtime.trace.audit_correlation import AuditCorrelation, AuditRecord
from src.runtime.trace.context import TraceContext

logger = logging.getLogger(__name__)


class PromptInjectionAuditEventType(str, Enum):
    """Prompt 注入审计事件类型"""
    DETECTION = "prompt_injection.detected"
    POLICY_ALLOW = "prompt_injection.policy_allow"
    POLICY_REVIEW = "prompt_injection.policy_review"
    POLICY_REJECT = "prompt_injection.policy_reject"
    OVERRIDE_REQUESTED = "prompt_injection.override_requested"
    OVERRIDE_APPROVED = "prompt_injection.override_approved"
    OVERRIDE_DENIED = "prompt_injection.override_denied"


@dataclass
class PromptInjectionAuditContext:
    """Prompt 注入审计上下文"""
    # 业务关联
    task_id: str | None = None
    workflow_id: str | None = None
    action_id: str | None = None
    
    # Trace 关联
    trace_context: TraceContext | None = None
    
    # 操作主体
    actor_id: str = ""
    actor_type: str = "user"  # user, system, tool, etc.
    
    # 资源信息
    source_type: str = "user_input"  # user_input, repo_file, retrieval, etc.
    source_id: str = ""
    
    # 其他元数据
    metadata: dict[str, Any] = field(default_factory=dict)


class PromptInjectionAuditLogger:
    """
    Prompt 注入审计日志记录器
    
    集成到 Runtime Trace 系统的审计关联模块，记录所有检测和决策事件。
    """

    def __init__(self, audit_correlation: AuditCorrelation):
        """
        初始化审计日志记录器
        
        Args:
            audit_correlation: 审计关联管理器（来自 Runtime Trace）
        """
        self.audit_correlation = audit_correlation

    async def log_detection(
        self,
        context: PromptInjectionAuditContext,
        risk_level: str,
        confidence: float,
        detected_patterns: list[str],
        evidence: list[str],
        recommendation: str,
    ) -> AuditRecord:
        """
        记录检测事件
        
        Args:
            context: 审计上下文
            risk_level: 风险等级
            confidence: 置信度
            detected_patterns: 检测到的模式
            evidence: 证据
            recommendation: 建议
            
        Returns:
            审计记录
        """
        metadata = {
            **(context.metadata or {}),
            "risk_level": risk_level,
            "confidence": confidence,
            "detected_patterns": detected_patterns,
            "evidence": evidence[:5],  # 限制前 5 个证据
            "recommendation": recommendation,
        }

        reason = (
            f"Detected {risk_level} Prompt injection with {confidence:.1%} confidence. "
            f"Patterns: {', '.join(detected_patterns)}"
        )

        record = self.audit_correlation.create_audit_record(
            action_type=PromptInjectionAuditEventType.DETECTION.value,
            actor=ActorRef(
                actor_type=ActorType.USER,
                actor_id=context.actor_id,
            ),
            decision="PENDING",  # 待 Policy 决策
            trace_context=context.trace_context,
            task_id=context.task_id,
            workflow_id=context.workflow_id,
            action_id=context.action_id,
            resource=ResourceRef(
                resource_type=ResourceType.EXTERNAL_SERVICE,
                resource_id=context.source_id,
                scope=context.source_type,
            ) if context.source_id else None,
            reason=reason,
            metadata=metadata,
        )

        logger.info(
            f"[PromptInjectionAudit] Detection logged: "
            f"risk={risk_level}, confidence={confidence:.2f}, "
            f"audit_id={record.audit_id}"
        )

        return record

    async def log_policy_decision(
        self,
        context: PromptInjectionAuditContext,
        decision: str,  # "allow", "review", "reject", "suspicious"
        risk_level: str,
        confidence: float,
        detected_patterns: list[str],
        reason: str,
    ) -> AuditRecord:
        """
        记录 Policy 决策事件
        
        Args:
            context: 审计上下文
            decision: 决策结果
            risk_level: 风险等级
            confidence: 置信度
            detected_patterns: 检测模式
            reason: 决策理由
            
        Returns:
            审计记录
        """
        # 映射 decision 到事件类型
        event_type_map = {
            "allow": PromptInjectionAuditEventType.POLICY_ALLOW,
            "review": PromptInjectionAuditEventType.POLICY_REVIEW,
            "reject": PromptInjectionAuditEventType.POLICY_REJECT,
            "suspicious": PromptInjectionAuditEventType.POLICY_REJECT,
        }

        event_type = event_type_map.get(
            decision, PromptInjectionAuditEventType.POLICY_REVIEW
        )

        metadata = {
            **(context.metadata or {}),
            "risk_level": risk_level,
            "confidence": confidence,
            "detected_patterns": detected_patterns,
        }

        record = self.audit_correlation.create_audit_record(
            action_type=event_type.value,
            actor=ActorRef(
                actor_type=ActorType.USER,
                actor_id=context.actor_id,
            ),
            decision=decision.upper(),
            trace_context=context.trace_context,
            task_id=context.task_id,
            workflow_id=context.workflow_id,
            action_id=context.action_id,
            resource=ResourceRef(
                resource_type=ResourceType.EXTERNAL_SERVICE,
                resource_id=context.source_id,
                scope=context.source_type,
            ) if context.source_id else None,
            result_status="SUCCESS",
            reason=reason,
            metadata=metadata,
        )

        logger.info(
            f"[PromptInjectionAudit] Policy decision logged: "
            f"decision={decision}, risk={risk_level}, "
            f"audit_id={record.audit_id}"
        )

        return record

    async def log_override_requested(
        self,
        context: PromptInjectionAuditContext,
        risk_level: str,
        requestor_id: str,
        business_reason: str,
    ) -> AuditRecord:
        """
        记录 Kill Switch 覆盖请求
        
        Args:
            context: 审计上下文
            risk_level: 风险等级
            requestor_id: 请求者 ID
            business_reason: 业务原因
            
        Returns:
            审计记录
        """
        metadata = {
            **(context.metadata or {}),
            "risk_level": risk_level,
            "business_reason": business_reason,
            "requestor_id": requestor_id,
        }

        record = self.audit_correlation.create_audit_record(
            action_type=PromptInjectionAuditEventType.OVERRIDE_REQUESTED.value,
            actor=ActorRef(
                actor_type=ActorType.USER,
                actor_id=requestor_id,
            ),
            decision="PENDING",
            trace_context=context.trace_context,
            task_id=context.task_id,
            workflow_id=context.workflow_id,
            action_id=context.action_id,
            resource=ResourceRef(
                resource_type=ResourceType.EXTERNAL_SERVICE,
                resource_id=context.source_id,
                scope=context.source_type,
            ) if context.source_id else None,
            reason=f"Kill Switch override requested. Reason: {business_reason}",
            metadata=metadata,
        )

        logger.warning(
            f"[PromptInjectionAudit] Override requested: "
            f"risk={risk_level}, requestor={requestor_id}, "
            f"audit_id={record.audit_id}"
        )

        return record

    async def log_override_approved(
        self,
        context: PromptInjectionAuditContext,
        risk_level: str,
        requestor_id: str,
        approver_id: str,
        approval_level: str,
        business_reason: str,
    ) -> AuditRecord:
        """
        记录 Kill Switch 覆盖批准
        
        Args:
            context: 审计上下文
            risk_level: 风险等级
            requestor_id: 请求者 ID
            approver_id: 批准者 ID
            approval_level: 批准级别
            business_reason: 业务原因
            
        Returns:
            审计记录
        """
        metadata = {
            **(context.metadata or {}),
            "risk_level": risk_level,
            "requestor_id": requestor_id,
            "approver_id": approver_id,
            "approval_level": approval_level,
            "business_reason": business_reason,
        }

        record = self.audit_correlation.create_audit_record(
            action_type=PromptInjectionAuditEventType.OVERRIDE_APPROVED.value,
            actor=ActorRef(
                actor_type=ActorType.USER,
                actor_id=approver_id,
            ),
            decision="APPROVE",
            trace_context=context.trace_context,
            task_id=context.task_id,
            workflow_id=context.workflow_id,
            action_id=context.action_id,
            resource=ResourceRef(
                resource_type=ResourceType.EXTERNAL_SERVICE,
                resource_id=context.source_id,
                scope=context.source_type,
            ) if context.source_id else None,
            result_status="SUCCESS",
            reason=(
                f"Kill Switch override approved by {approver_id} ({approval_level}). "
                f"Requestor: {requestor_id}. Reason: {business_reason}"
            ),
            metadata=metadata,
        )

        logger.warning(
            f"[PromptInjectionAudit] Override APPROVED: "
            f"risk={risk_level}, requestor={requestor_id}, "
            f"approver={approver_id}, level={approval_level}, "
            f"audit_id={record.audit_id}"
        )

        return record

    async def log_override_denied(
        self,
        context: PromptInjectionAuditContext,
        risk_level: str,
        requestor_id: str,
        denial_reason: str,
    ) -> AuditRecord:
        """
        记录 Kill Switch 覆盖拒绝
        
        Args:
            context: 审计上下文
            risk_level: 风险等级
            requestor_id: 请求者 ID
            denial_reason: 拒绝原因
            
        Returns:
            审计记录
        """
        metadata = {
            **(context.metadata or {}),
            "risk_level": risk_level,
            "requestor_id": requestor_id,
            "denial_reason": denial_reason,
        }

        record = self.audit_correlation.create_audit_record(
            action_type=PromptInjectionAuditEventType.OVERRIDE_DENIED.value,
            actor=ActorRef(
                actor_type=ActorType.USER,
                actor_id=requestor_id,
            ),
            decision="DENY",
            trace_context=context.trace_context,
            task_id=context.task_id,
            workflow_id=context.workflow_id,
            action_id=context.action_id,
            resource=ResourceRef(
                resource_type=ResourceType.EXTERNAL_SERVICE,
                resource_id=context.source_id,
                scope=context.source_type,
            ) if context.source_id else None,
            result_status="FAILURE",
            reason=f"Kill Switch override denied. Reason: {denial_reason}",
            metadata=metadata,
        )

        logger.warning(
            f"[PromptInjectionAudit] Override DENIED: "
            f"risk={risk_level}, requestor={requestor_id}, "
            f"reason={denial_reason}, audit_id={record.audit_id}"
        )

        return record
