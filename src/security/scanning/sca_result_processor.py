"""
SCA Result Processor - 结果处理与 PR Comment 生成

职责:
  1. 聚合 npm 和 pip 扫描结果
  2. 做出 Allow/Block 决策
  3. 生成 PR Comment
  4. 记录审计日志
"""

from __future__ import annotations

import logging

from .sca_orchestrator import SCADecision, SCAResultSummary

logger = logging.getLogger(__name__)


class SCAResultProcessor:
    """
    SCA 结果处理器
    
    职责:
      1. 聚合结果
      2. 生成 PR Comment (包含所有漏洞详情)
      3. 提供可执行的修复建议
    """
    
    def generate_pr_comment(
        self,
        summary: SCAResultSummary,
        findings_detail_url: str = "",
    ) -> str:
        """
        生成 PR Comment
        
        Args:
            summary: SCA 结果摘要
            findings_detail_url: 完整报告 URL
        
        Returns:
            PR Comment markdown 文本
        """
        
        if summary.decision == SCADecision.ALLOW:
            return self._generate_pass_comment(summary, findings_detail_url)
        elif summary.decision == SCADecision.BLOCK:
            return self._generate_fail_comment(summary, findings_detail_url)
        else:  # NEUTRAL
            return self._generate_neutral_comment(summary)
    
    @staticmethod
    def _generate_pass_comment(
        summary: SCAResultSummary,
        findings_detail_url: str,
    ) -> str:
        """生成通过的 PR Comment"""
        
        comment = """## ✅ Dependency Scan Passed

所有依赖漏洞检查已通过。

| 检查项 | 结果 |
|--------|------|
| NPM 依赖 (package.json) | ✅ 无漏洞 |
| Python 依赖 (requirements.txt) | ✅ 无漏洞 |

此 PR 可以合并。

"""
        
        if findings_detail_url:
            comment += f"[查看完整报告]({findings_detail_url})\n"
        
        return comment
    
    @staticmethod
    def _generate_fail_comment(
        summary: SCAResultSummary,
        findings_detail_url: str,
    ) -> str:
        """生成失败的 PR Comment"""
        
        comment = """## ❌ Dependency Scan Failed - Cannot Merge

🚫 **此 PR 包含已知漏洞的依赖,无法合并**

"""
        
        # NPM 结果
        if summary.npm_findings:
            comment += "### 📦 NPM 依赖 (JavaScript/TypeScript)\n\n"
            
            for vuln in summary.npm_findings[:10]:  # 限制显示前 10 个
                severity_emoji = {
                    "critical": "🔴",
                    "high": "🟠",
                    "medium": "🟡",
                    "low": "🟢",
                }
                emoji = severity_emoji.get(vuln.severity.value, "❓")
                
                comment += f"""
{emoji} **[{vuln.severity.value.upper()}]** {vuln.package}

**当前版本**: {vuln.current_version}  
**修复版本**: {vuln.fix_version}  
**问题**: {vuln.description}

"""
            
            if len(summary.npm_findings) > 10:
                comment += f"*还有 {len(summary.npm_findings) - 10} 个漏洞*\n\n"
        
        # Python 结果
        if summary.pip_findings:
            comment += "### 🐍 Python 依赖\n\n"
            
            for vuln in summary.pip_findings[:10]:  # 限制显示前 10 个
                severity_emoji = {
                    "critical": "🔴",
                    "high": "🟠",
                    "medium": "🟡",
                    "low": "🟢",
                }
                emoji = severity_emoji.get(vuln.severity.value, "❓")
                
                comment += f"""
{emoji} **[{vuln.severity.value.upper()}]** {vuln.package}

**当前版本**: {vuln.current_version}  
**修复版本**: {vuln.fix_version}  
**问题**: {vuln.description}

"""
            
            if len(summary.pip_findings) > 10:
                comment += f"*还有 {len(summary.pip_findings) - 10} 个漏洞*\n\n"
        
        # 修复步骤
        comment += """### 修复步骤

1. **更新依赖到最新安全版本**

   对于 NPM:
   ```bash
   npm audit fix
   npm update
   ```
   
   对于 Python:
   ```bash
   pip install --upgrade package-name
   ```

2. **本地验证应用功能**

   ```bash
   npm test  # 或 Python 测试
   ```

3. **提交更新后的依赖锁定文件**

   ```bash
   git add package-lock.json  # 或 requirements.txt
   git commit -m "chore: update vulnerable dependencies"
   ```

---

"""
        
        if findings_detail_url:
            comment += f"[查看完整扫描报告]({findings_detail_url})\n"
        
        return comment
    
    @staticmethod
    def _generate_neutral_comment(summary: SCAResultSummary) -> str:
        """生成扫描失败的 PR Comment"""
        
        return """## ⚠️ Dependency Scan Failed - Retry Required

依赖扫描过程中发生错误,请稍后重试。

**建议行动**:
1. 确保仓库包含正确的 package.json 或 requirements.txt
2. 稍后重新推送以重新触发扫描
3. 如果问题持续,请联系 Admin

[重试扫描](link) | [查看日志](link)
"""
