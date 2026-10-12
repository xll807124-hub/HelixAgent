"""
Gitleaks Scanner - 密钥和敏感数据检测

职责:
  1. 扫描 Git 提交历史中的密钥泄露
  2. 检测 API Key, Token, 密码等敏感信息
  3. 返回结构化的检测结果

设计基线: REQ-SEC-003 (Policy Gateway), REQ-OBS-002 (Evidence Schema)
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SecretType(str, Enum):
    """密钥类型"""
    API_KEY = "api_key"
    AWS_KEY = "aws_key"
    GITHUB_TOKEN = "github_token"
    PRIVATE_KEY = "private_key"
    DATABASE_PASSWORD = "database_password"
    JWT_TOKEN = "jwt_token"
    GENERIC_SECRET = "generic_secret"


@dataclass
class GitleaksSecret:
    """Gitleaks 检测到的密钥"""
    secret_type: SecretType          # 密钥类型
    rule_id: str                     # 规则 ID
    file_path: str                   # 文件路径
    commit_hash: str                 # 提交哈希
    line_number: int                 # 行号
    secret_value_hash: str           # 密钥值哈希 (安全脱敏)
    rule_description: str            # 规则描述
    remediation: str                 # 修复建议 (删除密钥,重写历史)
    
    def to_dict(self):
        return asdict(self)


@dataclass
class GitleaksResult:
    """Gitleaks 扫描结果"""
    success: bool                   # 扫描是否成功
    scan_duration_ms: int           # 扫描耗时 (毫秒)
    secrets: list[GitleaksSecret]   # 检测到的密钥列表
    error_message: Optional[str]    # 错误信息
    
    @property
    def should_block(self) -> bool:
        """是否应该阻止 PR"""
        # 严格模式: 任何 Secret 检测都阻止
        return len(self.secrets) > 0


class GitleaksScanner:
    """
    Gitleaks 扫描器
    
    集成 gitleaks 工具检测代码中的密钥泄露。
    
    前置条件:
      - gitleaks 已安装 (`gitleaks version`)
      - git 仓库初始化
    
    检测范围:
      - API Key (GitHub, AWS, Google 等)
      - 私钥 (RSA, ECDSA 等)
      - 数据库连接字符串
      - JWT Token
      - OAuth Token
    """
    
    def __init__(
        self,
        gitleaks_path: str = "gitleaks",
        timeout_seconds: int = 60,
    ):
        """
        初始化 Gitleaks 扫描器
        
        Args:
            gitleaks_path: gitleaks 可执行文件路径
            timeout_seconds: 扫描超时时间
        """
        self.gitleaks_path = gitleaks_path
        self.timeout_seconds = timeout_seconds
    
    async def scan(
        self,
        repo_path: str,
        scan_all_history: bool = False
    ) -> GitleaksResult:
        """
        扫描仓库中的密钥泄露
        
        Args:
            repo_path: 仓库本地路径
            scan_all_history: 是否扫描全部历史提交
                              False: 仅扫描当前 HEAD (快速)
                              True: 扫描全部历史 (深度,用于晚间任务)
        
        Returns:
            GitleaksResult: 扫描结果
        
        异常处理:
            - gitleaks 不存在 → 返回 error_message
            - 仓库不是 git 目录 → 返回 error_message
            - 扫描超时 → 返回 error_message
        """
        try:
            repo_path = Path(repo_path)
            logger.info(
                f"[Gitleaks] 开始扫描: {repo_path} "
                f"(全部历史: {scan_all_history})"
            )
            
            # 构建命令
            cmd = [self.gitleaks_path, "detect"]
            cmd.extend([f"--source={repo_path}"])
            cmd.append(f"--verbose")
            cmd.append(f"--report-path=/tmp/gitleaks-report.json")
            
            if scan_all_history:
                cmd.append("--no-git")  # 扫描整个目录
            
            # 执行扫描
            result = await asyncio.wait_for(
                self._run_subprocess(cmd),
                timeout=self.timeout_seconds
            )
            
            # 解析结果
            secrets = []
            report_file = Path("/tmp/gitleaks-report.json")
            if report_file.exists():
                with open(report_file) as f:
                    data = json.load(f)
                    secrets = self._parse_results(data)
                report_file.unlink(missing_ok=True)
            
            logger.info(
                f"[Gitleaks] 扫描完成: {len(secrets)} 个密钥检测"
            )
            
            return GitleaksResult(
                success=True,
                scan_duration_ms=0,  # TODO: 记录实际耗时
                secrets=secrets,
                error_message=None
            )
        
        except asyncio.TimeoutError:
            logger.error("[Gitleaks] 扫描超时")
            return GitleaksResult(
                success=False,
                scan_duration_ms=0,
                secrets=[],
                error_message="Gitleaks scan timeout"
            )
        except Exception as e:
            logger.error(f"[Gitleaks] 扫描异常: {e}")
            return GitleaksResult(
                success=False,
                scan_duration_ms=0,
                secrets=[],
                error_message=str(e)
            )
    
    def _parse_results(self, data: dict | list) -> list[GitleaksSecret]:
        """解析 Gitleaks JSON 结果"""
        secrets = []
        
        # gitleaks 可能返回对象或数组
        results = data if isinstance(data, list) else data.get("Secrets", [])
        
        for item in results:
            # 推断密钥类型
            rule_id = item.get("RuleID", "generic")
            secret_type = self._infer_secret_type(rule_id, item)
            
            secret = GitleaksSecret(
                secret_type=secret_type,
                rule_id=rule_id,
                file_path=item.get("File", "unknown"),
                commit_hash=item.get("Commit", "unknown"),
                line_number=item.get("Line", 0),
                secret_value_hash=self._hash_secret(item.get("Secret", "")),
                rule_description=item.get("Rule", ""),
                remediation=(
                    "1. 立即删除密钥内容\n"
                    "2. 如果密钥已泄露,请在 secrets 管理系统中轮换\n"
                    "3. 使用 git filter-branch 重写历史"
                ),
            )
            
            secrets.append(secret)
        
        return secrets
    
    @staticmethod
    def _infer_secret_type(rule_id: str, item: dict) -> SecretType:
        """从规则 ID 推断密钥类型"""
        rule_id_lower = rule_id.lower()
        
        if "aws" in rule_id_lower:
            return SecretType.AWS_KEY
        elif "github" in rule_id_lower or "github" in item.get("Rule", "").lower():
            return SecretType.GITHUB_TOKEN
        elif "private" in rule_id_lower or "key" in rule_id_lower:
            return SecretType.PRIVATE_KEY
        elif "password" in rule_id_lower or "passwd" in rule_id_lower:
            return SecretType.DATABASE_PASSWORD
        elif "jwt" in rule_id_lower or "bearer" in rule_id_lower.lower():
            return SecretType.JWT_TOKEN
        elif "api" in rule_id_lower:
            return SecretType.API_KEY
        else:
            return SecretType.GENERIC_SECRET
    
    @staticmethod
    def _hash_secret(secret: str) -> str:
        """对密钥值进行哈希处理 (安全脱敏)"""
        import hashlib
        if not secret:
            return "unknown"
        # 仅保留前 4 个字符和后 4 个字符,中间用 *** 替代
        if len(secret) <= 8:
            return "***"
        return f"{secret[:4]}***{secret[-4:]}"
    
    @staticmethod
    async def _run_subprocess(cmd: list[str]) -> subprocess.CompletedProcess:
        """异步运行子进程"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True)
        )
