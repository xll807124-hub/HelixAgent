"""
OpenTelemetry Tracer 封装。

对应契约：docs/design-specs/REQ-RT-006-Trace-传播和审计关联.md §4（追踪与审计架构）

封装 OpenTelemetry SDK，提供简化的 Tracer 和 Span 创建接口：
- get_tracer：获取 Tracer 实例
- create_span：创建 Span（Task/Workflow/Worker/Action）
- SpanKind：Span 类型枚举
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

from .context import TraceContext


class SpanKind(str, Enum):
    """Span 类型（REQ-RT-006 §4.1 Span 层级）。"""

    TASK = "TASK"  # Task / agent invocation
    WORKFLOW = "WORKFLOW"  # Workflow execution
    WORKER = "WORKER"  # Worker execution
    ACTION = "ACTION"  # Action
    TOOL = "TOOL"  # Tool execution
    MODEL = "MODEL"  # Model request
    SANDBOX = "SANDBOX"  # Sandbox operation
    POLICY = "POLICY"  # Policy decision / approval wait
    ARTIFACT = "ARTIFACT"  # Artifact / Evidence production


# 全局 TracerProvider（延迟初始化）
_tracer_provider: TracerProvider | None = None
_default_tracer: trace.Tracer | None = None


def _init_tracer_provider(sampling_rate: float = 0.15) -> TracerProvider:
    """初始化 TracerProvider（REQ-RT-006 §5.4 默认 15% 采样率）。

    MVP 阶段使用 ConsoleSpanExporter（输出到控制台），
    生产环境应替换为 OTLP Exporter。

    Args:
        sampling_rate: 采样率（0.0-1.0），默认 0.15（15%）
    """
    global _tracer_provider

    if _tracer_provider is not None:
        return _tracer_provider

    # 创建采样器（TraceIdRatioBased：按 TraceId 哈希采样，保证完整 Trace 采样）
    sampler = TraceIdRatioBased(sampling_rate)

    # 创建 TracerProvider
    provider = TracerProvider(sampler=sampler)

    # 添加 Span Processor（MVP 使用 ConsoleSpanExporter）
    # 生产环境应使用：BatchSpanProcessor + OTLPSpanExporter
    processor = SimpleSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)

    # 设置全局 TracerProvider
    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    return provider


def get_tracer(name: str = "ai_agent_platform") -> trace.Tracer:
    """获取 Tracer 实例。

    Args:
        name: Tracer 名称（通常是模块名或组件名）

    Returns:
        Tracer 实例
    """
    global _default_tracer

    if _default_tracer is None:
        # 确保 TracerProvider 已初始化
        _init_tracer_provider()
        _default_tracer = trace.get_tracer(name)

    return _default_tracer


@contextmanager
def create_span(
    name: str,
    kind: SpanKind,
    trace_context: TraceContext | None = None,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """创建 Span 上下文管理器（REQ-RT-006 §4.1）。

    Args:
        name: Span 名称（如 "Task.execute", "Worker.plan"）
        kind: Span 类型
        trace_context: 父 TraceContext（None 时创建新根 Span）
        attributes: Span 属性（业务关联字段：task_id, workflow_id 等）

    Yields:
        Span 实例

    Example:
        >>> with create_span("Task.execute", SpanKind.TASK, ctx, {"task_id": "..."}) as span:
        ...     # 执行任务
        ...     span.set_attribute("status", "success")

    核心原则（REQ-RT-006 §4.2）：
    - 必须关联稳定业务坐标（task_id, workflow_id 等）
    - 不得将自由文本、完整路径作为高基数属性
    """
    tracer = get_tracer()

    # 设置父上下文
    if trace_context is not None:
        # 从 TraceContext 恢复 OpenTelemetry Context
        ctx = trace.set_span_in_context(
            trace.NonRecordingSpan(
                trace.SpanContext(
                    trace_id=int(trace_context.trace_id, 16),
                    span_id=int(trace_context.span_id, 16),
                    is_remote=False,
                    trace_flags=trace.TraceFlags(trace_context.trace_flags),
                )
            )
        )
    else:
        ctx = None

    # 创建 Span
    with tracer.start_as_current_span(name, context=ctx) as span:
        # 设置 Span 类型
        span.set_attribute("span.kind", kind.value)

        # 设置业务属性
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)

        yield span


def get_current_trace_context() -> TraceContext | None:
    """获取当前 Span 的 TraceContext。

    Returns:
        当前 TraceContext，无活跃 Span 时返回 None
    """
    span = trace.get_current_span()
    if not span or not span.is_recording():
        return None

    span_context = span.get_span_context()
    if not span_context.is_valid:
        return None

    return TraceContext(
        trace_id=format(span_context.trace_id, "032x"),
        span_id=format(span_context.span_id, "016x"),
        trace_flags=span_context.trace_flags,
    )


def generate_span_id() -> str:
    """生成新的 SpanId（16 位十六进制）。"""
    return uuid.uuid4().hex[:16]
