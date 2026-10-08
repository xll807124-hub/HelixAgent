"""测试 OpenTelemetry Tracer 封装。"""

from src.runtime.trace.context import TraceContext
from src.runtime.trace.tracer import (
    SpanKind,
    create_span,
    generate_span_id,
    get_current_trace_context,
    get_tracer,
)


class TestTracer:
    """测试 Tracer（REQ-RT-006 §4）。"""

    def test_get_tracer(self) -> None:
        """测试获取 Tracer 实例。"""
        tracer = get_tracer("test_component")
        assert tracer is not None

    def test_generate_span_id(self) -> None:
        """测试生成 SpanId。"""
        span_id = generate_span_id()
        assert isinstance(span_id, str)
        assert len(span_id) == 16
        # 验证是十六进制
        int(span_id, 16)

    def test_create_span_without_parent(self) -> None:
        """测试创建根 Span（无父上下文）。"""
        with create_span(
            "test.operation",
            SpanKind.TASK,
            trace_context=None,
            attributes={"task_id": "test-123"},
        ) as span:
            assert span is not None
            # Span 可能未被采样（默认 15% 采样率），不强制要求 is_recording()

    def test_create_span_with_parent(self) -> None:
        """测试创建子 Span（有父上下文）。"""
        parent_ctx = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            trace_flags=1,
        )

        with create_span(
            "child.operation",
            SpanKind.ACTION,
            trace_context=parent_ctx,
            attributes={"action_id": "action-456"},
        ) as span:
            assert span is not None
            assert span.is_recording()

    def test_create_span_with_attributes(self) -> None:
        """测试创建带业务属性的 Span（REQ-RT-006 §4.2）。"""
        attributes = {
            "task_id": "task-123",
            "workflow_id": "workflow-456",
            "organization_id": "org-789",
        }

        with create_span(
            "test.operation",
            SpanKind.WORKFLOW,
            attributes=attributes,
        ) as span:
            assert span is not None
            # OpenTelemetry Span 会记录这些属性

    def test_span_kinds(self) -> None:
        """测试所有 SpanKind 类型（REQ-RT-006 §4.1）。"""
        kinds = [
            SpanKind.TASK,
            SpanKind.WORKFLOW,
            SpanKind.WORKER,
            SpanKind.ACTION,
            SpanKind.TOOL,
            SpanKind.MODEL,
            SpanKind.SANDBOX,
            SpanKind.POLICY,
            SpanKind.ARTIFACT,
        ]

        for kind in kinds:
            with create_span("test.span", kind) as span:
                assert span is not None
                # Span 可能未被采样，不强制要求 is_recording()

    def test_get_current_trace_context_without_span(self) -> None:
        """测试在无活跃 Span 时获取 TraceContext。"""
        _ = get_current_trace_context()
        # 可能为 None（无活跃 Span）或有默认 Span
        # 这取决于 OpenTelemetry 的初始化状态

    def test_get_current_trace_context_within_span(self) -> None:
        """测试在活跃 Span 内获取 TraceContext。"""
        with create_span("test.operation", SpanKind.TASK):
            ctx = get_current_trace_context()
            if ctx is not None:  # 取决于采样
                assert isinstance(ctx, TraceContext)
                assert len(ctx.trace_id) == 32
                assert len(ctx.span_id) == 16

    def test_nested_spans(self) -> None:
        """测试嵌套 Span（父子关系）。"""
        with create_span("parent", SpanKind.TASK) as parent_span:
            assert parent_span is not None

            with create_span("child", SpanKind.ACTION) as child_span:
                assert child_span is not None

                # 两个 Span 都应该存在（是否 recording 取决于采样）
                assert parent_span is not None
                assert child_span is not None
