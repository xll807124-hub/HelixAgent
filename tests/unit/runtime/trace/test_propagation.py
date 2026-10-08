"""测试 W3C Trace Context 传播。"""
from src.runtime.trace.context import TraceContext
from src.runtime.trace.propagation import (
    extract_trace_context,
    inject_trace_context,
)


class TestTracePropagator:
    """测试 TracePropagator（REQ-RT-006 §5）。"""

    def test_inject_trace_context(self) -> None:
        """测试注入 TraceContext 到 HTTP Headers。"""
        ctx = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            trace_flags=1,
        )
        carrier = inject_trace_context(ctx)

        assert "traceparent" in carrier
        assert carrier["traceparent"] == "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"

    def test_inject_with_baggage(self) -> None:
        """测试注入包含 baggage 的 TraceContext。"""
        ctx = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            trace_flags=1,
            baggage={"user_id": "123", "session": "abc"},
        )
        carrier = inject_trace_context(ctx)

        assert "traceparent" in carrier
        assert "baggage" in carrier
        assert "user_id=123" in carrier["baggage"]
        assert "session=abc" in carrier["baggage"]

    def test_extract_valid_trace_context(self) -> None:
        """测试从 HTTP Headers 提取有效的 TraceContext。"""
        carrier = {
            "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
        }
        ctx = extract_trace_context(carrier, trusted=True)

        assert ctx is not None
        assert ctx.trace_id == "0123456789abcdef0123456789abcdef"
        assert ctx.span_id == "0123456789abcdef"
        assert ctx.trace_flags == 1
        assert ctx.is_sampled is True

    def test_extract_with_baggage(self) -> None:
        """测试提取包含 baggage 的 TraceContext。"""
        carrier = {
            "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
            "baggage": "user_id=123,session=abc",
        }
        ctx = extract_trace_context(carrier, trusted=True)

        assert ctx is not None
        assert ctx.baggage == {"user_id": "123", "session": "abc"}

    def test_extract_invalid_format_returns_none(self) -> None:
        """测试提取无效格式时返回 None。"""
        invalid_carriers = [
            {},  # 缺少 traceparent
            {"traceparent": "invalid"},  # 格式错误
            {"traceparent": "00-short-span-01"},  # trace_id 太短
            {"traceparent": "00-0123456789abcdef0123456789abcdef-short-01"},  # span_id 太短
            {"traceparent": "99-0123456789abcdef0123456789abcdef-0123456789abcdef-01"},  # 版本错误
        ]
        for carrier in invalid_carriers:
            ctx = extract_trace_context(carrier, trusted=True)
            assert ctx is None

    def test_extract_not_sampled(self) -> None:
        """测试提取未采样的 TraceContext。"""
        carrier = {
            "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-00"
        }
        ctx = extract_trace_context(carrier, trusted=True)

        assert ctx is not None
        assert ctx.trace_flags == 0
        assert ctx.is_sampled is False

    def test_inject_extract_roundtrip(self) -> None:
        """测试注入-提取往返。"""
        original = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            trace_flags=1,
            baggage={"key": "value"},
        )

        # 注入
        carrier = inject_trace_context(original)

        # 提取
        extracted = extract_trace_context(carrier, trusted=True)

        assert extracted is not None
        assert extracted.trace_id == original.trace_id
        assert extracted.span_id == original.span_id
        assert extracted.trace_flags == original.trace_flags
        assert extracted.baggage == original.baggage

    def test_extract_untrusted_source(self) -> None:
        """测试从不可信来源提取（REQ-RT-006 §5.1/§5.3）。
        
        核心原则：来自不可信入口的 TraceContext 应被拒绝，
        调用方应创建新的根 Trace。
        """
        carrier = {
            "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
        }

        # 不可信来源拒绝提取（REQ-RT-006 §5.1）
        ctx = extract_trace_context(carrier, trusted=False)
        assert ctx is None  # 应返回 None，调用方创建新根 Trace

    def test_propagator_singleton(self) -> None:
        """测试 TracePropagator 全局单例行为。"""
        ctx = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
        )

        carrier1 = inject_trace_context(ctx)
        carrier2 = inject_trace_context(ctx)

        # 两次调用应该产生相同结果
        assert carrier1 == carrier2
