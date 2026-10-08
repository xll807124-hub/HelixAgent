"""测试 TraceContext 实体。"""
import pytest

from src.runtime.trace.context import TraceContext


class TestTraceContext:
    """测试 TraceContext（REQ-RT-006 §2）。"""

    def test_create_valid_trace_context(self) -> None:
        """测试创建有效的 TraceContext。"""
        ctx = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            trace_flags=1,
        )
        assert ctx.trace_id == "0123456789abcdef0123456789abcdef"
        assert ctx.span_id == "0123456789abcdef"
        assert ctx.trace_flags == 1
        assert ctx.is_sampled is True
        assert ctx.baggage == {}

    def test_trace_context_is_sampled(self) -> None:
        """测试 is_sampled 属性。"""
        sampled = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            trace_flags=1,
        )
        not_sampled = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            trace_flags=0,
        )
        assert sampled.is_sampled is True
        assert not_sampled.is_sampled is False

    def test_invalid_trace_id_length(self) -> None:
        """测试无效的 trace_id 长度。"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TraceContext(
                trace_id="short",
                span_id="0123456789abcdef",
            )

    def test_invalid_span_id_length(self) -> None:
        """测试无效的 span_id 长度。"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TraceContext(
                trace_id="0123456789abcdef0123456789abcdef",
                span_id="short",
            )

    def test_invalid_trace_id_format(self) -> None:
        """测试无效的 trace_id 格式（非十六进制）。"""
        with pytest.raises(ValueError, match="trace_id 必须是 32 位十六进制字符串"):
            TraceContext(
                trace_id="ghijklmnopqrstuvwxyz123456789012",  # 含非十六进制字符
                span_id="0123456789abcdef",
            )

    def test_baggage_with_valid_keys(self) -> None:
        """测试有效的 baggage 键名。"""
        ctx = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            baggage={"user_id": "123", "session": "abc"},
        )
        assert ctx.baggage == {"user_id": "123", "session": "abc"}

    def test_baggage_rejects_sensitive_keys(self) -> None:
        """测试 baggage 拒绝敏感键名（REQ-RT-006 §7.4）。"""
        forbidden_keys = [
            "api_key",
            "access_token",
            "refresh_token",
            "private_key",
            "password",
            "secret",
            "credential",
        ]
        for key in forbidden_keys:
            with pytest.raises(ValueError, match="baggage 键名.*命中禁止的敏感字段"):
                TraceContext(
                    trace_id="0123456789abcdef0123456789abcdef",
                    span_id="0123456789abcdef",
                    baggage={key: "value"},
                )

    def test_with_new_span(self) -> None:
        """测试 with_new_span 方法。"""
        parent = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            trace_flags=1,
            baggage={"key": "value"},
        )
        child = parent.with_new_span("fedcba9876543210")

        assert child.trace_id == parent.trace_id  # 继承 trace_id
        assert child.span_id == "fedcba9876543210"  # 新 span_id
        assert child.trace_flags == parent.trace_flags  # 继承 trace_flags
        assert child.baggage == parent.baggage  # 继承 baggage
        assert child is not parent  # 不同实例

    def test_trace_context_is_frozen(self) -> None:
        """测试 TraceContext 是不可变的。"""
        from pydantic import ValidationError

        ctx = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
        )
        with pytest.raises(ValidationError):  # pydantic frozen
            ctx.trace_id = "new_value"  # type: ignore
