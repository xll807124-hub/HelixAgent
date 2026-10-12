"""
CodeQL Scanner - 静态应用安全测试 (SAST)

职责:
  1. 通过 CodeQL 进行代码分析
  2. 识别 OWASP Top 10 及常见漏洞
  3. 返回结构化的漏洞信息

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


class ScanSeverity(str, Enum):
    """漏洞严重程度"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOTE = "note"


@dataclass
class CodeQLFinding:
    """CodeQL 发现的单个漏洞"""
    rule_id: str                    # 规则 ID (e.g. "py/sql-injection")
    message: str                    # 漏洞描述
    severity: ScanSeverity          # 严重程度
    file_path: str                  # 文件路径 (相对于仓库根)
    line_start: int                 # 起始行号
    line_end: int | None         # 结束行号
    column_start: int               # 起始列号
    column_end: int | None       # 结束列号
    code_snippet: str               # 代码片段 (上下文)
    remediation: str                # 修复建议
    
    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class CodeQLResult:
    """CodeQL 扫描结果"""
    success: bool                   # 扫描是否成功
    scan_duration_ms: int           # 扫描耗时 (毫秒)
    findings: list[CodeQLFinding]   # 发现的漏洞列表
    critical_count: int             # CRITICAL 数量
    high_count: int                 # HIGH 数量
    error_message: str | None    # 错误信息
    
    @property
    def should_block(self) -> bool:
        """是否应该阻止 PR"""
        # 严格模式: CRITICAL >= 1 或 HIGH >= 3
        return self.critical_count >= 1 or self.high_count >= 3


class CodeQLScanner:
    """
    CodeQL 扫描器
    
    集成 GitHub 官方 CodeQL CLI 进行静态代码分析。
    
    前置条件:
      - CodeQL CLI 已安装 (`codeql --version`)
      - CodeQL 查询库已下载
      - 代码仓库有完整的 git 历史
    """
    
    def __init__(
        self,
        codeql_path: str = "codeql",
        database_dir: str | None = None,
        queries_dir: str | None = None,
        timeout_seconds: int = 120,
    ):
        """
        初始化 CodeQL 扫描器
        
        Args:
            codeql_path: CodeQL CLI 可执行文件路径
            database_dir: CodeQL 数据库存储目录 (默认系统临时目录)
            queries_dir: CodeQL 查询库目录
            timeout_seconds: 扫描超时时间
        """
        import tempfile
        
        self.codeql_path = codeql_path
        default_db_dir = str(Path(tempfile.gettempdir()) / "codeql-databases")
        self.database_dir = Path(database_dir or default_db_dir)
        self.queries_dir = Path(queries_dir or "/opt/codeql-queries")
        self.timeout_seconds = timeout_seconds
        self.database_dir.mkdir(parents=True, exist_ok=True)
    
    async def scan(
        self, repo_path: str | Path, language: str = "python"
    ) -> CodeQLResult:
        """
        扫描代码仓库
        
        Args:
            repo_path: 仓库本地路径
            language: 编程语言 (python, javascript, go, ...)
        
        Returns:
            CodeQLResult: 扫描结果
        
        异常处理:
            - CodeQL CLI 不存在 → 返回 error_message
            - 数据库创建失败 → 返回 error_message
            - 查询执行超时 → 返回 error_message
        """
        try:
            repo_path = Path(repo_path)
            db_path = self.database_dir / f"{repo_path.name}-{language}-db"
            
            logger.info(f"[CodeQL] 开始扫描: {repo_path} (Language: {language})")
            
            # 步骤 1: 创建数据库
            db_created = await self._create_database(
                repo_path, db_path, language
            )
            if not db_created:
                return CodeQLResult(
                    success=False,
                    scan_duration_ms=0,
                    findings=[],
                    critical_count=0,
                    high_count=0,
                    error_message="Failed to create CodeQL database"
                )
            
            # 步骤 2: 执行查询
            findings = await self._run_queries(db_path, language)
            
            # 步骤 3: 统计结果
            critical_count = sum(
                1 for f in findings if f.severity == ScanSeverity.CRITICAL
            )
            high_count = sum(
                1 for f in findings if f.severity == ScanSeverity.HIGH
            )
            
            logger.info(
                f"[CodeQL] 扫描完成: {len(findings)} 漏洞 "
                f"({critical_count} CRITICAL, {high_count} HIGH)"
            )
            
            return CodeQLResult(
                success=True,
                scan_duration_ms=0,  # TODO: 记录实际耗时
                findings=findings,
                critical_count=critical_count,
                high_count=high_count,
                error_message=None
            )
        
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
    
    async def _create_database(
        self,
        repo_path: Path,
        db_path: Path,
        language: str
    ) -> bool:
        """创建 CodeQL 数据库"""
        try:
            # 清理旧数据库
            if db_path.exists():
                import shutil
                shutil.rmtree(db_path)
            
            cmd = [
                self.codeql_path,
                "database", "create",
                str(db_path),
                f"--language={language}",
                f"--source-root={repo_path}",
                "--overwrite",
            ]
            
            result = await asyncio.wait_for(
                self._run_subprocess(cmd),
                timeout=self.timeout_seconds
            )
            
            return result.returncode == 0
        
        except TimeoutError:
            logger.error("[CodeQL] Database 创建超时")
            return False
        except Exception as e:
            logger.error(f"[CodeQL] Database 创建失败: {e}")
            return False
    
    async def _run_queries(
        self,
        db_path: Path,
        language: str
    ) -> list[CodeQLFinding]:
        """运行 CodeQL 查询"""
        findings = []
        try:
            # 查询库路径
            queries_path = self.queries_dir / f"{language}-queries"
            if not queries_path.exists():
                logger.warning(
                    f"[CodeQL] 查询库不存在: {queries_path}, "
                    f"将使用默认查询"
                )
                queries_path = self.queries_dir
            
            # 运行分析
            output_file = Path("/tmp/codeql-results.json")
            cmd = [
                self.codeql_path,
                "database", "analyze",
                str(db_path),
                "--format=json",
                f"--output={output_file}",
            ]
            
            if queries_path.exists():
                cmd.append(str(queries_path))
            
            result = await asyncio.wait_for(
                self._run_subprocess(cmd),
                timeout=self.timeout_seconds
            )
            
            # 解析结果
            if result.returncode == 0 and output_file.exists():
                with open(output_file) as f:
                    data = json.load(f)
                    findings = self._parse_results(data)
                
                # 清理
                output_file.unlink(missing_ok=True)
            
            return findings
        
        except TimeoutError:
            logger.error("[CodeQL] 查询执行超时")
            return []
        except Exception as e:
            logger.error(f"[CodeQL] 查询执行失败: {e}")
            return []
    
    def _parse_results(self, data: dict) -> list[CodeQLFinding]:
        """解析 CodeQL JSON 结果"""
        findings = []
        
        for result in data.get("results", []):
            rule_id = result.get("ruleID", "unknown")
            
            # 严重程度映射
            severity_map = {
                "error": ScanSeverity.CRITICAL,
                "warning": ScanSeverity.HIGH,
                "note": ScanSeverity.MEDIUM,
            }
            severity = severity_map.get(
                result.get("level", "note"),
                ScanSeverity.MEDIUM
            )
            
            # 提取位置信息
            locations = result.get("locations", [{}])
            location = locations[0] if locations else {}
            physical_loc = location.get("physicalLocation", {})
            region = physical_loc.get("region", {})
            
            file_path = physical_loc.get("artifactLocation", {}).get("uri", "unknown")
            line_start = region.get("startLine", 0)
            line_end = region.get("endLine")
            column_start = region.get("startColumn", 0)
            column_end = region.get("endColumn")
            
            # 提取消息和建议
            message = result.get("message", {}).get("text", "")
            remediation = ""  # TODO: 从 rules 中提取修复建议
            
            finding = CodeQLFinding(
                rule_id=rule_id,
                message=message,
                severity=severity,
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                column_start=column_start,
                column_end=column_end,
                code_snippet="",  # TODO: 从源代码提取
                remediation=remediation,
            )
            
            findings.append(finding)
        
        return findings
    
    @staticmethod
    async def _run_subprocess(cmd: list[str]) -> subprocess.CompletedProcess:
        """异步运行子进程"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True)
        )
