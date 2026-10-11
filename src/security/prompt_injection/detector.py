"""
Prompt 注入检测引擎

对齐设计文档：REQ-SEC-006 Prompt 注入防护
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """检测风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class DetectionResult:
    """检测结果"""
    is_injection: bool                   # 是否检测到注入
    risk_level: RiskLevel                # 风险等级
    confidence: float                    # 置信度（0-1）
    detected_patterns: list[str]         # 检测到的模式
    evidence: list[str]                  # 证据
    recommendation: str                  # 建议


class PromptInjectionDetector:
    """
    Prompt 注入检测引擎
    
    职责：
    1. 识别已知的 Prompt 注入模式
    2. 分析输入的异常特征
    3. 评估风险等级
    4. 提供可操作的建议
    
    检测策略：
    - 模式匹配：已知攻击特征
    - 熵分析：异常字符分布
    - 语义分析：系统角色冲突
    - 统计异常：长度、字符分布
    """

    # 注入攻击模式库
    INJECTION_PATTERNS = {
        # 直接指令注入
        "ignore_previous": re.compile(
            r"ignore\s+(?:the\s+)?(?:previous|above|earlier|prior)", re.IGNORECASE
        ),
        "system_override": re.compile(
            r"system\s*(?:override|bypass|ignore|disable)", re.IGNORECASE
        ),
        "jailbreak": re.compile(
            r"jailbreak|break\s+out|escape\s+(?:the\s+)?(?:system|rules|constraints)",
            re.IGNORECASE,
        ),

        # 角色冲突
        "role_conflict": re.compile(
            r"you\s+are\s+(?:now|actually|really|actually)\s+a\s+(?:different|new|real|actual)",
            re.IGNORECASE,
        ),
        "role_switch": re.compile(
            r"(?:act|pretend|behave|roleplay)\s+as\s+(?:if\s+)?you\s+are",
            re.IGNORECASE,
        ),

        # 规则操纵
        "rule_override": re.compile(
            r"(?:your\s+)?rules?\s+(?:are\s+)?(?:overridden?|suspended|ignored|null)",
            re.IGNORECASE,
        ),
        "constraint_removal": re.compile(
            r"(?:ignore|remove|disable)\s+(?:your\s+)?(?:constraints?|restrictions?|limitations?)",
            re.IGNORECASE,
        ),

        # 代码执行
        "code_injection": re.compile(
            r"(?:execute|run|eval|exec)\s+(?:this\s+)?(?:python|javascript|code|command)",
            re.IGNORECASE,
        ),

        # 数据泄露
        "data_exfiltration": re.compile(
            r"(?:print|output|show|reveal|leak)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions|rules|memory)",
            re.IGNORECASE,
        ),

        # SQL 注入特征（在 prompt 中）
        "sql_injection": re.compile(
            r"(?:' (?:OR|AND)|--\s*;|/\*|\*/)", re.IGNORECASE
        ),
    }

    # 危险关键字
    DANGEROUS_KEYWORDS = {
        "ignore", "override", "bypass", "disable", "suspend",
        "cancel", "forget", "delete", "remove", "replace",
        "jailbreak", "escape", "breakout", "exploit", "hack",
        "execute", "eval", "exec", "system", "shell",
        "drop", "truncate", "update", "insert",
        "print", "output", "show", "leak", "reveal",
    }

    def __init__(self, threshold: float = 0.6):
        """
        初始化检测器
        
        Args:
            threshold: 检测阈值（0-1），置信度 > threshold 时报警
        """
        self.threshold = threshold
        self._detection_cache: dict[int, DetectionResult] = {}

    async def detect(self, text: str) -> DetectionResult:
        """
        检测 Prompt 注入风险
        
        Args:
            text: 输入文本
            
        Returns:
            DetectionResult: 检测结果
        """
        # 缓存检查
        text_hash = hash(text)
        if text_hash in self._detection_cache:
            return self._detection_cache[text_hash]

        detected_patterns: list[str] = []
        evidence: list[str] = []
        total_score = 0.0

        # 1. 模式匹配
        pattern_score = self._check_patterns(text, detected_patterns, evidence)
        total_score += pattern_score * 0.4  # 权重 40%

        # 2. 熵分析
        entropy_score = self._check_entropy(text, evidence)
        total_score += entropy_score * 0.2  # 权重 20%

        # 3. 语义分析
        semantic_score = self._check_semantic(text, evidence)
        total_score += semantic_score * 0.3  # 权重 30%

        # 4. 统计异常
        stats_score = self._check_statistics(text, evidence)
        total_score += stats_score * 0.1  # 权重 10%

        # 标准化置信度（0-1）
        confidence = min(total_score, 1.0)

        # 判断风险等级
        if confidence >= 0.9:
            risk_level = RiskLevel.CRITICAL
        elif confidence >= 0.7:
            risk_level = RiskLevel.HIGH
        elif confidence >= 0.5:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW

        is_injection = confidence > self.threshold

        result = DetectionResult(
            is_injection=is_injection,
            risk_level=risk_level,
            confidence=confidence,
            detected_patterns=detected_patterns,
            evidence=evidence,
            recommendation=self._get_recommendation(
                risk_level, detected_patterns
            ),
        )

        # 缓存结果
        self._detection_cache[text_hash] = result

        logger.info(
            f"Injection detection: risk={risk_level}, "
            f"confidence={confidence:.2f}, patterns={detected_patterns}"
        )

        return result

    def _check_patterns(
        self,
        text: str,
        detected_patterns: list[str],
        evidence: list[str],
    ) -> float:
        """检查已知注入模式"""
        score = 0.0

        for pattern_name, pattern_regex in self.INJECTION_PATTERNS.items():
            matches = pattern_regex.findall(text)
            if matches:
                detected_patterns.append(pattern_name)
                evidence.append(
                    f"Matched pattern '{pattern_name}': {matches[0]}"
                )
                score += 0.1  # 每个匹配加 0.1 分

        return min(score, 1.0)

    def _check_entropy(self, text: str, evidence: list[str]) -> float:
        """熵分析：检测异常低/高熵输入"""
        if len(text) < 10:
            return 0.0

        # 计算字符熵
        char_freq: dict[str, int] = {}
        for char in text.lower():
            char_freq[char] = char_freq.get(char, 0) + 1

        entropy = 0.0
        for freq in char_freq.values():
            p = freq / len(text)
            entropy -= p * (p and __import__("math").log2(p) or 0)

        # 正常英文熵约 4-5，异常低熵可能是重复注入模式
        if entropy < 2.0:
            evidence.append(f"Unusually low entropy: {entropy:.2f}")
            return 0.3
        elif entropy > 6.0:
            evidence.append(f"Unusually high entropy: {entropy:.2f}")
            return 0.2

        return 0.0

    def _check_semantic(self, text: str, evidence: list[str]) -> float:
        """语义分析：检测系统角色冲突"""
        score = 0.0

        # 检查是否尝试改变系统角色
        role_keywords = {
            "you are", "i am", "pretend", "act as", "assume", "imagine",
            "roleplay", "behave as", "think you are",
        }

        text_lower = text.lower()
        for keyword in role_keywords:
            if keyword in text_lower:
                evidence.append(f"Potential role-switch attempt: '{keyword}'")
                score += 0.2

        # 检查是否引用系统指令
        instruction_keywords = {
            "system prompt", "instructions", "rules", "guidelines",
            "constraints", "limitations", "don't", "must not",
        }

        for keyword in instruction_keywords:
            if keyword in text_lower:
                evidence.append(f"References system control: '{keyword}'")
                score += 0.15

        return min(score, 1.0)

    def _check_statistics(self, text: str, evidence: list[str]) -> float:
        """统计异常：检测异常长度、格式"""
        score = 0.0

        # 极端长度
        if len(text) > 10000:
            evidence.append(f"Unusually long input: {len(text)} chars")
            score += 0.2

        # 特殊字符比例
        special_chars = sum(1 for c in text if not c.isalnum() and c not in " \n\t")
        special_ratio = special_chars / len(text) if text else 0

        if special_ratio > 0.5:
            evidence.append(
                f"High special char ratio: {special_ratio:.1%}"
            )
            score += 0.3

        # 换行符过多（可能是格式注入）
        newline_count = text.count("\n")
        if newline_count > len(text) / 20:  # 每 20 字符超过 1 个换行
            evidence.append(f"Excessive newlines: {newline_count}")
            score += 0.2

        return min(score, 1.0)

    def _get_recommendation(
        self,
        risk_level: RiskLevel,
        detected_patterns: list[str],
    ) -> str:
        """生成建议"""
        if risk_level == RiskLevel.CRITICAL:
            return "BLOCK: Likely prompt injection detected. Reject input and log."
        elif risk_level == RiskLevel.HIGH:
            return (
                "CAUTION: Possible prompt injection. "
                "Review input before processing."
            )
        elif risk_level == RiskLevel.MEDIUM:
            return "WARN: Suspicious patterns detected. Monitor for issues."
        else:
            return "ALLOW: Input appears safe."
