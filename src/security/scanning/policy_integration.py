"""
Security Scanning Policy Gateway Integration

职责:
  1. 将扫描结果与 Policy Gateway 集成
  2. 生成 Policy Gateway 决策
  3. 控制 PR 检查状态
  4. 支持 Break-Glass 覆盖 (通过 Kill Switch)

设计基线: REQ-SEC-003 (Policy Gateway), REQ-SEC-009 (Kill Switch)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from .result_processor import ScanResultSummary, ScanDecision

logger = logging.getLogger(__name__)


class PolicyDecision(str, Enum):
    """Policy Gateway 决策"""
    APPROVE = "approve"           # PR Check PASS (绿色)
    REJECT = "reject"             # PR Check FAIL (红色)
    NEUTRAL = "neutral"           # 扫描失败,不阻止 (黄色)


@dataclass
class ScanPolicyDecision:
    """扫描策略决策"""
    decision: PolicyDecision               # 最终决策
    reason: str                            # 决策理由
    recommended_action: str                # 推荐行动
    should_comment_pr: bool                # 是否生成 PR Comment
    force_override_possible: bool          # 是否可通过 Kill Switch 覆盖


class ScanPolicyGateway:
    """
    扫描策略网关
    
    将 ScanResultSummary 转化为 Policy Gateway 决策。
    
    决策规则 (严格模式):
      - ScanDecision.ALLOW → PolicyDecision.APPROVE
      - ScanDecision.BLOCK → PolicyDecision.REJECT
      - ScanDecision.NEUTRAL → PolicyDecision.NEUTRAL
    
    Break-Glass 覆盖:
      - REJECT 可通过 Kill Switch M3 (三级审批) 覆盖
      - 所有覆盖决策记入审计日志 (永久不可删除)
    """
    
    def evaluate(self, summary: ScanResultSummary) -> ScanPolicyDecision:
        """
        评估扫描结果,生成策略决策
        
        Args:
            summary: 扫描结果摘要
        
        Returns:
            ScanPolicyDecision: 策略决策
        """
        
        if summary.decision == ScanDecision.ALLOW:
            return self._approve_decision(summary)
        elif summary.decision == ScanDecision.BLOCK:
            return self._reject_decision(summary)
        else:  # NEUTRAL
            return self._neutral_decision(summary)
    
    @staticmethod
    def _approve_decision(summary: ScanResultSummary) -> ScanPolicyDecision:
        """
        ALLOW 决策 → APPROVE
        """
        return ScanPolicyDecision(
            decision=PolicyDecision.APPROVE,
            reason="All security checks passed",
            recommended_action="PR can be merged",
            should_comment_pr=True,
            force_override_possible=False,
        )
    
    @staticmethod
    def _reject_decision(summary: ScanResultSummary) -> ScanPolicyDecision:
        """
        BLOCK 决策 → REJECT
        """
        
        issues = []
        if summary.codeql_critical > 0:
            issues.append(f"{summary.codeql_critical} CRITICAL vulnerabilities")
        if summary.codeql_high >= 3:
            issues.append(f"{summary.codeql_high} HIGH vulnerabilities")
        if summary.gitleaks_count > 0:
            issues.append(f"{summary.gitleaks_count} secrets detected")
        
        reason = f"Security issues found: {', '.join(issues)}"
        
        return ScanPolicyDecision(
            decision=PolicyDecision.REJECT,
            reason=reason,
            recommended_action=(
                "Fix all security issues and resubmit PR. "
                "If business-justified override needed, contact Admin for Kill Switch approval."
            ),
            should_comment_pr=True,
            force_override_possible=True,  # 可通过 Kill Switch M3 覆盖
        )
    
    @staticmethod
    def _neutral_decision(summary: ScanResultSummary) -> ScanPolicyDecision:
        """
        NEUTRAL 决策 → NEUTRAL (扫描失败)
        """
        return ScanPolicyDecision(
            decision=PolicyDecision.NEUTRAL,
            reason="Security scan failed or inconclusive",
            recommended_action="Please retry the scan or contact Admin if issues persist",
            should_comment_pr=True,
            force_override_possible=False,
        )
    
    def evaluate_kill_switch_override(
        self,
        summary: ScanResultSummary,
        approved_by_admin: bool,
        audit_note: str,
    ) -> ScanPolicyDecision:
        """
        评估 Kill Switch 覆盖请求
        
        Args:
            summary: 扫描结果摘要
            approved_by_admin: 是否已获得 Admin 三级审批
            audit_note: 审计备注 (业务理由)
        
        Returns:
            ScanPolicyDecision: 覆盖后的决策
        
        前置条件:
            - 必须是 REJECT 决策
            - 必须有 Admin 三级审批
            - 所有操作记入审计日志
        """
        
        if summary.decision != ScanDecision.BLOCK:
            return ScanPolicyDecision(
                decision=PolicyDecision.NEUTRAL,
                reason="Kill Switch override only applicable to REJECT decisions",
                recommended_action="No action needed",
                should_comment_pr=False,
                force_override_possible=False,
            )
        
        if not approved_by_admin:
            return ScanPolicyDecision(
                decision=PolicyDecision.REJECT,
                reason="Kill Switch override requires Admin three-level approval",
                recommended_action="Contact Admin (TechLead + SecurityLead + Manager)",
                should_comment_pr=False,
                force_override_possible=True,
            )
        
        logger.warning(
            f"[ScanPolicyGateway] Kill Switch override approved. "
            f"Audit note: {audit_note}"
        )
        
        return ScanPolicyDecision(
            decision=PolicyDecision.APPROVE,
            reason=f"Kill Switch override approved by Admin. Note: {audit_note}",
            recommended_action="PR can now be merged (override recorded in audit log)",
            should_comment_pr=True,
            force_override_possible=False,
        )


def to_github_check_status(policy_decision: ScanPolicyDecision) -> dict:
    """
    将 Policy 决策转换为 GitHub Check Run 状态
    
    GitHub Check Run 状态:
      - "completed" with conclusion "success"   → 绿色 ✅
      - "completed" with conclusion "failure"   → 红色 ❌
      - "completed" with conclusion "neutral"   → 黄色 ⚠️
    
    Args:
        policy_decision: Policy Gateway 决策
    
    Returns:
        GitHub Check Run 配置字典
    """
    
    conclusion_map = {
        PolicyDecision.APPROVE: "success",
        PolicyDecision.REJECT: "failure",
        PolicyDecision.NEUTRAL: "neutral",
    }
    
    return {
        "status": "completed",
        "conclusion": conclusion_map[policy_decision.decision],
        "title": "Security Scan",
        "summary": policy_decision.reason,
        "text": policy_decision.recommended_action,
    }
