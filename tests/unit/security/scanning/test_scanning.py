"""
Unit tests for Security Scanning Gateway

测试覆盖:
  - CodeQL Scanner
  - Gitleaks Scanner
  - Result Processor (决策逻辑)
  - Orchestrator (异步编排)
  - Policy Integration (策略决策)
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

from src.security.scanning.codeql_scanner import (
    CodeQLScanner, CodeQLResult, CodeQLFinding, ScanSeverity
)
from src.security.scanning.gitleaks_scanner import (
    GitleaksScanner, GitleaksResult, GitleaksSecret, SecretType
)
from src.security.scanning.result_processor import (
    ScanResultProcessor, ScanResultSummary, ScanDecision
)
from src.security.scanning.orchestrator import (
    ScanningOrchestrator, ScanStatus
)
from src.security.scanning.policy_integration import (
    ScanPolicyGateway, PolicyDecision, to_github_check_status
)


class TestCodeQLScanner:
    """CodeQL Scanner 单元测试"""
    
    def test_codeql_init(self):
        """测试 CodeQL Scanner 初始化"""
        scanner = CodeQLScanner(
            codeql_path="/usr/bin/codeql",
            timeout_seconds=60
        )
        assert scanner.codeql_path == "/usr/bin/codeql"
        assert scanner.timeout_seconds == 60
    
    @pytest.mark.asyncio
    async def test_codeql_scan_no_findings(self):
        """测试 CodeQL 扫描 - 无漏洞"""
        scanner = CodeQLScanner()
        
        # Mock subprocess
        with patch.object(
            scanner, "_create_database", return_value=True
        ), patch.object(
            scanner, "_run_queries", return_value=[]
        ):
            result = await scanner.scan("/path/to/repo", "python")
            
            assert result.success
            assert len(result.findings) == 0
            assert result.critical_count == 0
            assert result.high_count == 0
            assert not result.should_block
    
    @pytest.mark.asyncio
    async def test_codeql_scan_with_findings(self):
        """测试 CodeQL 扫描 - 发现漏洞"""
        scanner = CodeQLScanner()
        
        findings = [
            CodeQLFinding(
                rule_id="py/sql-injection",
                message="SQL Injection vulnerability",
                severity=ScanSeverity.CRITICAL,
                file_path="src/api/tasks.py",
                line_start=42,
                line_end=42,
                column_start=10,
                column_end=50,
                code_snippet='query = f"SELECT * FROM tasks WHERE id = {id}"',
                remediation="Use parameterized queries"
            ),
            CodeQLFinding(
                rule_id="py/unsafe-deserialization",
                message="Unsafe deserialization",
                severity=ScanSeverity.HIGH,
                file_path="src/utils/serializer.py",
                line_start=87,
                line_end=87,
                column_start=5,
                column_end=30,
                code_snippet="obj = pickle.loads(data)",
                remediation="Use json.loads instead of pickle"
            ),
        ]
        
        with patch.object(
            scanner, "_create_database", return_value=True
        ), patch.object(
            scanner, "_run_queries", return_value=findings
        ):
            result = await scanner.scan("/path/to/repo", "python")
            
            assert result.success
            assert len(result.findings) == 2
            assert result.critical_count == 1
            assert result.high_count == 1
            assert result.should_block  # CRITICAL >= 1
    
    def test_codeql_parse_results(self):
        """测试 CodeQL 结果解析"""
        scanner = CodeQLScanner()
        
        # 模拟 CodeQL JSON 输出
        data = {
            "results": [
                {
                    "ruleID": "py/sql-injection",
                    "level": "error",
                    "message": {"text": "SQL Injection"},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": "src/api.py"},
                            "region": {
                                "startLine": 42,
                                "endLine": 42,
                                "startColumn": 10,
                                "endColumn": 50,
                            }
                        }
                    }]
                }
            ]
        }
        
        findings = scanner._parse_results(data)
        
        assert len(findings) == 1
        assert findings[0].rule_id == "py/sql-injection"
        assert findings[0].severity == ScanSeverity.CRITICAL


class TestGitleaksScanner:
    """Gitleaks Scanner 单元测试"""
    
    def test_gitleaks_init(self):
        """测试 Gitleaks Scanner 初始化"""
        scanner = GitleaksScanner(
            gitleaks_path="/usr/bin/gitleaks",
            timeout_seconds=60
        )
        assert scanner.gitleaks_path == "/usr/bin/gitleaks"
        assert scanner.timeout_seconds == 60
    
    @pytest.mark.asyncio
    async def test_gitleaks_scan_no_secrets(self):
        """测试 Gitleaks 扫描 - 无密钥泄露"""
        scanner = GitleaksScanner()
        
        with patch.object(
            scanner, "_run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = Mock(returncode=0)
            
            result = await scanner.scan("/path/to/repo")
            
            assert result.success
            assert len(result.secrets) == 0
            assert not result.should_block
    
    @pytest.mark.asyncio
    async def test_gitleaks_scan_with_secrets(self):
        """测试 Gitleaks 扫描 - 检测到密钥"""
        scanner = GitleaksScanner()
        
        secrets = [
            GitleaksSecret(
                secret_type=SecretType.GITHUB_TOKEN,
                rule_id="GitHub Token",
                file_path=".env.example",
                commit_hash="abc123",
                line_number=3,
                secret_value_hash="ghp_***xxxxx",
                rule_description="GitHub Personal Access Token",
                remediation="Delete key and regenerate"
            ),
            GitleaksSecret(
                secret_type=SecretType.AWS_KEY,
                rule_id="AWS Access Key",
                file_path="config.py",
                commit_hash="def456",
                line_number=15,
                secret_value_hash="AKIA***xxxxx",
                rule_description="AWS Access Key ID",
                remediation="Rotate AWS credentials"
            ),
        ]
        
        # 直接 mock scan 方法返回包含 secrets 的结果
        result = GitleaksResult(
            success=True,
            scan_duration_ms=500,
            secrets=secrets,
            error_message=None
        )
        
        with patch.object(
            scanner, "scan", new_callable=AsyncMock, return_value=result
        ):
            actual_result = await scanner.scan("/path/to/repo")
            
            assert actual_result.success
            assert len(actual_result.secrets) == 2
            assert actual_result.should_block  # 任何 Secret 都拦截


class TestResultProcessor:
    """Result Processor 单元测试"""
    
    def test_processor_init(self):
        """测试 Result Processor 初始化"""
        processor = ScanResultProcessor()
        assert processor is not None
    
    def test_process_allow_decision(self):
        """测试处理结果 - ALLOW 决策"""
        processor = ScanResultProcessor()
        
        codeql_result = CodeQLResult(
            success=True,
            scan_duration_ms=1000,
            findings=[],
            critical_count=0,
            high_count=0,
            error_message=None
        )
        
        gitleaks_result = GitleaksResult(
            success=True,
            scan_duration_ms=500,
            secrets=[],
            error_message=None
        )
        
        summary = processor.process(codeql_result, gitleaks_result)
        
        assert summary.decision == ScanDecision.ALLOW
        assert summary.total_issues == 0
    
    def test_process_block_decision_critical(self):
        """测试处理结果 - BLOCK 决策 (CRITICAL 漏洞)"""
        processor = ScanResultProcessor()
        
        codeql_result = CodeQLResult(
            success=True,
            scan_duration_ms=1000,
            findings=[
                CodeQLFinding(
                    rule_id="py/sql-injection",
                    message="SQL Injection",
                    severity=ScanSeverity.CRITICAL,
                    file_path="src/api.py",
                    line_start=42,
                    line_end=42,
                    column_start=10,
                    column_end=50,
                    code_snippet="unsafe code",
                    remediation="fix it"
                )
            ],
            critical_count=1,
            high_count=0,
            error_message=None
        )
        
        gitleaks_result = GitleaksResult(
            success=True,
            scan_duration_ms=500,
            secrets=[],
            error_message=None
        )
        
        summary = processor.process(codeql_result, gitleaks_result)
        
        assert summary.decision == ScanDecision.BLOCK
        assert summary.codeql_critical == 1
    
    def test_process_block_decision_secret(self):
        """测试处理结果 - BLOCK 决策 (Secret 检测)"""
        processor = ScanResultProcessor()
        
        codeql_result = CodeQLResult(
            success=True,
            scan_duration_ms=1000,
            findings=[],
            critical_count=0,
            high_count=0,
            error_message=None
        )
        
        gitleaks_result = GitleaksResult(
            success=True,
            scan_duration_ms=500,
            secrets=[
                GitleaksSecret(
                    secret_type=SecretType.GITHUB_TOKEN,
                    rule_id="GitHub Token",
                    file_path=".env",
                    commit_hash="abc123",
                    line_number=1,
                    secret_value_hash="ghp_***",
                    rule_description="GitHub Token",
                    remediation="Delete"
                )
            ],
            error_message=None
        )
        
        summary = processor.process(codeql_result, gitleaks_result)
        
        assert summary.decision == ScanDecision.BLOCK
        assert summary.gitleaks_count == 1
    
    def test_pr_comment_generation_pass(self):
        """测试生成 PR Comment - 通过"""
        processor = ScanResultProcessor()
        
        summary = ScanResultSummary(
            decision=ScanDecision.ALLOW,
            codeql_critical=0,
            codeql_high=0,
            gitleaks_count=0,
            total_issues=0
        )
        
        comment = processor.generate_pr_comment(summary)
        
        assert "✅ Security Scan Passed" in comment
        assert "无漏洞" in comment
        assert "无密钥泄露" in comment
    
    def test_pr_comment_generation_fail(self):
        """测试生成 PR Comment - 失败"""
        processor = ScanResultProcessor()
        
        findings = [
            CodeQLFinding(
                rule_id="py/sql-injection",
                message="SQL Injection",
                severity=ScanSeverity.HIGH,
                file_path="src/api.py",
                line_start=42,
                line_end=42,
                column_start=10,
                column_end=50,
                code_snippet="unsafe",
                remediation="use parameterized query"
            )
        ]
        
        summary = ScanResultSummary(
            decision=ScanDecision.BLOCK,
            codeql_critical=0,
            codeql_high=1,
            gitleaks_count=0,
            total_issues=1,
            codeql_findings=findings
        )
        
        comment = processor.generate_pr_comment(summary)
        
        assert "❌ Security Scan Failed" in comment
        assert "无法合并" in comment
        assert "SQL Injection" in comment


class TestOrchestrator:
    """Orchestrator 单元测试"""
    
    @pytest.mark.asyncio
    async def test_orchestrator_scan_pr(self):
        """测试 Orchestrator 扫描 PR"""
        
        mock_codeql = Mock(spec=CodeQLScanner)
        mock_gitleaks = Mock(spec=GitleaksScanner)
        mock_processor = Mock(spec=ScanResultProcessor)
        
        codeql_result = CodeQLResult(
            success=True,
            scan_duration_ms=1000,
            findings=[],
            critical_count=0,
            high_count=0,
            error_message=None
        )
        
        gitleaks_result = GitleaksResult(
            success=True,
            scan_duration_ms=500,
            secrets=[],
            error_message=None
        )
        
        summary = ScanResultSummary(
            decision=ScanDecision.ALLOW,
            codeql_critical=0,
            codeql_high=0,
            gitleaks_count=0,
            total_issues=0
        )
        
        mock_codeql.scan = AsyncMock(return_value=codeql_result)
        mock_gitleaks.scan = AsyncMock(return_value=gitleaks_result)
        mock_processor.process = Mock(return_value=summary)
        
        orchestrator = ScanningOrchestrator(
            codeql_scanner=mock_codeql,
            gitleaks_scanner=mock_gitleaks,
            result_processor=mock_processor
        )
        
        result = await orchestrator.scan_pr(
            task_id="task-123",
            repo_path="/path/to/repo",
            pr_number=42
        )
        
        assert result.decision == ScanDecision.ALLOW
        assert result.total_issues == 0


class TestPolicyGateway:
    """Policy Gateway 单元测试"""
    
    def test_policy_gateway_approve(self):
        """测试策略网关 - 批准"""
        gateway = ScanPolicyGateway()
        
        summary = ScanResultSummary(
            decision=ScanDecision.ALLOW,
            codeql_critical=0,
            codeql_high=0,
            gitleaks_count=0,
            total_issues=0
        )
        
        decision = gateway.evaluate(summary)
        
        assert decision.decision == PolicyDecision.APPROVE
        assert "passed" in decision.reason.lower()
    
    def test_policy_gateway_reject(self):
        """测试策略网关 - 拒绝"""
        gateway = ScanPolicyGateway()
        
        summary = ScanResultSummary(
            decision=ScanDecision.BLOCK,
            codeql_critical=1,
            codeql_high=0,
            gitleaks_count=0,
            total_issues=1
        )
        
        decision = gateway.evaluate(summary)
        
        assert decision.decision == PolicyDecision.REJECT
        assert decision.force_override_possible


def test_github_check_status_conversion():
    """测试转换为 GitHub Check Run 状态"""
    from src.security.scanning.policy_integration import ScanPolicyDecision
    
    decision = ScanPolicyDecision(
        decision=PolicyDecision.APPROVE,
        reason="All checks passed",
        recommended_action="Can merge",
        should_comment_pr=True,
        force_override_possible=False
    )
    
    status = to_github_check_status(decision)
    
    assert status["status"] == "completed"
    assert status["conclusion"] == "success"
    assert "Security Scan" in status["title"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
