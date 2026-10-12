"""
Security Scanning Gateway

对齐设计文档: REQ-SEC-003 Policy Gateway, REQ-SEC-004 SAST/Secret Scanning

核心组件:
  - ScanningOrchestrator: 异步编排 CodeQL + Gitleaks 扫描
  - CodeQLScanner: CodeQL 静态分析集成
  - GitleaksScanner: Gitleaks 密钥检测集成
  - ScanResultProcessor: 结果聚合与决策
  - ScanPolicyGateway: 扫描结果策略检查

设计原则:
  - 异步执行: 扫描在后台进行,不阻塞 PR 提交
  - Event 驱动: 扫描完成后发送 Event,触发 Policy Gateway
  - 严格模式: 高危漏洞和 Secret 无法豁免,只能通过 Kill Switch
  - 可观测性: 所有结果记入审计日志 (REQ-OBS-007)
"""

from .orchestrator import ScanningOrchestrator
from .codeql_scanner import CodeQLScanner, CodeQLResult
from .gitleaks_scanner import GitleaksScanner, GitleaksResult
from .result_processor import ScanResultProcessor, ScanDecision, ScanSeverity
from .policy_integration import ScanPolicyGateway

__all__ = [
    "ScanningOrchestrator",
    "CodeQLScanner",
    "GitleaksScanner",
    "ScanResultProcessor",
    "ScanDecision",
    "ScanSeverity",
    "ScanPolicyGateway",
]
