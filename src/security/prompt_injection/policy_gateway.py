"""
Prompt 注入 Policy Gateway 集成 - Task 2.3 Day 2

对齐设计：REQ-SEC-006 (Prompt 注入防护) + Policy Gateway 架构

职责：
- 将 Prompt 注入检测结果融入 Policy Gateway 决策流程
- HIGH/CRITICAL 风险触发审批流程
- 记录所有检测与决策事件
- 支持 Kill Switch 覆盖（管理员强制通过）

集成点：
1. 用户 Issue/Comment → Content Source 标记
2. 检测结果 → Policy 决策（ALLOW/REJECT/PENDING）
3. 决策 → 审计日志 + PR Comment
4. Kill Switch → 审批覆盖 + 永久审计记录
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PromptInjectionPolicyDecision(str, Enum):
    """Prompt 注入检测的 Policy 决策"""
    ALLOW = "allow"              # 安全内容，允许处理
    REVIEW = "review"            # 中风险，人工审核
    REJECT = "reject"            # 高/严重风险，拒绝
    SUSPICIOUS = "suspicious"    # 可疑但无法确定，需要二次检查


@dataclass
class PromptInjectionPolicyEvaluation:
    """Prompt 注入 Policy 评估结果"""
    decision: PromptInjectionPolicyDecision
    confidence: float                # 0.0 ~ 1.0
    risk_level: str                  # "low", "medium", "high", "critical"
    detected_patterns: list[str]
    evidence: list[str]
    recommendation: str
    
    # Policy Gateway 控制
    should_comment_pr: bool          # 是否生成 PR Comment
    force_override_possible: bool    # 是否可通过 Kill Switch 覆盖
    required_approval_level: str     # "none", "review", "admin", "senior_admin"


class PromptInjectionPolicyGateway:
    """
    Prompt 注入检测 Policy Gateway
    
    将检测结果转化为 Policy 决策，集成到安全审批流程。
    
    决策规则：
    - LOW 风险        → ALLOW (允许处理)
    - MEDIUM 风险     → REVIEW (建议审核，但允许处理)
    - HIGH 风险       → REJECT (拒绝处理，需人工审核或 Kill Switch)
    - CRITICAL 风险   → REJECT (立即拒绝，仅 Kill Switch 可覆盖)
    
    Policy 优先级：
    1. CRITICAL 注入  → 立即拒绝，Senior Admin 可覆盖
    2. HIGH 注入      → 拒绝，Admin 可审批后覆盖
    3. MEDIUM 注入    → 建议审核，记录但允许继续
    4. LOW 注入       → 允许，记录日志
    """

    # Policy 规则映射
    RISK_TO_POLICY_MAP = {
        "critical": {
            "decision": PromptInjectionPolicyDecision.REJECT,
            "approval_level": "senior_admin",
            "can_override": True,
        },
        "high": {
            "decision": PromptInjectionPolicyDecision.REJECT,
            "approval_level": "admin",
            "can_override": True,
        },
        "medium": {
            "decision": PromptInjectionPolicyDecision.REVIEW,
            "approval_level": "review",
            "can_override": False,
        },
        "low": {
            "decision": PromptInjectionPolicyDecision.ALLOW,
            "approval_level": "none",
            "can_override": False,
        },
    }

    def evaluate(
        self,
        risk_level: str,
        confidence: float,
        detected_patterns: list[str],
        evidence: list[str],
        recommendation: str,
    ) -> PromptInjectionPolicyEvaluation:
        """
        评估 Prompt 注入检测结果，生成 Policy 决策
        
        Args:
            risk_level: 风险等级 ("low", "medium", "high", "critical")
            confidence: 置信度 (0.0 ~ 1.0)
            detected_patterns: 检测到的攻击模式
            evidence: 证据列表
            recommendation: 系统建议
            
        Returns:
            PromptInjectionPolicyEvaluation: Policy 评估结果
        """
        risk_key = risk_level.lower()
        
        if risk_key not in self.RISK_TO_POLICY_MAP:
            # 未知风险等级，采用保守策略
            logger.warning(f"Unknown risk level: {risk_key}, defaulting to REJECT")
            return self._create_suspicious_evaluation(
                risk_level, confidence, detected_patterns, evidence, recommendation
            )
        
        if risk_key == "critical":
            return self._evaluate_critical(
                confidence, detected_patterns, evidence, recommendation
            )
        elif risk_key == "high":
            return self._evaluate_high(
                confidence, detected_patterns, evidence, recommendation
            )
        elif risk_key == "medium":
            return self._evaluate_medium(
                confidence, detected_patterns, evidence, recommendation
            )
        else:  # low
            return self._evaluate_low(
                confidence, detected_patterns, evidence, recommendation
            )

    def _evaluate_critical(
        self,
        confidence: float,
        detected_patterns: list[str],
        evidence: list[str],
        recommendation: str,
    ) -> PromptInjectionPolicyEvaluation:
        """评估严重 Prompt 注入"""
        return PromptInjectionPolicyEvaluation(
            decision=PromptInjectionPolicyDecision.REJECT,
            confidence=confidence,
            risk_level="critical",
            detected_patterns=detected_patterns,
            evidence=evidence,
            recommendation=recommendation,
            should_comment_pr=True,
            force_override_possible=True,
            required_approval_level="senior_admin",
        )

    def _evaluate_high(
        self,
        confidence: float,
        detected_patterns: list[str],
        evidence: list[str],
        recommendation: str,
    ) -> PromptInjectionPolicyEvaluation:
        """评估高风险 Prompt 注入"""
        return PromptInjectionPolicyEvaluation(
            decision=PromptInjectionPolicyDecision.REJECT,
            confidence=confidence,
            risk_level="high",
            detected_patterns=detected_patterns,
            evidence=evidence,
            recommendation=recommendation,
            should_comment_pr=True,
            force_override_possible=True,
            required_approval_level="admin",
        )

    def _evaluate_medium(
        self,
        confidence: float,
        detected_patterns: list[str],
        evidence: list[str],
        recommendation: str,
    ) -> PromptInjectionPolicyEvaluation:
        """评估中风险 Prompt 注入 - 允许但建议审核"""
        return PromptInjectionPolicyEvaluation(
            decision=PromptInjectionPolicyDecision.REVIEW,
            confidence=confidence,
            risk_level="medium",
            detected_patterns=detected_patterns,
            evidence=evidence,
            recommendation=recommendation,
            should_comment_pr=True,
            force_override_possible=False,
            required_approval_level="review",
        )

    def _evaluate_low(
        self,
        confidence: float,
        detected_patterns: list[str],
        evidence: list[str],
        recommendation: str,
    ) -> PromptInjectionPolicyEvaluation:
        """评估低风险内容 - 允许处理"""
        return PromptInjectionPolicyEvaluation(
            decision=PromptInjectionPolicyDecision.ALLOW,
            confidence=confidence,
            risk_level="low",
            detected_patterns=detected_patterns,
            evidence=evidence,
            recommendation=recommendation,
            should_comment_pr=False,
            force_override_possible=False,
            required_approval_level="none",
        )

    def _create_suspicious_evaluation(
        self,
        risk_level: str,
        confidence: float,
        detected_patterns: list[str],
        evidence: list[str],
        recommendation: str,
    ) -> PromptInjectionPolicyEvaluation:
        """创建可疑内容的评估（未知风险等级）"""
        return PromptInjectionPolicyEvaluation(
            decision=PromptInjectionPolicyDecision.SUSPICIOUS,
            confidence=confidence,
            risk_level=risk_level,
            detected_patterns=detected_patterns,
            evidence=evidence,
            recommendation=f"Unknown risk level: {risk_level}. {recommendation}",
            should_comment_pr=True,
            force_override_possible=False,
            required_approval_level="admin",
        )

    def evaluate_kill_switch_override(
        self,
        current_evaluation: PromptInjectionPolicyEvaluation,
        approved_by: str,
        approval_level: str,
        business_reason: str,
    ) -> PromptInjectionPolicyEvaluation:
        """
        评估 Kill Switch 管理员覆盖
        
        Args:
            current_evaluation: 当前评估结果
            approved_by: 批准者 ID
            approval_level: 批准级别 ("admin", "senior_admin")
            business_reason: 业务原因
            
        Returns:
            PromptInjectionPolicyEvaluation: 覆盖后的评估结果
        """
        # 验证覆盖条件
        if current_evaluation.decision == PromptInjectionPolicyDecision.ALLOW:
            logger.warning(
                f"Kill Switch override attempted on ALLOW decision by {approved_by}. Ignoring."
            )
            return current_evaluation

        if not current_evaluation.force_override_possible:
            logger.warning(
                f"Kill Switch override not allowed for {current_evaluation.risk_level} "
                f"risk level by {approved_by}. Ignoring."
            )
            return current_evaluation

        # 验证权限级别
        required_level = current_evaluation.required_approval_level
        if required_level == "senior_admin" and approval_level != "senior_admin":
            logger.warning(
                f"Kill Switch override denied: {approval_level} insufficient for "
                f"{required_level} requirement by {approved_by}"
            )
            return current_evaluation

        # 覆盖成功
        logger.warning(
            f"[PromptInjectionPolicyGateway] Kill Switch override approved. "
            f"Approved by: {approved_by}, Level: {approval_level}, "
            f"Reason: {business_reason}, Original risk: {current_evaluation.risk_level}"
        )

        # 创建覆盖后的评估结果
        return PromptInjectionPolicyEvaluation(
            decision=PromptInjectionPolicyDecision.ALLOW,
            confidence=current_evaluation.confidence,
            risk_level=current_evaluation.risk_level,
            detected_patterns=current_evaluation.detected_patterns,
            evidence=current_evaluation.evidence,
            recommendation=(
                f"Kill Switch override approved by {approved_by} ({approval_level}). "
                f"Business reason: {business_reason}"
            ),
            should_comment_pr=True,
            force_override_possible=False,
            required_approval_level="none",
        )


def to_pr_comment(evaluation: PromptInjectionPolicyEvaluation) -> str:
    """
    将 Policy 评估转换为 PR Comment
    
    Args:
        evaluation: Prompt 注入 Policy 评估
        
    Returns:
        PR Comment 内容（Markdown 格式）
    """
    if not evaluation.should_comment_pr:
        return ""

    status_emoji = {
        PromptInjectionPolicyDecision.ALLOW: "✅",
        PromptInjectionPolicyDecision.REVIEW: "⚠️",
        PromptInjectionPolicyDecision.REJECT: "🚫",
        PromptInjectionPolicyDecision.SUSPICIOUS: "❓",
    }.get(evaluation.decision, "❓")

    comment = f"""
{status_emoji} **Prompt Injection Detection**

**Status**: {evaluation.decision.value.upper()}
**Risk Level**: {evaluation.risk_level.upper()}
**Confidence**: {evaluation.confidence:.1%}

"""

    if evaluation.detected_patterns:
        comment += "**Detected Patterns**:\n"
        for pattern in evaluation.detected_patterns:
            comment += f"  - {pattern}\n"
        comment += "\n"

    if evaluation.evidence:
        comment += "**Evidence**:\n"
        for item in evaluation.evidence[:3]:  # 限制前 3 个证据
            comment += f"  - {item}\n"
        if len(evaluation.evidence) > 3:
            comment += f"  - ... and {len(evaluation.evidence) - 3} more\n"
        comment += "\n"

    comment += f"**Recommendation**: {evaluation.recommendation}\n"

    if evaluation.required_approval_level != "none":
        comment += (
            f"\n**Approval Required**: {evaluation.required_approval_level} "
            f"(Kill Switch override available)\n"
        )

    return comment


def to_policy_decision_event(
    evaluation: PromptInjectionPolicyEvaluation,
) -> dict[str, Any]:
    """
    将 Policy 评估转换为审计事件
    
    Args:
        evaluation: Prompt 注入 Policy 评估
        
    Returns:
        审计事件字典
    """
    return {
        "action_type": "prompt_injection_policy_decision",
        "decision": evaluation.decision.value,
        "risk_level": evaluation.risk_level,
        "confidence": evaluation.confidence,
        "detected_patterns": evaluation.detected_patterns,
        "evidence_count": len(evaluation.evidence),
        "recommendation": evaluation.recommendation,
        "requires_approval": evaluation.required_approval_level != "none",
        "can_override": evaluation.force_override_possible,
    }
