"""
Trace 传播和审计关联模块。

对应契约：docs/design-specs/REQ-RT-006-Trace-传播和审计关联.md

本模块实现基于 OpenTelemetry 的分布式追踪能力：
- TraceContext：追踪上下文（TraceId + SpanId）
- Propagation：W3C Trace Context 传播（注入/提取）
- Tracer：OpenTelemetry Tracer 封装
- SpanBuilder：创建 Task/Workflow/Worker/Action Span
- Sampling：采样策略（默认 15%）
- AuditCorrelation：审计记录关联 TraceId

核心原则（REQ-RT-006）：
- Trace 与业务 ID 分离（TaskId ≠ TraceId）
- 审计记录不受采样影响（100% 写入）
- 默认不记录敏感内容（Prompt/代码/凭据）
- 跨服务传播受信任边界控制
"""

from .context import TraceContext
from .propagation import TracePropagator, extract_trace_context, inject_trace_context
from .tracer import SpanKind, create_span, get_tracer

__all__ = [
    "TraceContext",
    "TracePropagator",
    "extract_trace_context",
    "inject_trace_context",
    "get_tracer",
    "create_span",
    "SpanKind",
]
