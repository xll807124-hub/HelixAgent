"""
Prompt 注入 Policy Gateway + 审计日志集成测试 - Task 2.3 Day 2

测试范围：
- Policy Gateway 评估逻辑
- 审计日志记录
- Kill Switch 覆盖流程
- PR Comment 生成
- 端到端集成
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.security.prompt_injection.policy_gateway import (
    PromptInjectionPolicyGateway,
    PromptInjectionPolicyDecision,
    PromptInjectionPolicyEvaluation,
    to_pr_comment,
    to_policy_decision_event,
)
from src.security.prompt_injection.audit_logger import (
    PromptInjectionAuditLogger,
    PromptInjectionAuditContext,
    PromptInjectionAuditEventType,
)


class TestPromptInjectionPolicyGateway:
    """Policy Gateway 评估测试"""

    @pytest.fixture
    def gateway(self):
        return PromptInjectionPolicyGateway()

    # ===== 低风险评估测试 =====
    @pytest.mark.asyncio
    async def test_evaluate_low_risk(self, gateway):
        """低风险内容评估"""
        result = gateway.evaluate(
            risk_level="low",
            confidence=0.2,
            detected_patterns=[],
            evidence=["Normal user question"],
            recommendation="Safe to process",
        )

        assert result.decision == PromptInjectionPolicyDecision.ALLOW
        assert result.risk_level == "low"
        assert result.confidence == 0.2
        assert result.should_comment_pr is False
        assert result.force_override_possible is False
        assert result.required_approval_level == "none"

    # ===== 中风险评估测试 =====
    @pytest.mark.asyncio
    async def test_evaluate_medium_risk(self, gateway):
        """中风险内容评估"""
        result = gateway.evaluate(
            risk_level="medium",
            confidence=0.55,
            detected_patterns=["scattered_keywords"],
            evidence=["Multiple suspicious phrases detected"],
            recommendation="Recommend human review",
        )

        assert result.decision == PromptInjectionPolicyDecision.REVIEW
        assert result.risk_level == "medium"
        assert result.confidence == 0.55
        assert result.should_comment_pr is True
        assert result.force_override_possible is False
        assert result.required_approval_level == "review"

    # ===== 高风险评估测试 =====
    @pytest.mark.asyncio
    async def test_evaluate_high_risk(self, gateway):
        """高风险注入评估"""
        result = gateway.evaluate(
            risk_level="high",
            confidence=0.78,
            detected_patterns=["instruction_override", "privilege_escalation"],
            evidence=["Detected 'ignore instructions'", "Detected 'administrator' claim"],
            recommendation="REJECT: High risk injection detected",
        )

        assert result.decision == PromptInjectionPolicyDecision.REJECT
        assert result.risk_level == "high"
        assert result.confidence == 0.78
        assert result.should_comment_pr is True
        assert result.force_override_possible is True
        assert result.required_approval_level == "admin"

    # ===== 严重风险评估测试 =====
    @pytest.mark.asyncio
    async def test_evaluate_critical_risk(self, gateway):
        """严重风险注入评估"""
        result = gateway.evaluate(
            risk_level="critical",
            confidence=0.99,
            detected_patterns=["instruction_override", "data_exfiltration"],
            evidence=[
                "Detected 'ignore all instructions'",
                "Detected data exfiltration attempt",
            ],
            recommendation="BLOCK: Critical injection - immediate rejection required",
        )

        assert result.decision == PromptInjectionPolicyDecision.REJECT
        assert result.risk_level == "critical"
        assert result.confidence == 0.99
        assert result.should_comment_pr is True
        assert result.force_override_possible is True
        assert result.required_approval_level == "senior_admin"

    # ===== 未知风险等级测试 =====
    @pytest.mark.asyncio
    async def test_evaluate_unknown_risk_level(self, gateway):
        """未知风险等级评估"""
        result = gateway.evaluate(
            risk_level="unknown",
            confidence=0.5,
            detected_patterns=[],
            evidence=[],
            recommendation="Unknown risk",
        )

        assert result.decision == PromptInjectionPolicyDecision.SUSPICIOUS
        assert result.risk_level == "unknown"
        assert result.required_approval_level == "admin"

    # ===== Kill Switch 覆盖测试 =====
    @pytest.mark.asyncio
    async def test_kill_switch_override_critical_by_senior_admin(self, gateway):
        """Senior Admin 覆盖严重风险"""
        # 创建初始严重风险评估
        initial = gateway.evaluate(
            risk_level="critical",
            confidence=0.99,
            detected_patterns=["instruction_override"],
            evidence=["Critical injection detected"],
            recommendation="BLOCK",
        )

        assert initial.decision == PromptInjectionPolicyDecision.REJECT

        # Senior Admin 覆盖
        overridden = gateway.evaluate_kill_switch_override(
            current_evaluation=initial,
            approved_by="admin_001",
            approval_level="senior_admin",
            business_reason="Business critical operation - approved by CTO",
        )

        assert overridden.decision == PromptInjectionPolicyDecision.ALLOW
        assert "Kill Switch override" in overridden.recommendation
        assert overridden.required_approval_level == "none"

    # ===== Kill Switch 覆盖权限检查测试 =====
    @pytest.mark.asyncio
    async def test_kill_switch_override_insufficient_permission(self, gateway):
        """低权限用户尝试覆盖高风险"""
        initial = gateway.evaluate(
            risk_level="critical",
            confidence=0.99,
            detected_patterns=["instruction_override"],
            evidence=["Critical injection detected"],
            recommendation="BLOCK",
        )

        # 仅 Admin 权限，无法覆盖 Senior Admin 要求
        overridden = gateway.evaluate_kill_switch_override(
            current_evaluation=initial,
            approved_by="admin_001",
            approval_level="admin",  # 权限不足
            business_reason="Need access",
        )

        # 应该保持原状
        assert overridden.decision == PromptInjectionPolicyDecision.REJECT
        assert overridden.risk_level == "critical"

    # ===== Kill Switch 覆盖 ALLOW 决策测试 =====
    @pytest.mark.asyncio
    async def test_kill_switch_override_allow_decision_ignored(self, gateway):
        """尝试覆盖 ALLOW 决策（应该忽略）"""
        initial = gateway.evaluate(
            risk_level="low",
            confidence=0.2,
            detected_patterns=[],
            evidence=[],
            recommendation="Safe",
        )

        assert initial.decision == PromptInjectionPolicyDecision.ALLOW

        # 尝试覆盖（应该被忽略）
        result = gateway.evaluate_kill_switch_override(
            current_evaluation=initial,
            approved_by="admin_001",
            approval_level="senior_admin",
            business_reason="Unnecessary override",
        )

        # 应该返回原始评估
        assert result.decision == PromptInjectionPolicyDecision.ALLOW

    # ===== PR Comment 生成测试 =====
    @pytest.mark.asyncio
    async def test_pr_comment_critical_injection(self, gateway):
        """生成严重注入的 PR Comment"""
        evaluation = gateway.evaluate(
            risk_level="critical",
            confidence=0.99,
            detected_patterns=["instruction_override", "data_exfiltration"],
            evidence=["Ignore instructions pattern", "Data exfiltration attempt"],
            recommendation="BLOCK: Critical injection detected",
        )

        comment = to_pr_comment(evaluation)

        assert "🚫" in comment
        assert "REJECT" in comment
        assert "CRITICAL" in comment
        assert "99.0%" in comment
        assert "instruction_override" in comment
        assert "Ignore instructions pattern" in comment

    @pytest.mark.asyncio
    async def test_pr_comment_medium_injection(self, gateway):
        """生成中风险的 PR Comment"""
        evaluation = gateway.evaluate(
            risk_level="medium",
            confidence=0.55,
            detected_patterns=["scattered_keywords"],
            evidence=["Multiple suspicious phrases"],
            recommendation="Review recommended",
        )

        comment = to_pr_comment(evaluation)

        assert "⚠️" in comment
        assert "REVIEW" in comment
        assert "MEDIUM" in comment

    @pytest.mark.asyncio
    async def test_pr_comment_not_generated_for_low_risk(self, gateway):
        """低风险不生成 PR Comment"""
        evaluation = gateway.evaluate(
            risk_level="low",
            confidence=0.2,
            detected_patterns=[],
            evidence=[],
            recommendation="Safe",
        )

        comment = to_pr_comment(evaluation)

        assert comment == ""

    # ===== Policy 决策事件测试 =====
    @pytest.mark.asyncio
    async def test_policy_decision_event_creation(self, gateway):
        """创建 Policy 决策事件"""
        evaluation = gateway.evaluate(
            risk_level="high",
            confidence=0.78,
            detected_patterns=["instruction_override"],
            evidence=["Detected pattern"],
            recommendation="REJECT",
        )

        event = to_policy_decision_event(evaluation)

        assert event["action_type"] == "prompt_injection_policy_decision"
        assert event["decision"] == "reject"
        assert event["risk_level"] == "high"
        assert event["confidence"] == 0.78
        assert event["detected_patterns"] == ["instruction_override"]
        assert event["requires_approval"] is True
        assert event["can_override"] is True


class TestPromptInjectionAuditLogger:
    """审计日志记录器测试"""

    @pytest.fixture
    def mock_audit_correlation(self):
        """Mock 审计关联管理器"""
        return MagicMock()

    @pytest.fixture
    def audit_logger(self, mock_audit_correlation):
        return PromptInjectionAuditLogger(mock_audit_correlation)

    @pytest.fixture
    def audit_context(self):
        """测试审计上下文"""
        return PromptInjectionAuditContext(
            task_id="task_001",
            workflow_id="workflow_001",
            action_id="action_001",
            trace_context=None,
            actor_id="user_001",
            actor_type="user",
            source_type="user_input",
            source_id="comment_001",
        )

    # ===== 检测事件记录测试 =====
    @pytest.mark.asyncio
    async def test_log_detection_event(self, audit_logger, audit_context):
        """记录检测事件"""
        # Mock create_audit_record
        mock_record = MagicMock()
        mock_record.audit_id = "audit_001"
        audit_logger.audit_correlation.create_audit_record.return_value = mock_record

        record = await audit_logger.log_detection(
            context=audit_context,
            risk_level="high",
            confidence=0.78,
            detected_patterns=["instruction_override"],
            evidence=["Pattern detected"],
            recommendation="Review",
        )

        assert record.audit_id == "audit_001"
        audit_logger.audit_correlation.create_audit_record.assert_called_once()

        # 验证调用参数
        call_args = audit_logger.audit_correlation.create_audit_record.call_args
        assert (
            call_args.kwargs["action_type"]
            == PromptInjectionAuditEventType.DETECTION.value
        )
        assert call_args.kwargs["decision"] == "PENDING"
        assert call_args.kwargs["task_id"] == "task_001"

    # ===== Policy 决策记录测试 =====
    @pytest.mark.asyncio
    async def test_log_policy_decision_allow(self, audit_logger, audit_context):
        """记录 ALLOW 决策"""
        mock_record = MagicMock()
        mock_record.audit_id = "audit_002"
        audit_logger.audit_correlation.create_audit_record.return_value = mock_record

        record = await audit_logger.log_policy_decision(
            context=audit_context,
            decision="allow",
            risk_level="low",
            confidence=0.2,
            detected_patterns=[],
            reason="Safe content",
        )

        assert record.audit_id == "audit_002"
        call_args = audit_logger.audit_correlation.create_audit_record.call_args
        assert (
            call_args.kwargs["action_type"]
            == PromptInjectionAuditEventType.POLICY_ALLOW.value
        )
        assert call_args.kwargs["decision"] == "ALLOW"

    @pytest.mark.asyncio
    async def test_log_policy_decision_reject(self, audit_logger, audit_context):
        """记录 REJECT 决策"""
        mock_record = MagicMock()
        mock_record.audit_id = "audit_003"
        audit_logger.audit_correlation.create_audit_record.return_value = mock_record

        record = await audit_logger.log_policy_decision(
            context=audit_context,
            decision="reject",
            risk_level="high",
            confidence=0.78,
            detected_patterns=["instruction_override"],
            reason="High risk injection",
        )

        assert record.audit_id == "audit_003"
        call_args = audit_logger.audit_correlation.create_audit_record.call_args
        assert (
            call_args.kwargs["action_type"]
            == PromptInjectionAuditEventType.POLICY_REJECT.value
        )
        assert call_args.kwargs["decision"] == "REJECT"

    # ===== Kill Switch 覆盖请求记录测试 =====
    @pytest.mark.asyncio
    async def test_log_override_requested(self, audit_logger, audit_context):
        """记录 Kill Switch 覆盖请求"""
        mock_record = MagicMock()
        mock_record.audit_id = "audit_004"
        audit_logger.audit_correlation.create_audit_record.return_value = mock_record

        record = await audit_logger.log_override_requested(
            context=audit_context,
            risk_level="high",
            requestor_id="user_001",
            business_reason="Business critical operation",
        )

        assert record.audit_id == "audit_004"
        call_args = audit_logger.audit_correlation.create_audit_record.call_args
        assert (
            call_args.kwargs["action_type"]
            == PromptInjectionAuditEventType.OVERRIDE_REQUESTED.value
        )
        assert "Business critical" in call_args.kwargs["reason"]

    # ===== Kill Switch 覆盖批准记录测试 =====
    @pytest.mark.asyncio
    async def test_log_override_approved(self, audit_logger, audit_context):
        """记录 Kill Switch 覆盖批准"""
        mock_record = MagicMock()
        mock_record.audit_id = "audit_005"
        audit_logger.audit_correlation.create_audit_record.return_value = mock_record

        record = await audit_logger.log_override_approved(
            context=audit_context,
            risk_level="high",
            requestor_id="user_001",
            approver_id="admin_001",
            approval_level="admin",
            business_reason="Business critical operation",
        )

        assert record.audit_id == "audit_005"
        call_args = audit_logger.audit_correlation.create_audit_record.call_args
        assert (
            call_args.kwargs["action_type"]
            == PromptInjectionAuditEventType.OVERRIDE_APPROVED.value
        )
        assert call_args.kwargs["decision"] == "APPROVE"
        assert "admin_001" in call_args.kwargs["reason"]

    # ===== Kill Switch 覆盖拒绝记录测试 =====
    @pytest.mark.asyncio
    async def test_log_override_denied(self, audit_logger, audit_context):
        """记录 Kill Switch 覆盖拒绝"""
        mock_record = MagicMock()
        mock_record.audit_id = "audit_006"
        audit_logger.audit_correlation.create_audit_record.return_value = mock_record

        record = await audit_logger.log_override_denied(
            context=audit_context,
            risk_level="critical",
            requestor_id="user_001",
            denial_reason="Insufficient approval level",
        )

        assert record.audit_id == "audit_006"
        call_args = audit_logger.audit_correlation.create_audit_record.call_args
        assert (
            call_args.kwargs["action_type"]
            == PromptInjectionAuditEventType.OVERRIDE_DENIED.value
        )
        assert call_args.kwargs["decision"] == "DENY"

    # ===== 审计上下文创建测试 =====
    @pytest.mark.asyncio
    async def test_audit_context_with_metadata(self):
        """创建包含元数据的审计上下文"""
        context = PromptInjectionAuditContext(
            task_id="task_001",
            actor_id="user_001",
            source_type="user_input",
            source_id="comment_001",
            metadata={
                "pr_number": 123,
                "repository": "my-repo",
                "branch": "feature/x",
            },
        )

        assert context.task_id == "task_001"
        assert context.metadata["pr_number"] == 123
        assert context.metadata["repository"] == "my-repo"


class TestIntegration:
    """端到端集成测试"""

    @pytest.mark.asyncio
    async def test_end_to_end_detection_to_audit(self):
        """端到端：检测 -> Policy 决策 -> 审计记录"""
        gateway = PromptInjectionPolicyGateway()
        mock_audit_correlation = MagicMock()
        audit_logger = PromptInjectionAuditLogger(mock_audit_correlation)

        # 步骤 1: 检测
        detection_context = PromptInjectionAuditContext(
            task_id="task_001",
            actor_id="user_001",
            source_id="comment_001",
        )

        mock_record = MagicMock()
        mock_record.audit_id = "audit_001"
        mock_audit_correlation.create_audit_record.return_value = mock_record

        await audit_logger.log_detection(
            context=detection_context,
            risk_level="high",
            confidence=0.78,
            detected_patterns=["instruction_override"],
            evidence=["Pattern detected"],
            recommendation="Review",
        )

        # 步骤 2: Policy 决策
        evaluation = gateway.evaluate(
            risk_level="high",
            confidence=0.78,
            detected_patterns=["instruction_override"],
            evidence=["Pattern detected"],
            recommendation="Review",
        )

        assert evaluation.decision == PromptInjectionPolicyDecision.REJECT
        assert evaluation.required_approval_level == "admin"

        # 步骤 3: 记录决策
        await audit_logger.log_policy_decision(
            context=detection_context,
            decision="reject",
            risk_level="high",
            confidence=0.78,
            detected_patterns=["instruction_override"],
            reason="Policy gateway rejection",
        )

        # 验证审计关联被调用了 2 次（检测 + 决策）
        assert mock_audit_correlation.create_audit_record.call_count == 2

    @pytest.mark.asyncio
    async def test_end_to_end_critical_detection_with_override(self):
        """端到端：严重注入 -> Kill Switch 覆盖 -> 完整审计记录"""
        gateway = PromptInjectionPolicyGateway()
        mock_audit_correlation = MagicMock()
        audit_logger = PromptInjectionAuditLogger(mock_audit_correlation)

        audit_context = PromptInjectionAuditContext(
            task_id="task_001",
            actor_id="user_001",
            source_id="comment_001",
        )

        # 创建 mock 记录
        mock_records = [
            MagicMock(audit_id=f"audit_{i:03d}") for i in range(1, 6)
        ]
        mock_audit_correlation.create_audit_record.side_effect = mock_records

        # 步骤 1: 检测严重注入
        await audit_logger.log_detection(
            context=audit_context,
            risk_level="critical",
            confidence=0.99,
            detected_patterns=["instruction_override", "data_exfiltration"],
            evidence=["Critical pattern"],
            recommendation="BLOCK",
        )

        # 步骤 2: Policy 决策 -> REJECT
        evaluation = gateway.evaluate(
            risk_level="critical",
            confidence=0.99,
            detected_patterns=["instruction_override", "data_exfiltration"],
            evidence=["Critical pattern"],
            recommendation="BLOCK",
        )

        assert evaluation.decision == PromptInjectionPolicyDecision.REJECT

        # 步骤 3: 记录 Policy 决策
        await audit_logger.log_policy_decision(
            context=audit_context,
            decision="reject",
            risk_level="critical",
            confidence=0.99,
            detected_patterns=["instruction_override", "data_exfiltration"],
            reason="Critical injection detected",
        )

        # 步骤 4: 请求 Kill Switch 覆盖
        await audit_logger.log_override_requested(
            context=audit_context,
            risk_level="critical",
            requestor_id="user_001",
            business_reason="Business critical - approved by CTO",
        )

        # 步骤 5: 批准 Kill Switch 覆盖
        overridden = gateway.evaluate_kill_switch_override(
            current_evaluation=evaluation,
            approved_by="admin_001",
            approval_level="senior_admin",
            business_reason="Business critical - approved by CTO",
        )

        assert overridden.decision == PromptInjectionPolicyDecision.ALLOW

        # 步骤 6: 记录覆盖批准
        await audit_logger.log_override_approved(
            context=audit_context,
            risk_level="critical",
            requestor_id="user_001",
            approver_id="admin_001",
            approval_level="senior_admin",
            business_reason="Business critical - approved by CTO",
        )

        # 验证所有 4 个审计事件都被记录（检测、决策、覆盖请求、覆盖批准）
        assert mock_audit_correlation.create_audit_record.call_count == 4
