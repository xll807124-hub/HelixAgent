"""
Policy Gateway 模块导出

提供策略网关功能：
- PolicyGateway: 策略网关接口
- SimplifiedPolicyGateway: 简化版实现
- OPAClient: OPA 客户端（遗留，延迟导入）
- PolicyDecision: 策略决策枚举
- PolicyResult: 策略结果模型
"""
from typing import Any

from .base import PolicyDecision, PolicyGateway, PolicyResult
from .gateway import SimplifiedPolicyGateway


# OPAClient 延迟导入，避免 requests 依赖问题
def __getattr__(name: str) -> Any:
    if name == "OPAClient":
        from .opa_client import OPAClient
        return OPAClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # 接口
    "PolicyGateway",

    # 实现
    "SimplifiedPolicyGateway",
    "OPAClient",

    # 枚举和模型
    "PolicyDecision",
    "PolicyResult",
]
