"""
Prompt 注入检测引擎 - Task 2.3 Day 1 核心实现

对齐设计文档：REQ-SEC-006 Prompt 注入防护

双层防护架构：
1. 第1层：快速拒绝（关键词+隐藏字符，< 5ms）同步
2. 第2层：启发式分析（语法+语义，20-50ms）可异步
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """检测风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SourceType(str, Enum):
    """内容来源类型"""
    USER_INPUT = "user_input"        # Issue/PR/Comment
    REPO_FILE = "repo_file"          # 仓库文件
    REPO_CONFIG = "repo_config"      # 配置文件（Cursor rules等）
    RETRIEVAL = "retrieval"          # 检索结果
    TOOL_OUTPUT = "tool_output"      # 工具执行结果
    MODEL_OUTPUT = "model_output"    # 模型输出


class TrustLevel(str, Enum):
    """内容信任级别"""
    TRUSTED = "trusted"              # 经授权确认
    UNTRUSTED = "untrusted"          # 未经授权


@dataclass
class ContentSource:
    """内容来源标记"""
    source_id: str
    source_type: SourceType
    trust_level: TrustLevel
    origin: str                       # user_id:issue_id / repo_id:file_path
    created_at: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class DetectionResult:
    """检测结果"""
    is_injection: bool
    risk_level: RiskLevel
    confidence: float                 # 0.0 ~ 1.0
    detected_patterns: list[str]
    evidence: list[str]
    recommendation: str
    source: ContentSource | None = None
    blocking_reason: str | None = None


class FastRejectFilter:
    """
    快速拒绝层（第1层）- 同步执行
    
    职责：
    - 检测明确的恶意关键词
    - 检测隐藏字符（零宽空格、RTL标记等）
    - 检测HTML注释中的隐藏内容
    - 检测高危正则模式
    
    延迟目标：< 5ms
    """

    # ===== 关键词黑名单 =====
    FORBIDDEN_KEYWORDS = {
        # 直接指令覆盖
        "ignore the above", "ignore previous", "ignore all", "ignore instructions",
        "forget all", "disregard", "override all", "bypass all", "override", "bypass",
        
        # 系统指令引用
        "system prompt", "system instructions", "system override",
        "your instructions", "your rules", "your guidelines",
        
        # 权限提升
        "administrator", "admin access", "super user", "root",
        "sudo", "elevated", "unrestricted", "no restrictions",
        
        # 恶意操作
        "delete all", "drop table", "remove database", "drop database",
        "execute command", "run shell", "eval code",
        
        # 逃逸尝试
        "jailbreak", "break out", "escape sandbox", "escape restrictions",
        "bypass security", "circumvent", "exploit",
    }

    # ===== 隐藏字符检测 =====
    HIDDEN_CHARS = {
        "\u200b": "zero-width space",
        "\u200c": "zero-width non-joiner",
        "\u200d": "zero-width joiner",
        "\u200e": "left-to-right mark",
        "\u200f": "right-to-left mark",
        "\u202a": "left-to-right embedding",
        "\u202b": "right-to-left embedding",
        "\u202c": "pop directional formatting",
        "\u202d": "left-to-right override",
        "\u202e": "right-to-left override",
        "\u2060": "word joiner",
        "\u2061": "function application",
        "\ufeff": "zero-width no-break space",
    }

    # ===== 高危正则模式 =====
    CRITICAL_PATTERNS = {
        # 指令覆盖
        "instruction_override": re.compile(
            r"ignore\s+(?:the\s+)?(?:previous|above|earlier|all|prior|instructions)",
            re.IGNORECASE
        ),
        "system_override": re.compile(
            r"(?:system|your)\s+(?:override|bypass|disable)",
            re.IGNORECASE
        ),
        
        # 权限提升
        "privilege_escalation": re.compile(
            r"(?:i\s+am|you\s+are)\s+(?:an?\s+)?(?:admin|administrator|superuser|root)",
            re.IGNORECASE
        ),
        
        # 数据外泄
        "data_exfiltration": re.compile(
            r"(?:send|transmit|exfiltrate|leak|upload)\s+.*?(?:to|via)\s+(?:http|ftp|mail|http:\/\/|https:\/\/)",
            re.IGNORECASE
        ),
        
        # 恶意代码注入
        "code_injection": re.compile(
            r"(?:execute|run|eval|exec)\s+(?:this\s+)?(?:python|javascript|code|command|shell|sql)",
            re.IGNORECASE
        ),
    }

    def __init__(self) -> None:
        self._keyword_pattern = re.compile(
            "|".join(re.escape(kw) for kw in self.FORBIDDEN_KEYWORDS),
            re.IGNORECASE
        )

    async def check(self, text: str) -> tuple[bool, list[str], RiskLevel]:
        """
        快速检查内容
        
        返回: (should_reject, matched_patterns, risk_level)
        
        Args:
            text: 输入文本
            
        Returns:
            - should_reject: True 表示应立即拒绝
            - matched_patterns: 命中的模式名称列表
            - risk_level: 评估的风险等级
        """
        matched = []
        max_severity = RiskLevel.LOW

        # 1. 检测隐藏字符
        hidden_found = self._detect_hidden_chars(text)
        if hidden_found:
            matched.extend(hidden_found)
            # 隐藏字符通常是可疑的
            if any("right-to-left override" in m for m in hidden_found):
                max_severity = RiskLevel.HIGH
            else:
                max_severity = RiskLevel.MEDIUM

        # 2. 检测HTML注释中的内容
        html_comment_found = self._detect_html_comments(text)
        if html_comment_found:
            matched.extend(html_comment_found)
            max_severity = RiskLevel.MEDIUM

        # 3. 检测关键词
        keyword_found = self._detect_keywords(text)
        if keyword_found:
            matched.extend(keyword_found)
            max_severity = RiskLevel.HIGH

        # 4. 检测高危正则
        for pattern_name, pattern_regex in self.CRITICAL_PATTERNS.items():
            if pattern_regex.search(text):
                matched.append(pattern_name)
                if pattern_name == "data_exfiltration":
                    max_severity = RiskLevel.CRITICAL
                elif pattern_name in ("code_injection", "privilege_escalation"):
                    max_severity = RiskLevel.HIGH
                else:
                    if max_severity == RiskLevel.LOW:
                        max_severity = RiskLevel.MEDIUM

        # 决策
        should_reject = max_severity in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        
        logger.debug(
            f"FastRejectFilter: matched={matched}, severity={max_severity}, reject={should_reject}"
        )
        
        return should_reject, matched, max_severity

    def _detect_hidden_chars(self, text: str) -> list[str]:
        """检测隐藏字符"""
        found = []
        for char, name in self.HIDDEN_CHARS.items():
            if char in text:
                found.append(f"hidden_char_{name}")
        return found

    def _detect_html_comments(self, text: str) -> list[str]:
        """检测HTML注释"""
        if "<!--" in text and "-->" in text:
            # 提取HTML注释内容
            pattern = re.compile(r"<!--(.*?)-->", re.DOTALL)
            comments = pattern.findall(text)
            if comments:
                # 检查注释中是否有可疑内容
                for comment in comments:
                    if self._keyword_pattern.search(comment):
                        return ["html_comment_injection"]
            return ["html_comment"]
        return []

    def _detect_keywords(self, text: str) -> list[str]:
        """检测黑名单关键词"""
        matches = self._keyword_pattern.findall(text.lower())
        return [f"keyword_{m.replace(' ', '_')}" for m in set(matches)]


class HeuristicDetector:
    """
    启发式检测层（第2层）- 可异步执行
    
    职责：
    - 指令转移检测
    - 权限提升企图检测
    - 系统访问检测
    - 代码注入检测
    
    延迟目标：20-50ms
    """

    # 各维度的权重
    DIMENSIONS = {
        "instruction_override": 0.30,
        "privilege_escalation": 0.25,
        "system_access": 0.25,
        "code_injection": 0.20,
    }

    # 指令转移关键词
    INSTRUCTION_OVERRIDE_KEYWORDS = {
        "you are", "you're", "act as", "pretend",
        "imagine you are", "roleplay", "assume you are",
        "think you are", "behave as", "you are now",
    }

    # 权限提升关键词
    PRIVILEGE_ESCALATION_KEYWORDS = {
        "admin", "administrator", "sudo", "root",
        "superuser", "system", "elevated", "unrestricted",
        "no restrictions", "bypass", "override",
    }

    # 系统访问关键词
    SYSTEM_ACCESS_KEYWORDS = {
        "system prompt", "system instructions", "your instructions",
        "your rules", "your guidelines", "constraints",
        "limitations", "don't", "must not", "forbidden",
    }

    # 代码注入关键词
    CODE_INJECTION_KEYWORDS = {
        "execute", "run", "eval", "exec", "shell",
        "command", "python", "javascript", "code",
        "script", "backdoor", "payload", "exploit",
    }

    def __init__(self) -> None:
        pass

    async def analyze(self, text: str) -> tuple[float, dict[str, float]]:
        """
        启发式分析
        
        返回: (总风险评分 0.0~1.0, 各维度得分)
        
        Args:
            text: 输入文本
            
        Returns:
            - total_score: 综合风险评分
            - dimension_scores: 各维度得分
        """
        scores = {}

        # 1. 指令转移检测
        scores["instruction_override"] = self._detect_instruction_override(text)

        # 2. 权限提升检测
        scores["privilege_escalation"] = self._detect_privilege_escalation(text)

        # 3. 系统访问检测
        scores["system_access"] = self._detect_system_access(text)

        # 4. 代码注入检测
        scores["code_injection"] = self._detect_code_injection(text)

        # 计算加权总分
        total_score = sum(
            scores[dim] * self.DIMENSIONS[dim]
            for dim in self.DIMENSIONS
        )

        logger.debug(
            f"HeuristicDetector: dimension_scores={scores}, total={total_score:.2f}"
        )

        return min(total_score, 1.0), scores

    def _detect_instruction_override(self, text: str) -> float:
        """指令转移检测"""
        text_lower = text.lower()
        score = 0.0

        # 检查关键词
        for keyword in self.INSTRUCTION_OVERRIDE_KEYWORDS:
            if keyword in text_lower:
                score += 0.15
                break

        # 检查指令转移模式（如"you are now X"）
        if re.search(r"you\s+(?:are\s+)?(?:now|actually|really)", text_lower):
            score += 0.35

        return min(score, 1.0)

    def _detect_privilege_escalation(self, text: str) -> float:
        """权限提升企图检测"""
        text_lower = text.lower()
        score = 0.0

        # 检查权限提升关键词
        keyword_count = sum(
            1 for kw in self.PRIVILEGE_ESCALATION_KEYWORDS
            if kw in text_lower
        )
        score += min(keyword_count * 0.2, 0.8)

        return min(score, 1.0)

    def _detect_system_access(self, text: str) -> float:
        """系统访问检测"""
        text_lower = text.lower()
        score = 0.0

        # 检查系统访问关键词
        for keyword in self.SYSTEM_ACCESS_KEYWORDS:
            if keyword in text_lower:
                score += 0.2

        # 检查是否尝试读取系统信息
        pattern = r"(?:show|print|reveal|output).*(?:system|prompt|instruction|rules)"
        if re.search(pattern, text_lower):
            score += 0.4

        return min(score, 1.0)

    def _detect_code_injection(self, text: str) -> float:
        """代码注入检测"""
        text_lower = text.lower()
        score = 0.0

        # 检查代码注入关键词
        keyword_count = sum(
            1 for kw in self.CODE_INJECTION_KEYWORDS
            if kw in text_lower
        )
        score += min(keyword_count * 0.25, 0.75)

        # 检查SQL/Python代码特征
        if re.search(r"(?:insert|update|delete|drop)\s+(?:into|from)?", text_lower):
            score += 0.3
        if re.search(r"import\s+|\s+as\s+|def\s+|class\s+", text_lower):
            score += 0.2

        return min(score, 1.0)


class PromptInjectionDetector:
    """
    完整的 Prompt 注入检测引擎
    
    整合第1层和第2层，实现完整的双层防护。
    """

    def __init__(
        self,
        fast_reject_threshold: float = 0.5,
        heuristic_threshold: float = 0.6,
    ) -> None:
        """
        初始化检测器
        
        Args:
            fast_reject_threshold: 快速拒绝阈值
            heuristic_threshold: 启发式分析阈值
        """
        self.fast_reject_filter = FastRejectFilter()
        self.heuristic_detector = HeuristicDetector()
        self.fast_reject_threshold = fast_reject_threshold
        self.heuristic_threshold = heuristic_threshold
        self._detection_cache: dict[int, DetectionResult] = {}

    async def detect(
        self,
        text: str,
        source: ContentSource | None = None,
    ) -> DetectionResult:
        """
        完整的 Prompt 注入检测流程
        
        1. 快速拒绝（同步，< 5ms）
        2. 启发式分析（可异步，20-50ms）
        3. 综合决策
        
        Args:
            text: 输入文本
            source: 内容来源信息
            
        Returns:
            DetectionResult: 检测结果
        """
        # 缓存检查
        text_hash = hash(text)
        if text_hash in self._detection_cache:
            return self._detection_cache[text_hash]

        # ===== 第1层：快速拒绝 =====
        should_reject_fast, fast_patterns, fast_severity = await self.fast_reject_filter.check(text)

        if should_reject_fast and fast_severity == RiskLevel.CRITICAL:
            # CRITICAL 直接拒绝
            result = DetectionResult(
                is_injection=True,
                risk_level=RiskLevel.CRITICAL,
                confidence=0.99,
                detected_patterns=fast_patterns,
                evidence=[f"快速拒绝层检测到严重威胁: {fast_patterns}"],
                recommendation="BLOCK: 严重 Prompt 注入已检测，立即拒绝",
                source=source,
                blocking_reason="CRITICAL_INJECTION_DETECTED",
            )
            self._detection_cache[text_hash] = result
            return result

        # ===== 第2层：启发式分析 =====
        heuristic_score, dimension_scores = await self.heuristic_detector.analyze(text)

        # ===== 综合决策 =====
        # 结合两层结果
        confidence = self._combine_scores(fast_severity, fast_patterns, heuristic_score)

        # 确定最终风险等级
        if confidence >= 0.85:
            risk_level = RiskLevel.CRITICAL
        elif confidence >= 0.6:
            risk_level = RiskLevel.HIGH
        elif confidence >= 0.4:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW

        is_injection = confidence > 0.5 or fast_severity in (RiskLevel.HIGH, RiskLevel.CRITICAL)

        # 收集证据
        evidence = self._build_evidence(
            fast_patterns, dimension_scores, heuristic_score
        )

        # 生成建议
        recommendation = self._get_recommendation(risk_level, fast_patterns)

        result = DetectionResult(
            is_injection=is_injection,
            risk_level=risk_level,
            confidence=confidence,
            detected_patterns=fast_patterns,
            evidence=evidence,
            recommendation=recommendation,
            source=source,
        )

        # 缓存结果
        self._detection_cache[text_hash] = result

        logger.info(
            f"PromptInjectionDetector: risk={risk_level}, confidence={confidence:.2f}, "
            f"patterns={fast_patterns}, heuristic_score={heuristic_score:.2f}"
        )

        return result

    def _combine_scores(
        self,
        fast_severity: RiskLevel,
        fast_patterns: list[str],
        heuristic_score: float,
    ) -> float:
        """合并两层检测的评分"""
        # 快速拒绝层得分
        fast_score_map = {
            RiskLevel.LOW: 0.0,
            RiskLevel.MEDIUM: 0.6,
            RiskLevel.HIGH: 0.85,
            RiskLevel.CRITICAL: 0.99,
        }
        fast_score = fast_score_map.get(fast_severity, 0.0)

        # 如果快速拒绝层检测到高风险，给予更高权重
        if fast_severity in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            # 快速拒绝层权重 70%
            combined = fast_score * 0.7 + heuristic_score * 0.3
        else:
            # 快速拒绝层权重 30%，启发式分析权重 70%
            combined = fast_score * 0.3 + heuristic_score * 0.7

        return min(combined, 1.0)

    def _build_evidence(
        self,
        fast_patterns: list[str],
        dimension_scores: dict[str, float],
        heuristic_score: float,
    ) -> list[str]:
        """构建证据列表"""
        evidence = []

        # 快速拒绝层证据
        if fast_patterns:
            evidence.append(f"快速拒绝层检测: {', '.join(fast_patterns)}")

        # 启发式分析证据
        for dim, score in dimension_scores.items():
            if score > 0.3:
                evidence.append(f"启发式分析-{dim}: {score:.2f}")

        if heuristic_score > 0.6:
            evidence.append(f"综合启发式评分: {heuristic_score:.2f} (高风险)")

        return evidence

    def _get_recommendation(self, risk_level: RiskLevel, patterns: list[str]) -> str:
        """生成处理建议"""
        if risk_level == RiskLevel.CRITICAL:
            return "BLOCK: 检测到严重 Prompt 注入。立即拒绝输入并记录。"
        elif risk_level == RiskLevel.HIGH:
            return "BLOCK: 检测到高风险 Prompt 注入。拒绝输入并审计。"
        elif risk_level == RiskLevel.MEDIUM:
            return "WARN: 检测到可疑模式。允许继续但记录警告。"
        else:
            return "ALLOW: 输入安全，允许处理。"

    def clear_cache(self) -> None:
        """清除检测缓存"""
        self._detection_cache.clear()
