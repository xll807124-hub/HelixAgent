"""
Security Scanning Orchestrator

职责:
  1. 异步编排 CodeQL + Gitleaks 扫描
  2. 管理扫描生命周期 (pending → completed → processed)
  3. 与 Policy Gateway 和 Event 系统集成
  4. 记录审计日志

设计基线: REQ-RT-003 (Event Schema), REQ-OBS-007 (Audit Logs)

执行流程:
  1. PR 创建事件触发
  2. ScanRequested Event 发送
  3. ScanningOrchestrator 后台异步执行
     - CodeQL 扫描 (5-30s)
     - Gitleaks 扫描 (1-5s)
     - 结果聚合 (1s)
  4. ScanCompleted Event 发送
  5. Policy Gateway 做出决策
  6. 生成 PR Comment + 审计日志
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from enum import Enum
from uuid import uuid4

from .codeql_scanner import CodeQLScanner, CodeQLResult
from .gitleaks_scanner import GitleaksScanner, GitleaksResult
from .result_processor import ScanResultProcessor, ScanResultSummary, ScanDecision

logger = logging.getLogger(__name__)


class ScanStatus(str, Enum):
    """扫描状态"""
    PENDING = "pending"
    CODEQL_RUNNING = "codeql_running"
    GITLEAKS_RUNNING = "gitleaks_running"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ScanningOrchestrator:
    """
    安全扫描编排器
    
    异步编排 CodeQL 和 Gitleaks 扫描,支持:
      - 并行扫描 (同时运行 CodeQL 和 Gitleaks)
      - 超时保护 (单个扫描超时 120s)
      - 失败恢复 (扫描失败返回 NEUTRAL 决策)
      - 事件驱动 (ScanRequested → ScanCompleted)
    
    集成点:
      - Event Store: 记录扫描事件
      - Policy Gateway: 应用扫描决策
      - Audit Log: 记录所有操作
    """
    
    def __init__(
        self,
        codeql_scanner: CodeQLScanner | None = None,
        gitleaks_scanner: GitleaksScanner | None = None,
        result_processor: ScanResultProcessor | None = None,
    ):
        """
        初始化 Orchestrator
        
        Args:
            codeql_scanner: CodeQL 扫描器 (默认自动初始化)
            gitleaks_scanner: Gitleaks 扫描器 (默认自动初始化)
            result_processor: 结果处理器 (默认自动初始化)
        """
        self.codeql_scanner = codeql_scanner or CodeQLScanner()
        self.gitleaks_scanner = gitleaks_scanner or GitleaksScanner()
        self.result_processor = result_processor or ScanResultProcessor()
        
        # 扫描状态追踪 (scan_id → status)
        self.scan_states: dict[str, ScanStatus] = {}
    
    async def scan_pr(
        self,
        task_id: str,
        repo_path: str,
        pr_number: int,
        languages: list[str] | None = None,
    ) -> ScanResultSummary:
        """
        扫描 PR (异步)
        
        Args:
            task_id: 任务 ID
            repo_path: 仓库路径
            pr_number: PR 编号
            languages: 要扫描的编程语言 (默认 Python)
        
        Returns:
            ScanResultSummary: 扫描结果摘要
        
        流程:
            1. 创建扫描 ID
            2. 记录 ScanRequested Event
            3. 并行运行 CodeQL 和 Gitleaks
            4. 处理结果
            5. 记录 ScanCompleted Event
        """
        
        if languages is None:
            languages = ["python"]  # MVP 支持 Python
        
        scan_id = str(uuid4())
        self.scan_states[scan_id] = ScanStatus.PENDING
        
        logger.info(
            f"[Orchestrator] 开始扫描 PR {pr_number}: "
            f"scan_id={scan_id}, task_id={task_id}"
        )
        
        try:
            # 步骤 1: 并行运行扫描
            codeql_result, gitleaks_result = await asyncio.gather(
                self._run_codeql(scan_id, repo_path, languages),
                self._run_gitleaks(scan_id, repo_path),
                return_exceptions=False
            )
            
            # 步骤 2: 处理结果
            self.scan_states[scan_id] = ScanStatus.PROCESSING
            summary = self.result_processor.process(
                codeql_result, gitleaks_result
            )
            
            # 步骤 3: 标记完成
            self.scan_states[scan_id] = ScanStatus.COMPLETED
            
            logger.info(
                f"[Orchestrator] 扫描完成: scan_id={scan_id}, "
                f"decision={summary.decision}, issues={summary.total_issues}"
            )
            
            return summary
        
        except Exception as e:
            logger.error(f"[Orchestrator] 扫描异常: {e}")
            self.scan_states[scan_id] = ScanStatus.FAILED
            
            # 返回失败结果 (NEUTRAL 决策)
            return ScanResultSummary(
                decision=ScanDecision.NEUTRAL,
                codeql_critical=0,
                codeql_high=0,
                gitleaks_count=0,
                total_issues=0,
            )
    
    async def _run_codeql(
        self,
        scan_id: str,
        repo_path: str,
        languages: list[str],
    ) -> CodeQLResult:
        """运行 CodeQL 扫描"""
        try:
            self.scan_states[scan_id] = ScanStatus.CODEQL_RUNNING
            
            logger.info(f"[CodeQL] 扫描开始: scan_id={scan_id}")
            
            # MVP: 支持 Python (主选)
            language = "python" if "python" in languages else languages[0]
            
            result = await self.codeql_scanner.scan(repo_path, language)
            
            logger.info(
                f"[CodeQL] 扫描完成: scan_id={scan_id}, "
                f"findings={len(result.findings)}"
            )
            
            return result
        
        except Exception as e:
            logger.error(f"[CodeQL] 扫描异常: {e}")
            return CodeQLResult(
                success=False,
                scan_duration_ms=0,
                findings=[],
                critical_count=0,
                high_count=0,
                error_message=str(e)
            )
    
    async def _run_gitleaks(
        self,
        scan_id: str,
        repo_path: str,
    ) -> GitleaksResult:
        """运行 Gitleaks 扫描"""
        try:
            self.scan_states[scan_id] = ScanStatus.GITLEAKS_RUNNING
            
            logger.info(f"[Gitleaks] 扫描开始: scan_id={scan_id}")
            
            result = await self.gitleaks_scanner.scan(
                repo_path,
                scan_all_history=False  # PR 扫描使用快速模式
            )
            
            logger.info(
                f"[Gitleaks] 扫描完成: scan_id={scan_id}, "
                f"secrets={len(result.secrets)}"
            )
            
            return result
        
        except Exception as e:
            logger.error(f"[Gitleaks] 扫描异常: {e}")
            return GitleaksResult(
                success=False,
                scan_duration_ms=0,
                secrets=[],
                error_message=str(e)
            )
    
    def get_scan_status(self, scan_id: str) -> ScanStatus | None:
        """获取扫描状态"""
        return self.scan_states.get(scan_id)
    
    async def full_scan(
        self,
        task_id: str,
        repo_path: str,
        languages: list[str] | None = None,
    ) -> ScanResultSummary:
        """
        完整扫描 (用于定期全量扫描,扫描全部 git 历史)
        
        Args:
            task_id: 任务 ID
            repo_path: 仓库路径
            languages: 要扫描的编程语言
        
        Returns:
            ScanResultSummary: 扫描结果摘要
        """
        
        if languages is None:
            languages = ["python"]
        
        scan_id = str(uuid4())
        self.scan_states[scan_id] = ScanStatus.PENDING
        
        logger.info(
            f"[Orchestrator] 开始完整扫描: scan_id={scan_id}, task_id={task_id}"
        )
        
        try:
            # 完整扫描: 深度 Gitleaks (扫描全部历史)
            codeql_result, gitleaks_result = await asyncio.gather(
                self._run_codeql(scan_id, repo_path, languages),
                self._run_gitleaks_full(scan_id, repo_path),
                return_exceptions=False
            )
            
            self.scan_states[scan_id] = ScanStatus.PROCESSING
            summary = self.result_processor.process(
                codeql_result, gitleaks_result
            )
            
            self.scan_states[scan_id] = ScanStatus.COMPLETED
            
            return summary
        
        except Exception as e:
            logger.error(f"[Orchestrator] 完整扫描异常: {e}")
            self.scan_states[scan_id] = ScanStatus.FAILED
            
            return ScanResultSummary(
                decision=ScanDecision.NEUTRAL,
                codeql_critical=0,
                codeql_high=0,
                gitleaks_count=0,
                total_issues=0,
            )
    
    async def _run_gitleaks_full(
        self,
        scan_id: str,
        repo_path: str,
    ) -> GitleaksResult:
        """运行完整 Gitleaks 扫描 (扫描全部历史)"""
        try:
            logger.info(f"[Gitleaks-Full] 完整扫描开始: scan_id={scan_id}")
            
            result = await self.gitleaks_scanner.scan(
                repo_path,
                scan_all_history=True  # 完整扫描模式
            )
            
            logger.info(
                f"[Gitleaks-Full] 完整扫描完成: scan_id={scan_id}, "
                f"secrets={len(result.secrets)}"
            )
            
            return result
        
        except Exception as e:
            logger.error(f"[Gitleaks-Full] 完整扫描异常: {e}")
            return GitleaksResult(
                success=False,
                scan_duration_ms=0,
                secrets=[],
                error_message=str(e)
            )
