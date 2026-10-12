"""
NPM Scanner - JavaScript 依赖漏洞扫描

职责:
  1. 检测 package.json/package-lock.json
  2. 运行 npm audit 获取漏洞信息
  3. 解析并返回结构化结果
  4. 支持快速/深度两种扫描模式

设计基线: REQ-SEC-003 (Policy Gateway), REQ-OBS-002 (Evidence Schema)
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class VulnerabilitySeverity(str, Enum):
    """漏洞严重程度"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Vulnerability:
    """单个漏洞信息"""
    id: str                      # CVE-XXXX-XXXXX
    package: str                 # lodash, express
    current_version: str         # 4.17.20
    vulnerable_range: str        # <4.17.21
    fix_version: str             # 4.17.21+
    severity: VulnerabilitySeverity
    description: str             # 漏洞描述
    references: list[str]        # CVE URL 等
    affected_file: str           # package.json, package-lock.json
    
    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class SCAResult:
    """SCA 扫描结果"""
    success: bool                       # 扫描是否成功
    scan_duration_ms: int               # 扫描耗时
    vulnerabilities: list[Vulnerability]  # 漏洞列表
    critical_count: int                 # CRITICAL 数量
    high_count: int                     # HIGH 数量
    medium_count: int                   # MEDIUM 数量
    low_count: int                      # LOW 数量
    error_message: str | None        # 错误信息
    
    @property
    def should_block(self) -> bool:
        """是否应该阻止 PR (任何漏洞都拦截)"""
        return len(self.vulnerabilities) > 0
    
    @property
    def total_vulnerabilities(self) -> int:
        """总漏洞数"""
        return self.critical_count + self.high_count + self.medium_count + self.low_count


class NPMScanner:
    """
    npm 依赖扫描器
    
    使用 npm audit 检测 JavaScript 依赖中的已知漏洞。
    
    前置条件:
      - npm CLI 已安装 (`npm --version`)
      - 仓库有 package.json 和 package-lock.json
    """
    
    def __init__(
        self,
        npm_path: str = "npm",
        timeout_seconds: int = 60,
    ):
        """
        初始化 NPM 扫描器
        
        Args:
            npm_path: npm 可执行文件路径
            timeout_seconds: 扫描超时时间
        """
        self.npm_path = npm_path
        self.timeout_seconds = timeout_seconds
    
    async def scan(
        self,
        repo_path: str | Path,
        deep_scan: bool = False
    ) -> SCAResult:
        """
        扫描 npm 依赖漏洞
        
        Args:
            repo_path: 仓库本地路径
            deep_scan: 是否深度扫描 (影响扫描详细程度)
        
        Returns:
            SCAResult: 扫描结果
        
        异常处理:
            - npm 不存在 → 返回 error_message
            - package.json 不存在 → 返回 error_message
            - 扫描超时 → 返回 error_message
        """
        try:
            repo_path = Path(repo_path)
            
            # 检查 package.json 是否存在
            package_json = repo_path / "package.json"
            if not package_json.exists():
                logger.info(f"[NPM] 未找到 package.json: {repo_path}")
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
            
            logger.info(f"[NPM] 开始扫描: {repo_path}")
            
            # 运行 npm audit
            vulnerabilities = await self._run_npm_audit(repo_path)
            
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
                f"[NPM] 扫描完成: {len(vulnerabilities)} 个漏洞 "
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
            logger.error(f"[NPM] 扫描异常: {e}")
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
    
    async def _run_npm_audit(self, repo_path: Path) -> list[Vulnerability]:
        """运行 npm audit 命令"""
        try:
            cmd = [self.npm_path, "audit", "--json"]
            
            result = await asyncio.wait_for(
                self._run_subprocess(cmd, cwd=str(repo_path)),
                timeout=self.timeout_seconds
            )
            
            # npm audit 总是返回 JSON (即使出错)
            if result.stdout:
                data = json.loads(result.stdout)
                return self._parse_npm_audit_output(data)
            
            return []
        
        except TimeoutError:
            logger.error("[NPM] 扫描超时")
            return []
        except json.JSONDecodeError:
            logger.error("[NPM] JSON 解析失败")
            return []
        except Exception as e:
            logger.error(f"[NPM] 审计执行失败: {e}")
            return []
    
    def _parse_npm_audit_output(self, data: dict) -> list[Vulnerability]:
        """解析 npm audit JSON 输出"""
        vulnerabilities = []
        
        # npm audit JSON 格式
        # {
        #   "vulnerabilities": {
        #     "package-name": {
        #       "nodes": [version],
        #       "name": "package-name",
        #       "severity": "high",
        #       "via": [
        #         {
        #           "type": "advisories",
        #           "source": 1234567,
        #           "title": "...",
        #           "url": "https://...",
        #           "cves": ["CVE-2023-1234"]
        #         }
        #       ],
        #       ...
        #     }
        #   }
        # }
        
        vulns_by_package = data.get("vulnerabilities", {})
        
        for package_name, package_info in vulns_by_package.items():
            via = package_info.get("via", [])
            
            for advisory in via:
                if isinstance(advisory, dict):
                    cves = advisory.get("cves", [])
                    cve_id = cves[0] if cves else f"npm-{package_name}"
                else:
                    cve_id = f"npm-{package_name}"
                    advisory = {}
                
                severity_str = package_info.get("severity", "low").lower()
                severity = VulnerabilitySeverity[severity_str.upper()]
                
                vulnerability = Vulnerability(
                    id=cve_id,
                    package=package_name,
                    current_version=", ".join(package_info.get("nodes", ["unknown"])),
                    vulnerable_range=package_info.get("range", "unknown"),
                    fix_version=advisory.get("fixed", "check advisories"),
                    severity=severity,
                    description=advisory.get("title", "Unknown vulnerability"),
                    references=[advisory.get("url", "")] if advisory.get("url") else [],
                    affected_file="package.json"
                )
                
                vulnerabilities.append(vulnerability)
        
        return vulnerabilities
    
    @staticmethod
    async def _run_subprocess(
        cmd: list[str],
        cwd: str | None = None
    ) -> subprocess.CompletedProcess:
        """异步运行子进程"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd
            )
        )
