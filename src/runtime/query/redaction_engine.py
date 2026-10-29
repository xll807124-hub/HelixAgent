"""
脱敏引擎 - 敏感字段识别与脱敏

负责：
1. 敏感字段自动识别（密钥、Token、私钥等）
2. 根据访问级别返回不同脱敏版本
3. 脱敏规则版本管理
"""

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .access_control import AccessLevel as AccessLevel


class SensitivityLevel(str, Enum):
    """数据敏感级别（与 Event 的 data_classification 对应）"""

    L0 = "PUBLIC"  # 公开信息
    L1 = "INTERNAL"  # 项目内部信息
    L2 = "RESTRICTED"  # 凭据前缀、部分敏感数据
    L3 = "SECRET"  # 完整凭据、私钥
    L4 = "TOP_SECRET"  # 最高机密


@dataclass
class RedactionInfo:
    """脱敏信息 - 记录脱敏操作"""

    has_sensitive_data: bool
    """是否包含敏感数据"""

    data_classification: SensitivityLevel
    """数据敏感级别"""

    redacted_fields: list[str] = field(default_factory=list)
    """被脱敏的字段列表"""

    redaction_rules_version: str = "v1.0"
    """脱敏规则版本"""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "has_sensitive_data": self.has_sensitive_data,
            "data_classification": self.data_classification.value,
            "redacted_fields": self.redacted_fields,
            "redaction_rules_version": self.redaction_rules_version,
        }


class SensitivePatternMatcher:
    """敏感模式匹配器"""

    # 密钥和令牌的常见模式
    PATTERNS = {
        "api_key": re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE),
        "github_token": re.compile(r"ghp_[a-zA-Z0-9]{36}", re.IGNORECASE),
        "private_key": re.compile(r"-----BEGIN.*PRIVATE KEY-----", re.IGNORECASE),
        "aws_secret": re.compile(r"AKIA[0-9A-Z]{16}", re.IGNORECASE),
        "jwt_token": re.compile(
            r"eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*", re.IGNORECASE
        ),
        "password": re.compile(r"password\s*[:=]", re.IGNORECASE),
        "env_var_secret": re.compile(r"(SECRET|PASSWORD|TOKEN|KEY)\s*=", re.IGNORECASE),
    }

    @classmethod
    def detect_sensitive_patterns(cls, text: str) -> list[str]:
        """
        检测文本中的敏感模式

        Args:
            text: 要检查的文本

        Returns:
            匹配到的模式列表
        """
        if not isinstance(text, str):
            return []

        matched_patterns = []
        for pattern_name, pattern in cls.PATTERNS.items():
            if pattern.search(text):
                matched_patterns.append(pattern_name)

        return matched_patterns


class RedactionEngine:
    """脱敏引擎"""

    # 脱敏规则矩阵：[用户访问级别][数据敏感级别] -> 脱敏策略
    REDACTION_MATRIX = {
        AccessLevel.BASIC: {
            SensitivityLevel.L0: "FULL",  # 完整返回
            SensitivityLevel.L1: "SUMMARY",  # 返回摘要
            SensitivityLevel.L2: "DENY",  # 拒绝返回
            SensitivityLevel.L3: "DENY",  # 拒绝返回
            SensitivityLevel.L4: "DENY",  # 拒绝返回
        },
        AccessLevel.AUDIT: {
            SensitivityLevel.L0: "FULL",  # 完整返回
            SensitivityLevel.L1: "FULL",  # 完整返回
            SensitivityLevel.L2: "FULL",  # 完整返回
            SensitivityLevel.L3: "PARTIAL",  # 部分脱敏
            SensitivityLevel.L4: "DENY",  # 拒绝返回
        },
        AccessLevel.ADMIN: {
            SensitivityLevel.L0: "FULL",  # 完整返回
            SensitivityLevel.L1: "FULL",  # 完整返回
            SensitivityLevel.L2: "FULL",  # 完整返回
            SensitivityLevel.L3: "FULL",  # 完整返回
            SensitivityLevel.L4: "FULL",  # 完整返回
        },
    }

    def __init__(self, rules_version: str = "v1.0"):
        """
        初始化脱敏引擎

        Args:
            rules_version: 脱敏规则版本
        """
        self.rules_version = rules_version

    def get_redaction_policy(
        self,
        access_level: AccessLevel,
        data_classification: SensitivityLevel,
    ) -> str:
        """
        获取脱敏策略

        Args:
            access_level: 用户访问级别
            data_classification: 数据敏感级别

        Returns:
            脱敏策略 (FULL/SUMMARY/PARTIAL/DENY)
        """
        return self.REDACTION_MATRIX.get(access_level, {}).get(data_classification, "DENY")

    def redact_string(
        self,
        value: str,
        policy: str,
        data_classification: SensitivityLevel | None = None,
    ) -> str | None:
        """
        脱敏单个字符串值

        Args:
            value: 原始值
            policy: 脱敏策略 (FULL/SUMMARY/PARTIAL/DENY)
            data_classification: 数据敏感级别（用于 PARTIAL 脱敏）

        Returns:
            脱敏后的值，或 None 如果策略为 DENY
        """
        if not isinstance(value, str):
            return value

        if policy == "FULL":
            return value

        if policy == "DENY":
            return None

        if policy == "SUMMARY":
            # 返回摘要：前 50 字符 + 哈希
            preview = value[:50] if len(value) > 50 else value
            value_hash = hashlib.sha256(value.encode()).hexdigest()[:16]
            return f"{preview}...[HASH:{value_hash}]"

        if policy == "PARTIAL":
            # 部分脱敏：识别敏感模式后脱敏
            if len(value) > 100:
                # 长值：前缀 + 哈希
                value_hash = hashlib.sha256(value.encode()).hexdigest()[:16]
                return f"***[REDACTED:{value_hash}]***"
            else:
                # 短值：保留前缀（如 "sk-" 或 "ghp_"）
                patterns = SensitivePatternMatcher.detect_sensitive_patterns(value)
                if patterns:
                    # 找到敏感模式，保留前 5 字符 + 星号
                    if len(value) > 5:
                        return f"{value[:5]}***"
                    else:
                        return "***"
                else:
                    # 没有明显敏感模式，返回原值
                    return value

        # 未知策略，拒绝返回
        return None

    def redact_payload(
        self,
        payload: dict[str, Any],
        access_level: AccessLevel,
        data_classification: SensitivityLevel,
    ) -> tuple[dict[str, Any], RedactionInfo]:
        """
        脱敏事件载荷

        Args:
            payload: 原始载荷
            access_level: 用户访问级别
            data_classification: 数据敏感级别

        Returns:
            (脱敏后的载荷, 脱敏信息)
        """
        if not isinstance(payload, dict):
            return payload, RedactionInfo(
                has_sensitive_data=False,
                data_classification=data_classification,
                redaction_rules_version=self.rules_version,
            )

        policy = self.get_redaction_policy(access_level, data_classification)

        # 如果策略是 DENY，拒绝返回整个载荷
        if policy == "DENY":
            return {}, RedactionInfo(
                has_sensitive_data=True,
                data_classification=data_classification,
                redacted_fields=list(payload.keys()),
                redaction_rules_version=self.rules_version,
            )

        redacted_fields: list[str] = []
        has_sensitive = False

        def redact_value(value: Any, path: str, sensitive_name: bool = False) -> Any:
            nonlocal has_sensitive
            sensitive_content = isinstance(value, str) and bool(
                SensitivePatternMatcher.detect_sensitive_patterns(value)
            )
            if sensitive_name or sensitive_content:
                has_sensitive = True
                if policy != "FULL":
                    # 字段名已表明敏感时，不依赖字符串格式/长度，也不返回秘密前缀。
                    redacted_fields.append(path)
                    return "[REDACTED]"
            if isinstance(value, dict):
                return {
                    key: redact_value(
                        child,
                        f"{path}.{key}" if path else key,
                        self._is_sensitive_field_name(key),
                    )
                    for key, child in value.items()
                }
            if isinstance(value, list):
                return [
                    redact_value(child, f"{path}[{index}]") for index, child in enumerate(value)
                ]
            return value

        redacted_payload = redact_value(payload, "")

        return redacted_payload, RedactionInfo(
            has_sensitive_data=has_sensitive,
            data_classification=data_classification,
            redacted_fields=redacted_fields,
            redaction_rules_version=self.rules_version,
        )

    @staticmethod
    def _is_sensitive_field_name(field_name: str) -> bool:
        """
        检查字段名是否指示敏感内容

        Args:
            field_name: 字段名

        Returns:
            是否敏感
        """
        sensitive_keywords = {
            "secret",
            "password",
            "token",
            "key",
            "credential",
            "apikey",
            "api_key",
            "access_token",
            "refresh_token",
            "auth",
            "authorization",
            "private",
            "sensitive",
            "confidential",
            "encrypted",
            "cipher",
        }

        field_lower = field_name.lower()
        return any(keyword in field_lower for keyword in sensitive_keywords)
