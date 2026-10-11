"""
OTel ↔ TraceContext 桥接（src/observability/context.py）。

设计原则：
- TraceContext 是 REQ-RT-006 冻结的 Pydantic 模型（不可改）
- OTel SpanContext 由 SDK 维护（不可改）
- 本模块只做单向桥接：OTel SpanContext → TraceContext；TraceContext 已在 HTTP header 中时优先使用
"""
from __future__ import annotations

from opentelemetry import trace
from opentelemetry.trace import SpanContext, TraceFlags

from src.runtime.trace.context import TraceContext


def format_trace_id(trace_id_int: int) -> str:
    """OTel trace_id (int) → 32 hex 字符串（REQ-RT-006）。"""
    return format(trace_id_int, "032x")


def format_span_id(span_id_int: int) -> str:
    """OTel span_id (int) → 16 hex 字符串（REQ-RT-006）。"""
    return format(span_id_int, "016x")


def current_span_context() -> TraceContext | None:
    """从当前 OTel context 提取 TraceContext；如无 active span 则返回 None。"""
    span = trace.get_current_span()
    sc: SpanContext = span.get_span_context()
    if not sc.is_valid:
        return None
    flags_value = int(sc.trace_flags or TraceFlags(0))
    return TraceContext(
        trace_id=format_trace_id(sc.trace_id),
        span_id=format_span_id(sc.span_id),
        trace_flags=flags_value,
        baggage={},
    )


def is_otel_sdk_active() -> bool:
    """检查 OTel SDK 是否已初始化（避免 OTel disabled 时仍尝试创建 span）。"""
    provider = trace.get_tracer_provider()
    # TracerProvider 默认实例是 ProxyTracerProvider，仅在 SDK init 后才返回真实 provider
    return provider.__class__.__name__ == "TracerProvider"


__all__ = [
    "current_span_context",
    "format_span_id",
    "format_trace_id",
    "is_otel_sdk_active",
]