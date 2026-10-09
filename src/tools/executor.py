"""
Action 执行器，协调 Action 执行的完整流程

对齐设计文档：
- REQ-RT-001 核心实体（Action, Evidence）
- REQ-RT-002 状态机（Action 状态迁移）
- REQ-SEC-003 Policy Gateway（双重校验）
- REQ-HAR-003 Tool Adapter（工具执行）
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from ..runtime.common.types import SafeMetadata
from ..runtime.entities.action import Action, ActionStatus
from ..runtime.entities.evidence import (
    Evidence,
    EvidenceResult,
    EvidenceSource,
    EvidenceType,
    VerificationMethod,
    VerifierType,
)
from ..security.policy_gateway import PolicyDecision, PolicyGateway
from .base import ExecutionContext, ToolExecutionError, ToolResult
from .registry import ToolRegistry


class ActionExecutionResult:
    """Action 执行结果"""
    def __init__(
        self,
        success: bool,
        action: Action,
        evidence: Evidence | None = None,
        error: str | None = None
    ):
        self.success = success
        self.action = action
        self.evidence = evidence
        self.error = error


class ActionExecutor:
    """
    Action 执行器
    
    职责：
    1. 协调 Action 执行的完整流程
    2. 确保每个环节都经过 Policy Gateway 校验
    3. 记录完整的 Evidence
    4. 处理异常和超时
    
    执行流程（REQ-SEC-003 §6）：
    1. 加载 Action
    2. Policy Gateway 前置校验
    3. 执行工具
    4. Policy Gateway 后置校验
    5. 记录 Evidence
    6. 更新 Action 状态
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        policy_gateway: PolicyGateway
    ):
        """
        初始化执行器
        
        Args:
            tool_registry: 工具注册表
            policy_gateway: 策略网关
        """
        self._tool_registry = tool_registry
        self._policy_gateway = policy_gateway
    
    def _create_evidence(
        self,
        action: Action,
        context: ExecutionContext,
        evidence_type: EvidenceType,
        result: EvidenceResult,
        content: dict[str, Any],
        suffix: str = "evidence",
        source_revision: str = "unknown",
    ) -> Evidence:
        """
        创建 Evidence 实体的辅助方法
        
        Args:
            action: 关联的 Action
            context: 执行上下文
            evidence_type: Evidence 类型
            result: Evidence 结果
            content: 内容
            suffix: ID 后缀
            source_revision: 源代码版本
            
        Returns:
            Evidence 实体
        """
        content_json = json.dumps(content, sort_keys=True)
        content_hash = hashlib.sha256(content_json.encode()).hexdigest()
        now = datetime.now(UTC)

        return Evidence(
            evidence_id=str(uuid.uuid4()),
            task_id=action.task_id,
            workflow_id=action.workflow_id,
            source_action_id=action.action_id,
            producer_worker_id=action.worker_id,
            type=evidence_type,
            source=EvidenceSource.TOOL,
            source_revision=source_revision,
            verification_method=VerificationMethod.DETERMINISTIC_CHECK,
            verifier_type=VerifierType.SYSTEM,
            verifier_id="action-executor",
            result=result,
            content_schema="action-execution.v1",
            content_schema_version="1.0.0",
            content_hash=content_hash,
            content_inline=content,
            trace_id=context.trace_id,
            created_at=now,
            verified_at=now,
        )

    async def execute_action(
        self,
        action: Action,
        context: ExecutionContext
    ) -> ActionExecutionResult:
        """
        执行 Action
        
        Args:
            action: Action 实体（REQ-RT-001）
            context: 执行上下文
            
        Returns:
            ActionExecutionResult: 执行结果
        """
        try:
            # 步骤1: 验证 Action 状态（REQ-RT-002 状态机约束）
            if action.status_projection != ActionStatus.PROPOSED:
                return ActionExecutionResult(
                    success=False,
                    action=action,
                    error=f"Action must be in PROPOSED state, got {action.status_projection}"
                )

            # 更新为 EXECUTING
            action = action.model_copy(
                update={
                    "status_projection": ActionStatus.EXECUTING,
                    "started_at": datetime.now(UTC)
                }
            )

            # 步骤2: Policy Gateway 前置校验
            pre_check_result = await self._policy_gateway.check_pre_execution(
                action_id=action.action_id,
                tool_name=action.tool_name,
                params=action.arguments,
                context={
                    "user_id": context.user_id,
                    "organization_id": context.organization_id,
                    "project_id": context.project_id,
                    "task_id": context.task_id
                }
            )

            # 如果需要审批，返回 WAITING_APPROVAL
            if pre_check_result.decision == PolicyDecision.REQUIRES_APPROVAL:
                # 合并现有 metadata 和新字段
                existing_meta = action.metadata.model_dump() if action.metadata.model_extra else {}
                new_metadata = SafeMetadata(**{
                    **existing_meta,
                    "approval_reason": pre_check_result.reason
                })
                action = action.model_copy(
                    update={
                        "status_projection": ActionStatus.WAITING_APPROVAL,
                        "metadata": new_metadata
                    }
                )

                # 创建审批等待 Evidence
                evidence = self._create_evidence(
                    action=action,
                    context=context,
                    evidence_type=EvidenceType.APPROVAL_GRANTED,
                    result=EvidenceResult.PARTIAL,
                    content={
                        "reason": pre_check_result.reason,
                        "tool_name": action.tool_name,
                        "parameters": action.arguments
                    },
                    suffix="approval"
                )

                return ActionExecutionResult(
                    success=False,
                    action=action,
                    evidence=evidence,
                    error="Action requires manual approval"
                )

            # 如果拒绝，返回 FAILED
            if pre_check_result.decision == PolicyDecision.DENY:
                # 合并现有 metadata 和新字段
                existing_meta = action.metadata.model_dump() if action.metadata.model_extra else {}
                new_metadata = SafeMetadata(**{
                    **existing_meta,
                    "error": pre_check_result.reason
                })
                action = action.model_copy(
                    update={
                        "status_projection": ActionStatus.FAILED,
                        "completed_at": datetime.now(UTC),
                        "metadata": new_metadata
                    }
                )

                # 创建失败 Evidence
                evidence = self._create_evidence(
                    action=action,
                    context=context,
                    evidence_type=EvidenceType.TEST_FAILED,
                    result=EvidenceResult.FAILED,
                    content={
                        "reason": pre_check_result.reason,
                        "violations": pre_check_result.violations
                    },
                    suffix="denied"
                )

                return ActionExecutionResult(
                    success=False,
                    action=action,
                    evidence=evidence,
                    error=f"Policy check failed: {pre_check_result.reason}"
                )

            # 步骤3: 执行工具
            tool_result = await self._execute_tool(action, context)

            # 步骤4: Policy Gateway 后置校验
            post_check_result = await self._policy_gateway.check_post_execution(
                action_id=action.action_id,
                tool_name=action.tool_name,
                output=tool_result.output,
                context={
                    "user_id": context.user_id,
                    "organization_id": context.organization_id
                }
            )

            if post_check_result.decision == PolicyDecision.DENY:
                # 合并现有 metadata 和新字段
                existing_meta = action.metadata.model_dump() if action.metadata.model_extra else {}
                new_metadata = SafeMetadata(**{
                    **existing_meta,
                    "error": post_check_result.reason
                })
                action = action.model_copy(
                    update={
                        "status_projection": ActionStatus.FAILED,
                        "completed_at": datetime.now(UTC),
                        "metadata": new_metadata
                    }
                )

                evidence = self._create_evidence(
                    action=action,
                    context=context,
                    evidence_type=EvidenceType.TEST_FAILED,
                    result=EvidenceResult.FAILED,
                    content={
                        "reason": post_check_result.reason,
                        "violations": post_check_result.violations,
                        "stage": "post_execution"
                    },
                    suffix="post-denied"
                )

                return ActionExecutionResult(
                    success=False,
                    action=action,
                    evidence=evidence,
                    error=f"Post-execution check failed: {post_check_result.reason}"
                )

            # 步骤5: 更新 Action 为 SUCCEEDED
            # 合并现有 metadata 和新字段
            existing_meta = action.metadata.model_dump() if action.metadata.model_extra else {}
            new_metadata = SafeMetadata(**{
                **existing_meta,
                "output": tool_result.output,
                "execution_time_ms": tool_result.execution_time_ms
            })
            action = action.model_copy(
                update={
                    "status_projection": ActionStatus.SUCCEEDED,
                    "completed_at": datetime.now(UTC),
                    "metadata": new_metadata
                }
            )

            # 步骤6: 创建 Evidence
            evidence = self._create_evidence(
                action=action,
                context=context,
                evidence_type=EvidenceType.TEST_PASSED,
                result=EvidenceResult.PASSED,
                content={
                    "tool_name": action.tool_name,
                    "parameters": action.arguments,
                    "output": tool_result.output,
                    "metadata": tool_result.metadata
                },
                suffix="success"
            )

            return ActionExecutionResult(
                success=True,
                action=action,
                evidence=evidence
            )

        except ToolExecutionError as e:
            # 工具执行失败
            # 合并现有 metadata 和新字段
            existing_meta = action.metadata.model_dump() if action.metadata.model_extra else {}
            new_metadata = SafeMetadata(**{
                **existing_meta,
                "error": str(e)
            })
            action = action.model_copy(
                update={
                    "status_projection": ActionStatus.FAILED,
                    "completed_at": datetime.now(UTC),
                    "metadata": new_metadata
                }
            )

            evidence = self._create_evidence(
                action=action,
                context=context,
                evidence_type=EvidenceType.TEST_FAILED,
                result=EvidenceResult.FAILED,
                content={
                    "error": str(e),
                    "tool_name": action.tool_name
                },
                suffix="tool-error"
            )

            return ActionExecutionResult(
                success=False,
                action=action,
                evidence=evidence,
                error=str(e)
            )
        
        except Exception as e:
            # 未预期的异常
            # 合并现有 metadata 和新字段
            existing_meta = action.metadata.model_dump() if action.metadata.model_extra else {}
            new_metadata = SafeMetadata(**{
                **existing_meta,
                "error": f"Unexpected error: {e}"
            })
            action = action.model_copy(
                update={
                    "status_projection": ActionStatus.FAILED,
                    "completed_at": datetime.now(UTC),
                    "metadata": new_metadata
                }
            )

            evidence = self._create_evidence(
                action=action,
                context=context,
                evidence_type=EvidenceType.TEST_FAILED,
                result=EvidenceResult.FAILED,
                content={
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                suffix="unexpected-error"
            )

            return ActionExecutionResult(
                success=False,
                action=action,
                evidence=evidence,
                error=str(e)
            )

    async def _execute_tool(
        self,
        action: Action,
        context: ExecutionContext
    ) -> ToolResult:
        """
        执行工具，带超时保护
        
        Args:
            action: Action 实体
            context: 执行上下文
            
        Returns:
            ToolResult: 工具执行结果
        
        Raises:
            ToolExecutionError: 工具执行失败或超时
        """
        tool = self._tool_registry.get_tool(action.tool_name)
        if tool is None:
            raise ToolExecutionError(f"Tool '{action.tool_name}' not found")

        # 获取超时时间（优先使用工具定义，否则使用上下文）
        timeout = min(tool.timeout_seconds, context.timeout_seconds)

        try:
            # 带超时的执行
            start_time = datetime.now(UTC)
            result = await asyncio.wait_for(
                tool.execute(action.arguments, context),
                timeout=timeout
            )
            end_time = datetime.now(UTC)

            # 记录执行时间
            result.execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

            return result

        except TimeoutError:
            raise ToolExecutionError(
                f"Tool execution timeout after {timeout} seconds"
            )
        except ToolExecutionError:
            raise
        except Exception as e:
            raise ToolExecutionError(f"Tool execution failed: {e}")
