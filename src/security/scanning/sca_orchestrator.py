"""
SCA Orchestrator - 依赖扫描编排器

职责:
  1. 检测项目类型 (Python/JavaScript/混合)
  2. 并行执行 npm 和 pip 扫描
  3. 聚合结果
  4. 与 Policy Gateway 集成

设计基线: REQ-RT-003 (Event Schema), REQ-OBS-007 (Audit Logs)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from .npm_scanner import NPMScanner, Vulnerability, VulnerabilitySeverity
from .npm_scanner import SCAResult as NPMResult
from .pip_scanner import PipScanner
from .pip_scanner import SCAResult as PipResult

logger = logging.getLogger(__name__)


class SCADecision(str, Enum):
    """SCA 决策"""
    ALLOW = "allow"
    BLOCK = "block"
    NEUTRAL = "neutral"


@dataclass
class SCAResultSummary:
    """SCA 结果摘要"""
    decision: SCADecision
    npm_vulnerabilities: int
    pip_vulnerabilities: int
    total_vulnerabilities: int
    critical_count: int
    high_count: int
    npm_findings: list[Vulnerability] = field(default_factory=list)
    pip_findings: list[Vulnerability] = field(default_factory=list)


class SCAOrchestrator:
    """
    SCA 编排器
    
    异步编排 npm 和 pip 扫描,支持:
      - 检测项目类型 (Python/JS/混合)
      - 并行扫描 (加快速度)
      - 超时保护
      - 失败恢复 (返回 NEUTRAL)
    """
    
    def __init__(
        self,
        npm_scanner: NPMScanner | None = None,
        pip_scanner: PipScanner | None = None,
    ):
        """
        初始化 Orchestrator
        
        Args:
            npm_scanner: NPM 扫描器 (默认自动初始化)
            pip_scanner: Pip 扫描器 (默认自动初始化)
        """
        self.npm_scanner = npm_scanner or NPMScanner()
        self.pip_scanner = pip_scanner or PipScanner()
        self.scan_states: dict[str, str] = {}
    
    async def scan_pr(
        self,
        task_id: str,
        repo_path: str,
        pr_number: int,
    ) -> SCAResultSummary:
        """
        扫描 PR (快速模式)
        
        Args:
            task_id: 任务 ID
            repo_path: 仓库路径
            pr_number: PR 编号
        
        Returns:
            SCAResultSummary: 扫描结果摘要
        """
        
        scan_id = str(uuid4())
        logger.info(
            f"[SCAOrchestrator] 开始 PR 扫描: scan_id={scan_id}, "
            f"task_id={task_id}, pr={pr_number}"
        )
        
        try:
            # 并行扫描
            npm_result, pip_result = await asyncio.gather(
                self.npm_scanner.scan(repo_path, deep_scan=False),
                self.pip_scanner.scan(repo_path, deep_scan=False),
                return_exceptions=False
            )
            
            # 处理结果
            summary = self._process_results(npm_result, pip_result)
            
            logger.info(
                f"[SCAOrchestrator] PR 扫描完成: scan_id={scan_id}, "
                f"decision={summary.decision}, issues={summary.total_vulnerabilities}"
            )
            
            return summary
        
        except Exception as e:
            logger.error(f"[SCAOrchestrator] PR 扫描异常: {e}")
            return SCAResultSummary(
                decision=SCADecision.NEUTRAL,
                npm_vulnerabilities=0,
                pip_vulnerabilities=0,
                total_vulnerabilities=0,
                critical_count=0,
                high_count=0,
            )
    
    async def full_scan(
        self,
        task_id: str,
        repo_path: str,
    ) -> SCAResultSummary:
        """
        完整扫描 (深度模式,用于定期全量扫描)
        
        Args:
            task_id: 任务 ID
            repo_path: 仓库路径
        
        Returns:
            SCAResultSummary: 扫描结果摘要
        """
        
        scan_id = str(uuid4())
        logger.info(
            f"[SCAOrchestrator] 开始完整扫描: scan_id={scan_id}, "
            f"task_id={task_id}"
        )
        
        try:
            # 并行深度扫描
            npm_result, pip_result = await asyncio.gather(
                self.npm_scanner.scan(repo_path, deep_scan=True),
                self.pip_scanner.scan(repo_path, deep_scan=True),
                return_exceptions=False
            )
            
            # 处理结果
            summary = self._process_results(npm_result, pip_result)
            
            logger.info(
                f"[SCAOrchestrator] 完整扫描完成: scan_id={scan_id}, "
                f"decision={summary.decision}, issues={summary.total_vulnerabilities}"
            )
            
            return summary
        
        except Exception as e:
            logger.error(f"[SCAOrchestrator] 完整扫描异常: {e}")
            return SCAResultSummary(
                decision=SCADecision.NEUTRAL,
                npm_vulnerabilities=0,
                pip_vulnerabilities=0,
                total_vulnerabilities=0,
                critical_count=0,
                high_count=0,
            )
    
    @staticmethod
    def _process_results(
        npm_result: NPMResult,
        pip_result: PipResult,
    ) -> SCAResultSummary:
        """
        处理扫描结果
        
        决策规则 (严格模式):
          - 任何漏洞 → BLOCK
          - 扫描失败 → NEUTRAL
          - 否则 → ALLOW
        """
        
        npm_vulns = npm_result.vulnerabilities if npm_result.success else []
        pip_vulns = pip_result.vulnerabilities if pip_result.success else []
        
        all_vulns = npm_vulns + pip_vulns
        
        # 统计
        critical_count = sum(
            1 for v in all_vulns if v.severity == VulnerabilitySeverity.CRITICAL
        )
        high_count = sum(
            1 for v in all_vulns if v.severity == VulnerabilitySeverity.HIGH
        )
        
        # 决策
        if len(all_vulns) > 0:
            decision = SCADecision.BLOCK
        elif not npm_result.success or not pip_result.success:
            decision = SCADecision.NEUTRAL
        else:
            decision = SCADecision.ALLOW
        
        return SCAResultSummary(
            decision=decision,
            npm_vulnerabilities=len(npm_vulns),
            pip_vulnerabilities=len(pip_vulns),
            total_vulnerabilities=len(all_vulns),
            critical_count=critical_count,
            high_count=high_count,
            npm_findings=npm_vulns,
            pip_findings=pip_vulns,
        )
