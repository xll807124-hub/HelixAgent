"""`src.observability.spans` 单元测试。

覆盖：
- `tool_invoke_span` 上下文管理器（OTel 未初始化 → 走 noop 分支）
- `set_error_status` / `set_ok_status` 在 noop span 上不抛错
- ATTR_* / EVENT_* 常量命名规范（snake_case / 业务语义）
- 显式初始化 SDK 后 span 会带 attributes
"""
from __future__ import annotations

from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from src.observability import spans as spans_mod


@pytest.fixture
def in_memory_tracer() -> Any:
    """安装一个 InMemoryExporter 的 TracerProvider，让 span 可被读取。

    关键：使用新 provider **覆盖** 任何残留的 global provider，
    避免与 test_tracer.py 的状态相互污染。
    """
    # 先清掉之前用例可能 set 的 provider（test_tracer 会重置，但顺序不可控）
    try:
        old = trace.get_tracer_provider()
        if isinstance(old, TracerProvider):
            old.shutdown()
    except Exception:  # noqa: BLE001
        pass
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]

    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield provider, exporter
    provider.shutdown()
    # 还原到 default（ProxyTracerProvider），让下一用例能重新安装
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]


def test_tool_invoke_span_noop_when_sdk_disabled() -> None:
    """SDK 未初始化时：context manager 走 noop 分支，不抛错。"""
    with spans_mod.tool_invoke_span(
        tool_name="file-read",
        action_id="a-1",
        task_id="t-1",
        risk_level="LOW",
    ) as span:
        # 仍是 OTel NonRecordingSpan，不抛错
        assert span is not None


def test_tool_invoke_span_creates_span_with_attributes(
    in_memory_tracer: Any,
) -> None:
    """SDK 启用时：span 携带业务 attributes；EVENT_TOOL_INVOKED 写为 event。"""
    provider, exporter = in_memory_tracer
    with spans_mod.tool_invoke_span(
        tool_name="file-read",
        action_id="action-001",
        task_id="task-001",
        risk_level="LOW",
        workflow_id="wf-1",
    ) as span:
        # 写入业务 event
        span.add_event(spans_mod.EVENT_TOOL_INVOKED, attributes={"foo": "bar"})

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "tool.invoke"
    attrs = dict(s.attributes or {})
    assert attrs[spans_mod.ATTR_TOOL_NAME] == "file-read"
    assert attrs[spans_mod.ATTR_TOOL_RISK_LEVEL] == "LOW"
    assert attrs[spans_mod.ATTR_ACTION_ID] == "action-001"
    assert attrs[spans_mod.ATTR_TASK_ID] == "task-001"
    # 注：executor 调用方传 workflow_id=... 被 **extra 收走，OTel 上 key 是 'workflow_id'
    assert attrs["workflow_id"] == "wf-1"
    # event 已落
    event_names = [e.name for e in s.events]
    assert spans_mod.EVENT_TOOL_INVOKED in event_names


def test_tool_invoke_span_extra_attributes_merged(in_memory_tracer: Any) -> None:
    """`extra` 参数合并到 attribute dict。"""
    _provider, exporter = in_memory_tracer
    with spans_mod.tool_invoke_span(
        tool_name="x",
        action_id="a",
        task_id="t",
        risk_level="HIGH",
        custom_field="custom-value",
        numeric=42,
    ):
        pass

    s = exporter.get_finished_spans()[0]
    attrs = dict(s.attributes or {})
    assert attrs["custom_field"] == "custom-value"
    assert attrs["numeric"] == 42


def test_set_ok_status_noop_when_sdk_disabled() -> None:
    """set_ok_status 在 noop span 上不抛错。"""
    with spans_mod.tool_invoke_span(
        tool_name="x", action_id="a", task_id="t", risk_level="LOW"
    ) as span:
        spans_mod.set_ok_status(span)  # 不抛错


def test_set_error_status_noop_when_sdk_disabled() -> None:
    """set_error_status 在 noop span 上不抛错。"""
    with spans_mod.tool_invoke_span(
        tool_name="x", action_id="a", task_id="t", risk_level="LOW"
    ) as span:
        spans_mod.set_error_status(span, error_type="tool_failed", message="boom")


def test_set_error_status_marks_span_error(in_memory_tracer: Any) -> None:
    """SDK 启用时：set_error_status 写入 status=ERROR + error.type attribute。"""
    _provider, exporter = in_memory_tracer
    with spans_mod.tool_invoke_span(
        tool_name="x", action_id="a", task_id="t", risk_level="HIGH"
    ) as span:
        spans_mod.set_error_status(span, error_type="tool_failed", message="boom")

    s = exporter.get_finished_spans()[0]
    # status 是 StatusCode.ERROR
    from opentelemetry.trace import StatusCode

    assert s.status.status_code == StatusCode.ERROR
    attrs = dict(s.attributes or {})
    assert attrs[spans_mod.ATTR_ERROR_TYPE] == "tool_failed"


def test_event_constants_snake_case() -> None:
    """EVENT_* 命名约束：snake_case，event 语义（不与 span name 冲突）。"""
    for ev in (
        spans_mod.EVENT_TOOL_INVOKED,
        spans_mod.EVENT_TOOL_COMPLETED,
        spans_mod.EVENT_TOOL_FAILED,
        spans_mod.EVENT_KILL_SWITCH_BLOCKED,
        spans_mod.EVENT_ACTION_STATUS_CHANGED,
    ):
        assert ev == ev.lower(), f"event {ev} must be lowercase"
        assert "." in ev, f"event {ev} should be namespaced"


def test_attr_constants_snake_case() -> None:
    """ATTR_* 命名约束：snake_case + 业务前缀。"""
    for k in (
        spans_mod.ATTR_TOOL_NAME,
        spans_mod.ATTR_TOOL_RISK_LEVEL,
        spans_mod.ATTR_ACTION_ID,
        spans_mod.ATTR_TASK_ID,
        spans_mod.ATTR_WORKFLOW_ID,
        spans_mod.ATTR_HTTP_METHOD,
        spans_mod.ATTR_HTTP_ROUTE,
        spans_mod.ATTR_HTTP_STATUS_CODE,
        spans_mod.ATTR_ERROR_TYPE,
    ):
        assert k == k.lower(), f"attr {k} must be lowercase"
        assert "." in k, f"attr {k} should be namespaced"
