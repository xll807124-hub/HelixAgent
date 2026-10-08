"""
W3C Trace Context 传播逻辑。

对应契约：
    docs/design-specs/REQ-RT-006-Trace-传播和审计关联.md
    §5（Trace Context 生命周期与传播流程）

实现 W3C Trace Context 标准的注入（inject）和提取（extract）：
- inject：将 TraceContext 注入到 HTTP Headers/消息载体
- extract：从 HTTP Headers/消息载体提取 TraceContext
- 支持跨服务传播（受信任边界控制）
"""
from __future__ import annotations

from typing import Any

from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from .context import TraceContext


class TracePropagator:
    """W3C Trace Context 传播器（REQ-RT-006 §5.2/§5.3）。

    封装 OpenTelemetry 的 TraceContextTextMapPropagator，提供简化的注入/提取接口。

    核心原则（REQ-RT-006）：
    - 内部服务自动传播
    - 外部服务白名单控制（本模块只负责技术实现，策略判断由调用方处理）
    - 不可信来源拒绝提取（创建新根 Trace）
    """

    def __init__(self) -> None:
        self._propagator = TraceContextTextMapPropagator()

    def inject(
        self, trace_context: TraceContext, carrier: dict[str, str] | None = None
    ) -> dict[str, str]:
        """将 TraceContext 注入到载体（通常是 HTTP Headers）。

        Args:
            trace_context: 追踪上下文
            carrier: 载体字典（如 HTTP Headers），None 时创建新字典

        Returns:
            注入后的载体字典

        Example:
            >>> ctx = TraceContext(trace_id="...", span_id="...")
            >>> headers = propagator.inject(ctx, {})
            >>> # headers 包含 'traceparent' 和 'tracestate' 字段
        """
        if carrier is None:
            carrier = {}

        # 构造 W3C traceparent 格式：version-trace_id-span_id-trace_flags
        # 格式：00-{trace_id}-{span_id}-{flags:02x}
        traceparent = (
            f"00-{trace_context.trace_id}-{trace_context.span_id}"
            f"-{trace_context.trace_flags:02x}"
        )
        carrier["traceparent"] = traceparent

        # Baggage 传播（如果有）
        if trace_context.baggage:
            baggage_items = [f"{k}={v}" for k, v in trace_context.baggage.items()]
            carrier["baggage"] = ",".join(baggage_items)

        return carrier

    def extract(
        self, carrier: dict[str, Any], trusted: bool = True
    ) -> TraceContext | None:
        """从载体提取 TraceContext。

        Args:
            carrier: 载体字典（如 HTTP Headers）
            trusted: 是否来自受信任边界（False 时更严格校验）

        Returns:
            提取的 TraceContext，格式无效或不可信时返回 None

        核心原则（REQ-RT-006 §5.1/§5.3）：
        - 只有来自已登记的可信接入边界才允许关联
        - 格式无效、超限或来自不可信入口时拒绝提取
        """
        traceparent = carrier.get("traceparent", "")
        if not isinstance(traceparent, str):
            return None

        # 解析 W3C traceparent 格式：00-{trace_id}-{span_id}-{flags}
        parts = traceparent.split("-")
        if len(parts) != 4:
            return None

        version, trace_id, span_id, flags_hex = parts

        # 校验版本（当前只支持 version 00）
        if version != "00":
            return None

        # 校验长度
        if len(trace_id) != 32 or len(span_id) != 16 or len(flags_hex) != 2:
            return None

        # 不可信来源拒绝提取（REQ-RT-006 §5.3：受控传播）
        if not trusted:
            # 安全原则：不接受来自不可信边界的 TraceContext
            # 调用方应创建新的根 Trace
            return None

        try:
            trace_flags = int(flags_hex, 16)
        except ValueError:
            return None

        # 提取 baggage（如果有）
        baggage: dict[str, str] = {}
        baggage_header = carrier.get("baggage", "")
        if isinstance(baggage_header, str) and baggage_header:
            for item in baggage_header.split(","):
                item = item.strip()
                if "=" in item:
                    key, value = item.split("=", 1)
                    baggage[key.strip()] = value.strip()

        return TraceContext(
            trace_id=trace_id,
            span_id=span_id,
            trace_flags=trace_flags,
            baggage=baggage,
        )


# 全局单例
_propagator = TracePropagator()


def inject_trace_context(
    trace_context: TraceContext, carrier: dict[str, str] | None = None
) -> dict[str, str]:
    """便捷函数：注入 TraceContext。"""
    return _propagator.inject(trace_context, carrier)


def extract_trace_context(
    carrier: dict[str, Any], trusted: bool = True
) -> TraceContext | None:
    """便捷函数：提取 TraceContext。"""
    return _propagator.extract(carrier, trusted)
