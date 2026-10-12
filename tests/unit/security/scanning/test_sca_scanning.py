"""
Unit tests for SCA (Software Composition Analysis) Scanning

测试覆盖:
  - NPM Scanner
  - Pip Scanner
  - SCA Orchestrator
  - SCA Result Processor
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.security.scanning.npm_scanner import (
    NPMScanner,
    SCAResult,
    Vulnerability,
    VulnerabilitySeverity,
)
from src.security.scanning.pip_scanner import PipScanner
from src.security.scanning.sca_orchestrator import SCADecision, SCAOrchestrator, SCAResultSummary
from src.security.scanning.sca_result_processor import SCAResultProcessor


class TestNPMScanner:
    """NPM Scanner 单元测试"""
    
    def test_npm_scanner_init(self):
        """测试 NPM Scanner 初始化"""
        scanner = NPMScanner(npm_path="/usr/bin/npm", timeout_seconds=60)
        assert scanner.npm_path == "/usr/bin/npm"
        assert scanner.timeout_seconds == 60
    
    @pytest.mark.asyncio
    async def test_npm_scan_no_package_json(self):
        """测试 NPM 扫描 - 无 package.json"""
        scanner = NPMScanner()
        
        result = await scanner.scan("/nonexistent/path")
        
        assert result.success
        assert len(result.vulnerabilities) == 0
        assert not result.should_block
    
    @pytest.mark.asyncio
    async def test_npm_scan_with_vulnerabilities(self):
        """测试 NPM 扫描 - 发现漏洞"""
        scanner = NPMScanner()
        
        vulnerabilities = [
            Vulnerability(
                id="CVE-2023-1234",
                package="lodash",
                current_version="4.17.20",
                vulnerable_range="<4.17.21",
                fix_version="4.17.21+",
                severity=VulnerabilitySeverity.CRITICAL,
                description="Prototype Pollution",
                references=["https://github.com/lodash/lodash/issues/4874"],
                affected_file="package.json"
            )
        ]
        
        # Mock both the package.json check and the scan
        with patch("pathlib.Path.exists", return_value=True), \
             patch.object(
            scanner, "_run_npm_audit", new_callable=AsyncMock, return_value=vulnerabilities
        ):
            result = await scanner.scan("/path/to/repo")
            
            assert result.success
            assert len(result.vulnerabilities) == 1
            assert result.critical_count == 1
            assert result.should_block
    
    def test_npm_parse_audit_output(self):
        """测试 npm audit 输出解析"""
        scanner = NPMScanner()
        
        data = {
            "vulnerabilities": {
                "lodash": {
                    "nodes": ["4.17.20"],
                    "severity": "high",
                    "via": [
                        {
                            "title": "Prototype Pollution",
                            "url": "https://github.com/lodash/lodash",
                            "cves": ["CVE-2023-1234"],
                            "fixed": "4.17.21"
                        }
                    ]
                }
            }
        }
        
        vulnerabilities = scanner._parse_npm_audit_output(data)
        
        assert len(vulnerabilities) == 1
        assert vulnerabilities[0].package == "lodash"
        assert vulnerabilities[0].severity == VulnerabilitySeverity.HIGH


class TestPipScanner:
    """Pip Scanner 单元测试"""
    
    def test_pip_scanner_init(self):
        """测试 Pip Scanner 初始化"""
        scanner = PipScanner(pip_audit_path="/usr/bin/pip-audit", timeout_seconds=60)
        assert scanner.pip_audit_path == "/usr/bin/pip-audit"
        assert scanner.timeout_seconds == 60
    
    @pytest.mark.asyncio
    async def test_pip_scan_no_requirements(self):
        """测试 Pip 扫描 - 无 requirements.txt"""
        scanner = PipScanner()
        
        result = await scanner.scan("/nonexistent/path")
        
        assert result.success
        assert len(result.vulnerabilities) == 0
        assert not result.should_block
    
    @pytest.mark.asyncio
    async def test_pip_scan_with_vulnerabilities(self):
        """测试 Pip 扫描 - 发现漏洞"""
        scanner = PipScanner()
        
        vulnerabilities = [
            Vulnerability(
                id="CVE-2023-5678",
                package="requests",
                current_version="2.28.0",
                vulnerable_range="<2.28.1",
                fix_version="2.28.1+",
                severity=VulnerabilitySeverity.HIGH,
                description="DoS via excessive redirects",
                references=["https://nvd.nist.gov/vuln/detail/CVE-2023-5678"],
                affected_file="requirements.txt"
            )
        ]
        
        # Mock the dependency file check
        with patch("pathlib.Path.exists", return_value=True), \
             patch.object(
            scanner, "_run_pip_audit", new_callable=AsyncMock, return_value=vulnerabilities
        ):
            result = await scanner.scan("/path/to/repo")
            
            assert result.success
            assert len(result.vulnerabilities) == 1
            assert result.high_count == 1
            assert result.should_block
    
    def test_pip_infer_severity(self):
        """测试 pip-audit 严重程度推断"""
        scanner = PipScanner()
        
        assert scanner._infer_severity("Remote Code Execution") == VulnerabilitySeverity.CRITICAL
        assert scanner._infer_severity("DoS vulnerability") == VulnerabilitySeverity.HIGH
        assert scanner._infer_severity("Information leak") == VulnerabilitySeverity.MEDIUM
        assert scanner._infer_severity("Minor issue") == VulnerabilitySeverity.LOW


class TestSCAOrchestrator:
    """SCA Orchestrator 单元测试"""
    
    @pytest.mark.asyncio
    async def test_orchestrator_scan_pr_allow(self):
        """测试 Orchestrator 扫描 PR - 允许通过"""
        
        npm_result = SCAResult(
            success=True,
            scan_duration_ms=500,
            vulnerabilities=[],
            critical_count=0,
            high_count=0,
            medium_count=0,
            low_count=0,
            error_message=None
        )
        
        pip_result = SCAResult(
            success=True,
            scan_duration_ms=400,
            vulnerabilities=[],
            critical_count=0,
            high_count=0,
            medium_count=0,
            low_count=0,
            error_message=None
        )
        
        mock_npm = Mock(spec=NPMScanner)
        mock_pip = Mock(spec=PipScanner)
        
        mock_npm.scan = AsyncMock(return_value=npm_result)
        mock_pip.scan = AsyncMock(return_value=pip_result)
        
        orchestrator = SCAOrchestrator(
            npm_scanner=mock_npm,
            pip_scanner=mock_pip
        )
        
        result = await orchestrator.scan_pr(
            task_id="task-123",
            repo_path="/path/to/repo",
            pr_number=42
        )
        
        assert result.decision == SCADecision.ALLOW
        assert result.total_vulnerabilities == 0
    
    @pytest.mark.asyncio
    async def test_orchestrator_scan_pr_block(self):
        """测试 Orchestrator 扫描 PR - 阻止"""
        
        vuln = Vulnerability(
            id="CVE-2023-1234",
            package="lodash",
            current_version="4.17.20",
            vulnerable_range="<4.17.21",
            fix_version="4.17.21+",
            severity=VulnerabilitySeverity.CRITICAL,
            description="Prototype Pollution",
            references=["https://..."],
            affected_file="package.json"
        )
        
        npm_result = SCAResult(
            success=True,
            scan_duration_ms=500,
            vulnerabilities=[vuln],
            critical_count=1,
            high_count=0,
            medium_count=0,
            low_count=0,
            error_message=None
        )
        
        pip_result = SCAResult(
            success=True,
            scan_duration_ms=400,
            vulnerabilities=[],
            critical_count=0,
            high_count=0,
            medium_count=0,
            low_count=0,
            error_message=None
        )
        
        mock_npm = Mock(spec=NPMScanner)
        mock_pip = Mock(spec=PipScanner)
        
        mock_npm.scan = AsyncMock(return_value=npm_result)
        mock_pip.scan = AsyncMock(return_value=pip_result)
        
        orchestrator = SCAOrchestrator(
            npm_scanner=mock_npm,
            pip_scanner=mock_pip
        )
        
        result = await orchestrator.scan_pr(
            task_id="task-123",
            repo_path="/path/to/repo",
            pr_number=42
        )
        
        assert result.decision == SCADecision.BLOCK
        assert result.total_vulnerabilities == 1
        assert result.critical_count == 1


class TestSCAResultProcessor:
    """SCA Result Processor 单元测试"""
    
    def test_pr_comment_generation_allow(self):
        """测试生成 PR Comment - 允许"""
        processor = SCAResultProcessor()
        
        summary = SCAResultSummary(
            decision=SCADecision.ALLOW,
            npm_vulnerabilities=0,
            pip_vulnerabilities=0,
            total_vulnerabilities=0,
            critical_count=0,
            high_count=0
        )
        
        comment = processor.generate_pr_comment(summary)
        
        assert "✅ Dependency Scan Passed" in comment
        assert "无漏洞" in comment
    
    def test_pr_comment_generation_block(self):
        """测试生成 PR Comment - 阻止"""
        processor = SCAResultProcessor()
        
        vuln = Vulnerability(
            id="CVE-2023-1234",
            package="lodash",
            current_version="4.17.20",
            vulnerable_range="<4.17.21",
            fix_version="4.17.21+",
            severity=VulnerabilitySeverity.CRITICAL,
            description="Prototype Pollution",
            references=["https://..."],
            affected_file="package.json"
        )
        
        summary = SCAResultSummary(
            decision=SCADecision.BLOCK,
            npm_vulnerabilities=1,
            pip_vulnerabilities=0,
            total_vulnerabilities=1,
            critical_count=1,
            high_count=0,
            npm_findings=[vuln]
        )
        
        comment = processor.generate_pr_comment(summary)
        
        assert "❌ Dependency Scan Failed" in comment
        assert "无法合并" in comment
        assert "lodash" in comment


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
