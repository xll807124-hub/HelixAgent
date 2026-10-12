"""
Security Scanning Gateway

对齐设计文档: REQ-SEC-003 Policy Gateway, REQ-SEC-004 SAST/Secret Scanning

核心组件:
  === SAST + Secret Scanning ===
  - ScanningOrchestrator: 异步编排 CodeQL + Gitleaks 扫描
  - CodeQLScanner: CodeQL 静态分析集成
  - GitleaksScanner: Gitleaks 密钥检测集成
  - ScanResultProcessor: 结果聚合与决策
  - ScanPolicyGateway: 扫描结果策略检查

  === SCA (Dependency) Scanning ===
  - SCAOrchestrator: 异步编排 npm + pip-audit 扫描
  - NPMScanner: npm audit JavaScript 依赖扫描
  - PipScanner: pip-audit Python 依赖扫描
  - SCAResultProcessor: 结果聚合与 PR Comment 生成

设计原则:
  - 异步执行: 扫描在后台进行,不阻塞 PR 提交
  - Event 驱动: 扫描完成后发送 Event,触发 Policy Gateway
  - 严格模式: 所有安全问题都无法豁免,只能通过 Kill Switch
  - 可观测性: 所有结果记入审计日志 (REQ-OBS-007)
"""

from .codeql_scanner import CodeQLResult, CodeQLScanner, ScanSeverity
from .gitleaks_scanner import GitleaksResult, GitleaksScanner
from .npm_scanner import NPMScanner, SCAResult, Vulnerability, VulnerabilitySeverity
from .orchestrator import ScanningOrchestrator
from .pip_scanner import PipScanner
from .policy_integration import ScanPolicyGateway
from .result_processor import ScanDecision, ScanResultProcessor
from .sca_orchestrator import SCADecision as SCADecisionEnum
from .sca_orchestrator import SCAOrchestrator, SCAResultSummary
from .sca_result_processor import SCAResultProcessor

__all__ = [
    # SAST + Secret
    "ScanningOrchestrator",
    "CodeQLScanner",
    "CodeQLResult",
    "GitleaksScanner",
    "GitleaksResult",
    "ScanResultProcessor",
    "ScanDecision",
    "ScanSeverity",
    "ScanPolicyGateway",
    
    # SCA
    "NPMScanner",
    "PipScanner",
    "SCAOrchestrator",
    "SCAResultSummary",
    "SCAResultProcessor",
    "SCADecisionEnum",
    "Vulnerability",
    "VulnerabilitySeverity",
    "SCAResult",
]
