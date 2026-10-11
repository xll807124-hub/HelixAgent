"""
公共 span 工厂（src/observability/spans.py）。

集中管理：span name 规范、attribute 命名、event 命名。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from src.observability.context import is_otel_sdk_active
from src.observability.tracer import get_tracer

# 业务级事件名（snake_case 风格，对齐 OTel 语义约定）
EVENT_TOOL_INVOKED = "tool.invoked"
EVENT_TOOL_COMPLETED = "tool.completed"
EVENT_TOOL_FAILED = "tool.failed"
EVENT_KILL_SWITCH_BLOCKED = "kill_switch.blocked"
EVENT_ACTION_STATUS_CHANGED = "action.status_changed"

# 业务级 attribute 键
ATTR_TOOL_NAME = "tool.name"
ATTR_TOOL_RISK_LEVEL = "tool.risk_level"
ATTR_ACTION_ID = "action.id"
ATTR_TASK_ID = "task.id"
ATTR_WORKFLOW_ID = "workflow.id"
ATTR_HTTP_METHOD = "http.method"
ATTR_HTTP_ROUTE = "http.route"
ATTR_HTTP_STATUS_CODE = "http.status_code"
ATTR_ORGANIZATION_ID = "organization.id"
ATTR_PROJECT_ID = "project.id"
ATTR_REPOSITORY_ID = "repository.id"
ATTR_KILL_SWITCH_SCOPE = "kill_switch.scope"
ATTR_KILL_SWITCH_STATE = "kill_switch.state"
ATTR_POLICY_DECISION = "policy.decision"
ATTR_ERROR_TYPE = "error.type"


@contextmanager
def tool_invoke_span(
    *,
    tool_name: str,
    action_id: str,
    task_id: str,
    risk_level: str,
    **extra: Any,
) -> Iterator[Any]:
    """tool.invoke span context manager（被 ActionExecutor 调用）。

    用法：
        with tool_invoke_span(...) as span:
            result = await executor(...)
            if result.success:
                span.set_attribute(ATTR_TOOL_NAME, tool_name)
            else:
                span.set_status(Status(StatusCode.ERROR))
    """
    tracer = get_tracer("ai-agent-platform.executor")
    attrs: dict[str, Any] = {
        ATTR_TOOL_NAME: tool_name,
        ATTR_TOOL_RISK_LEVEL: risk_level,
        ATTR_ACTION_ID: action_id,
        ATTR_TASK_ID: task_id,
    }
    attrs.update(extra)
    span_cm: Any = tracer.start_as_current_span("tool.invoke", attributes=attrs)
    if not is_otel_sdk_active():
        # OTel SDK 未初始化 → tracer 是 noop；context manager 也是 noop
        # 仍走 with 让代码不分支
        with span_cm as span:
            yield span
            return
    with span_cm as span:
        yield span


def set_error_status(span: Any, *, error_type: str, message: str = "") -> None:
    """标记 span 为 ERROR 状态。"""
    if not is_otel_sdk_active():
        return
    span.set_status(Status(StatusCode.ERROR, message))
    span.set_attribute(ATTR_ERROR_TYPE, error_type)


def set_ok_status(span: Any) -> None:
    """标记 span 为 OK 状态。"""
    if not is_otel_sdk_active():
        return
    span.set_status(Status(StatusCode.OK))


__all__ = [
    "ATTR_ACTION_ID",
    "ATTR_ERROR_TYPE",
    "ATTR_HTTP_METHOD",
    "ATTR_HTTP_ROUTE",
    "ATTR_HTTP_STATUS_CODE",
    "ATTR_KILL_SWITCH_SCOPE",
    "ATTR_KILL_SWITCH_STATE",
    "ATTR_ORGANIZATION_ID",
    "ATTR_POLICY_DECISION",
    "ATTR_PROJECT_ID",
    "ATTR_REPOSITORY_ID",
    "ATTR_TASK_ID",
    "ATTR_TOOL_NAME",
    "ATTR_TOOL_RISK_LEVEL",
    "ATTR_WORKFLOW_ID",
    "EVENT_ACTION_STATUS_CHANGED",
    "EVENT_KILL_SWITCH_BLOCKED",
    "EVENT_TOOL_COMPLETED",
    "EVENT_TOOL_FAILED",
    "EVENT_TOOL_INVOKED",
    "set_error_status",
    "set_ok_status",
    "tool_invoke_span",
]


# 静默 unused：trace 在 is_otel_sdk_active 已用；这里仅为 IDE 提示
_ = trace