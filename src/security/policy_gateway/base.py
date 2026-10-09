"""
Policy Gateway 基础接口

对齐设计文档：REQ-SEC-003 Policy Gateway
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PolicyDecision(str, Enum):
    """策略决策结果（REQ-SEC-003 §5.1）"""
    ALLOW = "ALLOW"                      # 允许执行
    DENY = "DENY"                        # 拒绝执行
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"  # 需要人工审批


class PolicyResult(BaseModel):
    """策略校验结果（REQ-SEC-003 §5.2）"""
    decision: PolicyDecision
    reason: str = ""
    violations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyGateway(ABC):
    """
    策略网关接口
    
    职责（REQ-SEC-003）：
    1. Action 执行前的权限和策略检查
    2. Action 执行后的输出校验和脱敏
    3. 决策结果审计
    
    设计原则：
    - 零信任：默认拒绝，显式允许
    - 双重校验：前置 + 后置
    - 可审计：每个决策可追溯
    """

    @abstractmethod
    async def check_pre_execution(
        self,
        action_id: str,
        tool_name: str,
        params: dict[str, Any],
        context: dict[str, Any]
    ) -> PolicyResult:
        """
        执行前策略检查
        
        检查项：
        1. 工具是否存在且可用
        2. 参数是否符合 Schema
        3. 用户是否有权限执行该工具
        4. 风险级别是否需要审批
        
        Args:
            action_id: Action ID（用于审计）
            tool_name: 工具名称
            params: 工具参数
            context: 执行上下文（user_id, organization_id 等）
        
        Returns:
            PolicyResult: 策略决策结果
        """
        pass

    @abstractmethod
    async def check_post_execution(
        self,
        action_id: str,
        tool_name: str,
        output: Any,
        context: dict[str, Any]
    ) -> PolicyResult:
        """
        执行后策略检查
        
        检查项：
        1. 输出是否符合预期 Schema
        2. 输出是否包含敏感信息（需脱敏）
        3. 输出大小是否超限
        
        Args:
            action_id: Action ID（用于审计）
            tool_name: 工具名称
            output: 工具输出结果
            context: 执行上下文
        
        Returns:
            PolicyResult: 策略决策结果（如需脱敏，在 metadata 中返回脱敏后的输出）
        """
        pass
