"""
采样策略配置。

对应契约：docs/design-specs/REQ-RT-006-Trace-传播和审计关联.md §5.4（采样决策）

提供灵活的采样策略配置：
- 默认 15% 全 Trace 采样
- 高风险任务可提高采样优先级
- 采样不影响审计记录（审计 100% 写入）
"""
from __future__ import annotations

from enum import Enum

from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    Sampler,
    TraceIdRatioBased,
)


class SamplingPriority(str, Enum):
    """采样优先级（REQ-RT-006 §5.4）。"""

    DEFAULT = "DEFAULT"  # 默认采样率（15%）
    HIGH = "HIGH"  # 高优先级（100%）
    DISABLED = "DISABLED"  # 禁用追踪（0%）


class SamplingStrategy:
    """采样策略管理器（REQ-RT-006 §5.4）。

    核心原则：
    - 默认 15% 采样率（完整 Trace 采样，避免碎片）
    - 高风险任务、失败、审批等场景可提高优先级
    - 采样不影响审计记录（审计独立路径 100% 写入）
    """

    DEFAULT_SAMPLING_RATE = 0.15  # 15%

    @staticmethod
    def get_sampler(
        priority: SamplingPriority = SamplingPriority.DEFAULT,
        custom_rate: float | None = None,
    ) -> Sampler:
        """获取采样器。

        Args:
            priority: 采样优先级
            custom_rate: 自定义采样率（0.0-1.0），覆盖优先级默认值

        Returns:
            OpenTelemetry Sampler 实例

        Example:
            >>> # 默认 15% 采样
            >>> sampler = SamplingStrategy.get_sampler()
            >>>
            >>> # 高风险任务 100% 采样
            >>> sampler = SamplingStrategy.get_sampler(SamplingPriority.HIGH)
            >>>
            >>> # 自定义 50% 采样
            >>> sampler = SamplingStrategy.get_sampler(custom_rate=0.5)
        """
        if custom_rate is not None:
            # 自定义采样率
            if not 0.0 <= custom_rate <= 1.0:
                raise ValueError(f"采样率必须在 0.0-1.0 范围内，收到: {custom_rate}")
            base_sampler = TraceIdRatioBased(custom_rate)
        elif priority == SamplingPriority.HIGH:
            # 高优先级：100% 采样
            base_sampler = ALWAYS_ON
        elif priority == SamplingPriority.DISABLED:
            # 禁用追踪：0% 采样
            base_sampler = ALWAYS_OFF
        else:
            # 默认：15% 采样
            base_sampler = TraceIdRatioBased(SamplingStrategy.DEFAULT_SAMPLING_RATE)

        # 使用 ParentBased 包装，确保父 Span 已采样时子 Span 也采样
        return ParentBased(root=base_sampler)

    @staticmethod
    def should_sample_task(
        task_type: str | None = None,
        is_high_risk: bool = False,
        has_failure: bool = False,
        is_recovery: bool = False,
        explicit_request: bool = False,
    ) -> SamplingPriority:
        """判断任务是否应该提高采样优先级（REQ-RT-006 §5.4）。

        Args:
            task_type: 任务类型
            is_high_risk: 是否高风险任务
            has_failure: 是否包含失败
            is_recovery: 是否恢复操作
            explicit_request: 是否显式诊断请求

        Returns:
            采样优先级

        提高采样优先级的场景（REQ-RT-006 §5.4）：
        - 高风险任务
        - 安全策略拒绝
        - 审批操作
        - 任务失败
        - Checkpoint 恢复
        - Kill Switch 触发
        - 异常副作用状态
        - 明确诊断请求
        """
        if explicit_request or is_high_risk or has_failure or is_recovery:
            return SamplingPriority.HIGH

        return SamplingPriority.DEFAULT
