"""
简化版 Policy Gateway 实现

对齐设计文档：REQ-SEC-003 Policy Gateway
注：本阶段为简化实现，完整版（OPA 集成、复杂策略）推迟到阶段 1.3
"""
from __future__ import annotations

import inspect
import re
from typing import Any, cast

from ...tools.base import BaseTool, ExecutionContext, RiskLevel, ValidationResult
from ...tools.registry import ToolRegistry
from .base import PolicyDecision, PolicyGateway, PolicyResult


class SimplifiedPolicyGateway(PolicyGateway):
    """
    简化版策略网关
    
    实现策略：
    1. 前置检查：工具存在性、Schema 校验、风险级别判断
    2. 后置检查：输出 Schema 校验、敏感信息检测
    
    简化点（待阶段 1.3 完善）：
    - 无 OPA 集成，策略硬编码
    - 无复杂 RBAC 规则，仅基于风险级别
    - 无审批流程，高风险操作返回 REQUIRES_APPROVAL
    - 无完整脱敏策略，仅基于正则检测
    """

    # 敏感信息正则模式（REQ-SEC-003 §7.3 简化版）
    SENSITIVE_PATTERNS = {
        "api_key": re.compile(
            r"api[_-]?key['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9_-]{20,})",
            re.IGNORECASE
        ),
        "password": re.compile(
            r"password['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9!@#$%^&*()_+\-=\[\]{};:,.<>?]{8,})",
            re.IGNORECASE
        ),
        "token": re.compile(
            r"token['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9_-]{20,})",
            re.IGNORECASE
        ),
        "secret": re.compile(
            r"secret['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9_-]{20,})",
            re.IGNORECASE
        ),
        "private_key": re.compile(
            r"-----BEGIN [A-Z]+ PRIVATE KEY-----",
            re.IGNORECASE
        ),
    }

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """
        初始化策略网关
        
        Args:
            tool_registry: 工具注册表（用于查找工具和校验 Schema）
        """
        self._tool_registry = tool_registry

    async def check_pre_execution(
        self,
        action_id: str,
        tool_name: str,
        params: dict[str, Any],
        context: dict[str, Any]
    ) -> PolicyResult:
        """
        执行前策略检查
        
        检查流程：
        1. 工具存在性检查
        2. 输入 Schema 校验
        3. 风险级别判断（HIGH → REQUIRES_APPROVAL）
        """
        # 步骤1: 工具存在性检查
        tool = self._tool_registry.get_tool(tool_name)
        if tool is None:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason=f"Tool '{tool_name}' not found",
                violations=[f"Tool '{tool_name}' is not registered"]
            )

        # 步骤2: 输入 Schema 校验
        # 工具的 validate_input 签名不统一：有的是 (params)，有的是 (params, context)，
        # 有的是 async。这里按签名分派，避免 TypeError 导致整个 Action 崩溃。
        try:
            validation_result = await self._run_validation(tool, action_id, params, context)
        except Exception as e:  # noqa: BLE001 - 校验器异常一律视为拒绝（默认拒绝原则）
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="Input validation raised an error",
                violations=[f"{type(e).__name__}: {e}"],
            )
        if not validation_result.valid:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="Input validation failed",
                violations=validation_result.errors
            )

        # 步骤3: 风险级别判断
        if tool.risk_level == RiskLevel.HIGH:
            return PolicyResult(
                decision=PolicyDecision.REQUIRES_APPROVAL,
                reason=f"High-risk tool '{tool_name}' requires manual approval",
                metadata={
                    "risk_level": tool.risk_level.value,
                    "requires_approval": True
                }
            )

        # 通过所有检查
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            reason="Pre-execution checks passed",
            metadata={
                "risk_level": tool.risk_level.value
            }
        )

    @staticmethod
    async def _run_validation(
        tool: BaseTool,
        action_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> ValidationResult:
        """按工具 validate_input 的签名调用，并兼容同步/异步实现。"""
        validator: Any = tool.validate_input
        if "context" in inspect.signature(validator).parameters:
            exec_ctx = ExecutionContext(
                trace_id=str(context.get("trace_id", "unknown")),
                action_id=action_id,
                user_id=str(context.get("user_id", "unknown")),
                organization_id=str(context.get("organization_id", "unknown")),
                project_id=str(context.get("project_id", "unknown")),
                task_id=str(context.get("task_id", "unknown")),
                allowed_paths=list(context.get("allowed_paths") or []),
                read_only=bool(context.get("read_only", False)),
            )
            result = validator(params, exec_ctx)
        else:
            result = validator(params)
        if inspect.isawaitable(result):
            result = await result
        return cast(ValidationResult, result)

    async def check_post_execution(
        self,
        action_id: str,
        tool_name: str,
        output: Any,
        context: dict[str, Any]
    ) -> PolicyResult:
        """
        执行后策略检查
        
        检查流程：
        1. 输出类型检查
        2. 敏感信息检测（简化版）
        3. 输出大小限制
        """
        violations: list[str] = []

        # 步骤1: 输出类型检查
        if not isinstance(output, dict):
            violations.append(f"Output must be dict, got {type(output).__name__}")
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="Output validation failed",
                violations=violations
            )

        # 步骤2: 敏感信息检测
        sensitive_found = self._detect_sensitive_info(output)
        if sensitive_found:
            violations.extend([
                f"Sensitive information detected: {pattern}"
                for pattern in sensitive_found
            ])

            # 简化版：检测到敏感信息则标记，但不自动脱敏（完整版在阶段 1.3）
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="Sensitive information detected in output",
                violations=violations,
                metadata={
                    "sensitive_patterns": sensitive_found
                }
            )

        # 步骤3: 输出大小限制（简化版：只检查字符串长度）
        output_str = str(output)
        max_output_size = 10 * 1024 * 1024  # 10MB
        if len(output_str) > max_output_size:
            violations.append(
                f"Output too large: {len(output_str)} bytes (max: {max_output_size})"
            )
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="Output size exceeded limit",
                violations=violations
            )

        # 通过所有检查
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            reason="Post-execution checks passed"
        )

    def _detect_sensitive_info(self, output: dict[str, Any]) -> list[str]:
        """
        检测输出中的敏感信息（简化版）
        
        策略：
        - 将输出转为字符串
        - 用正则匹配敏感模式
        - 返回匹配到的模式名称
        
        Args:
            output: 工具输出
        
        Returns:
            list[str]: 匹配到的敏感模式名称列表
        """
        output_str = str(output)
        found_patterns: list[str] = []

        for pattern_name, pattern_regex in self.SENSITIVE_PATTERNS.items():
            if pattern_regex.search(output_str):
                found_patterns.append(pattern_name)

        return found_patterns
