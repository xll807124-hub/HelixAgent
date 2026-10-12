"""
OpenTelemetry Integration - 分布式追踪和可观测性

设计:
  - Trace Context: 跨服务传播 TraceID/SpanID
  - Span Instrumentation: 关键路径的 span 创建和属性
  - Exporter: 导出到 Jaeger/Datadog
  - Sampling: 智能采样策略
"""
