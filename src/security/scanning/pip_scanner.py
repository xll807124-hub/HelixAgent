"""
Pip Scanner - Python 依赖漏洞扫描

职责:
  1. 检测 requirements.txt/setup.py/pyproject.toml
  2. 运行 pip-audit 获取漏洞信息
  3. 解析并返回结构化结果
  4. 支持快速/深度两种扫描模式

设计基线: REQ-SEC-003 (Policy Gateway), REQ-OBS-002 (Evidence Schema)
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path

from .npm_scanner import SCAResult, Vulnerability, VulnerabilitySeverity
from .process import run_scanner_process

logger = logging.getLogger(__name__)


class PipScanner:
    """
    pip-audit 扫描器
    
    使用 pip-audit 检测 Python 依赖中的已知漏洞。
    
    前置条件:
      - pip-audit 已安装 (`pip-audit --version`)
      - 仓库有 requirements.txt 或 pyproject.toml
    """
    
    def __init__(
        self,
        pip_audit_path: str = "pip-audit",
        timeout_seconds: int = 60,
    ):
        """
        初始化 Pip 扫描器
        
        Args:
            pip_audit_path: pip-audit 可执行文件路径
            timeout_seconds: 扫描超时时间
        """
        self.pip_audit_path = pip_audit_path
        self.timeout_seconds = timeout_seconds
    
    async def scan(
        self,
        repo_path: str | Path,
        deep_scan: bool = False
    ) -> SCAResult:
        """
        扫描 Python 依赖漏洞
        
        Args:
            repo_path: 仓库本地路径
            deep_scan: 是否深度扫描
        
        Returns:
            SCAResult: 扫描结果
        
        异常处理:
            - pip-audit 不存在 → 返回 error_message
            - requirements.txt 不存在 → 返回 error_message
            - 扫描超时 → 返回 error_message
        """
        try:
            repo_path = Path(repo_path)
            
            # 检查是否有 Python 依赖文件
            has_requirements = (repo_path / "requirements.txt").exists()
            has_pyproject = (repo_path / "pyproject.toml").exists()
            has_setup = (repo_path / "setup.py").exists()
            
            if not (has_requirements or has_pyproject or has_setup):
                logger.info(f"[Pip] 未找到 Python 依赖文件: {repo_path}")
                return SCAResult(
                    success=True,
                    scan_duration_ms=0,
                    vulnerabilities=[],
                    critical_count=0,
                    high_count=0,
                    medium_count=0,
                    low_count=0,
                    error_message=None
                )
            
            logger.info(f"[Pip] 开始扫描: {repo_path}")
            
            # 运行 pip-audit
            vulnerabilities = await self._run_pip_audit(repo_path)
            
            # 统计漏洞
            critical_count = sum(
                1 for v in vulnerabilities
                if v.severity == VulnerabilitySeverity.CRITICAL
            )
            high_count = sum(
                1 for v in vulnerabilities
                if v.severity == VulnerabilitySeverity.HIGH
            )
            medium_count = sum(
                1 for v in vulnerabilities
                if v.severity == VulnerabilitySeverity.MEDIUM
            )
            low_count = sum(
                1 for v in vulnerabilities
                if v.severity == VulnerabilitySeverity.LOW
            )
            
            logger.info(
                f"[Pip] 扫描完成: {len(vulnerabilities)} 个漏洞 "
                f"({critical_count} CRITICAL, {high_count} HIGH)"
            )
            
            return SCAResult(
                success=True,
                scan_duration_ms=0,
                vulnerabilities=vulnerabilities,
                critical_count=critical_count,
                high_count=high_count,
                medium_count=medium_count,
                low_count=low_count,
                error_message=None
            )
        
        except Exception as e:
            logger.error(f"[Pip] 扫描异常: {e}")
            return SCAResult(
                success=False,
                scan_duration_ms=0,
                vulnerabilities=[],
                critical_count=0,
                high_count=0,
                medium_count=0,
                low_count=0,
                error_message=str(e)
            )
    
    async def _run_pip_audit(self, repo_path: Path) -> list[Vulnerability]:
        """运行 pip-audit 命令"""
        try:
            cmd = [
                self.pip_audit_path,
                "--format", "json",
                "--desc"  # 包含漏洞描述
            ]
            requirements = repo_path / "requirements.txt"
            if requirements.exists():
                cmd.extend(["-r", str(requirements.resolve())])
            elif (repo_path / "pyproject.toml").exists():
                cmd.append(str(repo_path.resolve()))
            else:
                raise ValueError("A requirements.txt or pyproject.toml audit target is required")
            
            result = await asyncio.wait_for(
                self._run_subprocess(cmd, cwd=str(repo_path)),
                timeout=self.timeout_seconds
            )
            
            # pip-audit 返回 JSON
            if result.returncode not in (0, 1) or not result.stdout.strip():
                raise RuntimeError(f"pip-audit failed (exit {result.returncode})")
            data = json.loads(result.stdout)
            findings = self._parse_pip_audit_output(data)
            if result.returncode == 1 and not findings:
                raise ValueError("pip-audit failed without usable findings")
            return findings
        
        except TimeoutError:
            logger.error("[Pip] 扫描超时")
            raise RuntimeError("pip-audit timed out") from None
        except json.JSONDecodeError:
            logger.error("[Pip] JSON 解析失败")
            raise ValueError("Invalid pip-audit JSON") from None
        except Exception as e:
            logger.error(f"[Pip] 审计执行失败: {e}")
            raise
    
    def _parse_pip_audit_output(self, data: dict | list) -> list[Vulnerability]:
        """解析 pip-audit JSON 输出"""
        vulnerabilities = []
        
        # pip-audit JSON 格式 (v2.x+)
        # {
        #   "vulnerabilities": [
        #     {
        #       "name": "package-name",
        #       "version": "1.0.0",
        #       "vulnerability_id": "CVE-2023-1234",
        #       "advisory": "...",
        #       "fixed_in": ["1.0.1"],
        #       "found_date": "...",
        #       "sources": [...]
        #     }
        #   ]
        # }
        
        # pip-audit 2.x JSON: dependencies[].vulns[]. Keep the earlier flattened
        # report shape readable for stored reports, but reject unknown schemas.
        if isinstance(data, dict) and isinstance(data.get("dependencies"), list):
            dependencies = data["dependencies"]
        elif isinstance(data, list) and all("vulns" in item for item in data):
            dependencies = data
        elif isinstance(data, dict) and isinstance(data.get("vulnerabilities"), list):
            dependencies = None
        else:
            raise ValueError("Invalid pip-audit report")

        if dependencies is not None:
            vulns = []
            for dependency in dependencies:
                if dependency.get("skip_reason") or not isinstance(dependency.get("vulns"), list):
                    raise ValueError("pip-audit did not audit every dependency")
                for vuln in dependency["vulns"]:
                    vulns.append({
                        "name": dependency["name"], "version": dependency["version"],
                        "vulnerability_id": vuln["id"],
                        "advisory": vuln.get("description", "Unknown vulnerability"),
                        "fixed_in": vuln.get("fix_versions", []),
                    })
        else:
            assert isinstance(data, dict)
            vulns = data["vulnerabilities"]
        
        for vuln in vulns:
            # 推断严重程度 (pip-audit 不总是提供 severity)
            advisory = vuln.get("advisory", "").lower()
            severity = self._infer_severity(advisory)
            
            vulnerability = Vulnerability(
                id=vuln.get("vulnerability_id", "unknown"),
                package=vuln.get("name", "unknown"),
                current_version=vuln.get("version", "unknown"),
                vulnerable_range="unknown",  # pip-audit 不提供范围
                fix_version=", ".join(vuln.get("fixed_in", ["unknown"])),
                severity=severity,
                description=vuln.get("advisory", "Unknown vulnerability"),
                references=vuln.get("sources", []),
                affected_file="requirements.txt"
            )
            
            vulnerabilities.append(vulnerability)
        
        return vulnerabilities
    
    @staticmethod
    def _infer_severity(advisory: str) -> VulnerabilitySeverity:
        """从文本推断严重程度"""
        advisory_lower = advisory.lower()
        
        if any(word in advisory_lower for word in ["critical", "remote code", "execution"]):
            return VulnerabilitySeverity.CRITICAL
        elif any(word in advisory_lower for word in ["high", "dos", "denial"]):
            return VulnerabilitySeverity.HIGH
        elif any(word in advisory_lower for word in ["medium", "bypass", "leak"]):
            return VulnerabilitySeverity.MEDIUM
        else:
            return VulnerabilitySeverity.LOW
    
    @staticmethod
    async def _run_subprocess(
        cmd: list[str],
        cwd: str | None = None
    ) -> subprocess.CompletedProcess:
        """异步运行子进程"""
        return await run_scanner_process(cmd, cwd=cwd)
