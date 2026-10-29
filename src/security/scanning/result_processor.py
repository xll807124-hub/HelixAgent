"""
Security Scan Result Processor

职责:
  1. 聚合 CodeQL 和 Gitleaks 扫描结果
  2. 做出 Allow/Block 决策
  3. 生成 PR Comment
  4. 记录审计日志

设计基线: REQ-SEC-003 (Policy Gateway), REQ-OBS-007 (Audit Logs)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from .codeql_scanner import CodeQLFinding, CodeQLResult
from .gitleaks_scanner import GitleaksResult, GitleaksSecret

logger = logging.getLogger(__name__)


class ScanDecision(str, Enum):
    """扫描决策"""
    ALLOW = "allow"           # 允许合并
    BLOCK = "block"           # 阻止合并
    NEUTRAL = "neutral"       # 扫描失败,中立态


@dataclass
class ScanResultSummary:
    """扫描结果摘要"""
    decision: ScanDecision              # 最终决策
    codeql_critical: int               # CRITICAL 漏洞数
    codeql_high: int                   # HIGH 漏洞数
    gitleaks_count: int                # Secret 检测数
    total_issues: int                  # 总问题数
    codeql_findings: list[CodeQLFinding] = field(default_factory=list)
    gitleaks_secrets: list[GitleaksSecret] = field(default_factory=list)


class ScanResultProcessor:
    """
    扫描结果处理器
    
    职责:
      1. 聚合 CodeQL 和 Gitleaks 结果
      2. 应用 Policy Gateway 规则 (严格模式)
      3. 生成 PR Comment 和审计日志
    
    严格模式规则:
      - CRITICAL 漏洞 >= 1 → BLOCK
      - HIGH 漏洞 >= 3 → BLOCK
      - Secret 检测 >= 1 → BLOCK
      - 扫描失败 → NEUTRAL (不阻止, 建议重试)
    """
    
    def process(
        self,
        codeql_result: CodeQLResult,
        gitleaks_result: GitleaksResult,
    ) -> ScanResultSummary:
        """
        处理扫描结果
        
        Args:
            codeql_result: CodeQL 扫描结果
            gitleaks_result: Gitleaks 扫描结果
        
        Returns:
            ScanResultSummary: 处理后的结果摘要
        """
        
        # 计数
        codeql_critical = codeql_result.critical_count if codeql_result.success else 0
        codeql_high = codeql_result.high_count if codeql_result.success else 0
        gitleaks_count = len(gitleaks_result.secrets) if gitleaks_result.success else 0
        
        # 做出决策 (严格模式)
        decision = self._make_decision(
            codeql_result, gitleaks_result,
            codeql_critical, codeql_high, gitleaks_count
        )
        
        logger.info(
            f"[ScanProcessor] 决策: {decision} "
            f"(CRITICAL: {codeql_critical}, HIGH: {codeql_high}, Secret: {gitleaks_count})"
        )
        
        return ScanResultSummary(
            decision=decision,
            codeql_critical=codeql_critical,
            codeql_high=codeql_high,
            gitleaks_count=gitleaks_count,
            total_issues=codeql_critical + codeql_high + gitleaks_count,
            codeql_findings=codeql_result.findings if codeql_result.success else [],
            gitleaks_secrets=gitleaks_result.secrets if gitleaks_result.success else [],
        )
    
    @staticmethod
    def _make_decision(
        codeql_result: CodeQLResult,
        gitleaks_result: GitleaksResult,
        codeql_critical: int,
        codeql_high: int,
        gitleaks_count: int,
    ) -> ScanDecision:
        """
        做出决策
        
        严格模式:
          - 任何 Secret 检测 → BLOCK
          - CRITICAL >= 1 → BLOCK
          - HIGH >= 3 → BLOCK
          - 扫描失败 → NEUTRAL
          - 否则 → ALLOW
        """
        
        # 密钥检测 (任何 Secret 都拦截)
        if gitleaks_count > 0:
            return ScanDecision.BLOCK
        
        # 严重漏洞 (CRITICAL >= 1 或 HIGH >= 3)
        if codeql_critical >= 1:
            return ScanDecision.BLOCK
        if codeql_high >= 3:
            return ScanDecision.BLOCK

        # Preserve confirmed findings even when the other scanner failed.
        if not codeql_result.success or not gitleaks_result.success:
            return ScanDecision.NEUTRAL
        
        return ScanDecision.ALLOW
    
    def generate_pr_comment(
        self,
        summary: ScanResultSummary,
        findings_detail_url: str = "",
    ) -> str:
        """
        生成 PR Comment
        
        Args:
            summary: 扫描结果摘要
            findings_detail_url: 完整报告 URL
        
        Returns:
            PR Comment markdown 文本
        """
        
        if summary.decision == ScanDecision.ALLOW:
            return self._generate_pass_comment(summary, findings_detail_url)
        elif summary.decision == ScanDecision.BLOCK:
            return self._generate_fail_comment(summary, findings_detail_url)
        else:  # NEUTRAL
            return self._generate_neutral_comment(summary)
    
    @staticmethod
    def _generate_pass_comment(
        summary: ScanResultSummary,
        findings_detail_url: str,
    ) -> str:
        """生成通过的 PR Comment"""
        
        comment = """## ✅ Security Scan Passed

所有安全检查已通过,此 PR 可以合并。

| 检查项 | 结果 |
|--------|------|
| CodeQL (SAST) | ✅ 无漏洞 |
| Gitleaks (Secret) | ✅ 无密钥泄露 |

"""
        
        if findings_detail_url:
            comment += f"[查看完整报告]({findings_detail_url})\n"
        
        return comment
    
    @staticmethod
    def _generate_fail_comment(
        summary: ScanResultSummary,
        findings_detail_url: str,
    ) -> str:
        """生成失败的 PR Comment"""
        
        comment = """## ❌ Security Scan Failed - Cannot Merge

🚫 **此 PR 包含安全问题,无法合并**

"""
        
        # CodeQL 结果
        if summary.codeql_findings:
            comment += "### 🔍 CodeQL (SAST) 检查结果\n\n"
            
            for finding in summary.codeql_findings[:10]:  # 限制显示前 10 个
                severity_emoji = {
                    "critical": "🔴",
                    "high": "🟠",
                    "medium": "🟡",
                    "low": "🟢",
                    "note": "ℹ️",
                }
                emoji = severity_emoji.get(finding.severity, "❓")
                
                comment += f"""
{emoji} **[{finding.severity.upper()}]** {finding.rule_id}

**文件**: `{finding.file_path}:{finding.line_start}`

**问题**: {finding.message}

**修复建议**: {finding.remediation}

---
"""
            
            if len(summary.codeql_findings) > 10:
                comment += f"*还有 {len(summary.codeql_findings) - 10} 个漏洞,请查看完整报告*\n\n"
        
        # Gitleaks 结果
        if summary.gitleaks_secrets:
            comment += "### 🔐 Gitleaks (Secret) 检查结果\n\n"
            
            for secret in summary.gitleaks_secrets:
                comment += f"""
**❌ 密钥泄露**: {secret.secret_type.value}

**文件**: `{secret.file_path}:{secret.line_number}`

**密钥类型**: {secret.rule_description}

**修复步骤**:
1. 立即删除密钥内容
2. 如果密钥已被他人访问,请在 Secrets 管理系统中轮换该密钥
3. 使用以下命令重写历史:
   ```bash
   git filter-branch --tree-filter 'rm -f {secret.file_path}' HEAD
   ```

---
"""
        
        # 最后的提示
        comment += """
### 📋 需要修复

请根据上述建议修复所有安全问题后,重新推送代码。

"""
        
        if findings_detail_url:
            comment += f"[查看完整扫描报告]({findings_detail_url})\n"
        
        comment += """
⚠️ **注意**: 如果有正当业务理由需要覆盖此检查,
仅平台管理员可通过 Break-Glass 流程 (Kill Switch) 审批。
[联系 Admin](link)
"""
        
        return comment
    
    @staticmethod
    def _generate_neutral_comment(summary: ScanResultSummary) -> str:
        """生成扫描失败的 PR Comment"""
        
        return """## ⚠️ Security Scan Failed - Retry Required

扫描过程中发生错误,请稍后重试。

| 检查项 | 状态 |
|--------|------|
| CodeQL (SAST) | ⚠️ 错误 |
| Gitleaks (Secret) | ⚠️ 错误 |

**建议行动**:
1. 确保仓库是有效的 Git 目录
2. 稍后重新推送以重新触发扫描
3. 如果问题持续,请联系 Admin

[重试扫描](link) | [查看日志](link)
"""
