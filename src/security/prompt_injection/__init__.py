"""
Prompt 注入防护模块

对齐设计文档：REQ-SEC-006 Prompt 注入防护
"""
from .detector import (
    DetectionResult,
    PromptInjectionDetector,
    RiskLevel,
)

__all__ = [
    "PromptInjectionDetector",
    "DetectionResult",
    "RiskLevel",
]
