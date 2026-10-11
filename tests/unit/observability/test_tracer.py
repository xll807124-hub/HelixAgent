"""`src.observability.tracer` 单元测试。

覆盖：
- 默认 Provider 状态（ProxyTracerProvider）下的判定
- `init_tracing` 幂等性
- `OTEL_SDK_DISABLED=true` 路径（返回 None / 不抛错）
- `OTEL_EXPORTER=none` 路径（初始化但无 exporter）
- `shutdown_tracing` 幂等
- `get_tracer` 在 SDK 关闭后仍可调用（fallback 到 default）
"""
from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from src.observability import tracer as tracer_mod


@pytest.fixture(autouse=True)
def _reset_tracer_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个用例前清空模块单例 + 重置 OTel global tracer provider。

    关键：先尝试关闭上一用例可能 set 的真实 TracerProvider，
    避免 OTel 内部的 _TRACER_PROVIDER_SET_ONCE 守卫阻止重新设置。
    """
    try:
        old = trace.get_tracer_provider()
        from opentelemetry.sdk.trace import TracerProvider as _TP

        if isinstance(old, _TP):
            old.shutdown()
    except Exception:  # noqa: BLE001
        pass
    monkeypatch.setattr(tracer_mod, "_initialized", False)
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]


def test_is_otel_sdk_active_default_false() -> None:
    """未初始化 SDK 时，ProxyTracerProvider 仍存在 → 判定基于类名。

    注：Otel 在导入时已注册 ProxyTracerProvider 作为 default；
    通过类名判断 SDK 是否真实初始化（见 src.observability.context.is_otel_sdk_active）。
    """
    from src.observability.context import is_otel_sdk_active

    assert isinstance(trace.get_tracer_provider(), type(trace.get_tracer_provider()))
    # 默认实例是 ProxyTracerProvider → is_otel_sdk_active 返回 False
    assert is_otel_sdk_active() is False


def test_init_tracing_returns_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常路径：init_tracing 返回真实 TracerProvider（类名为 'TracerProvider'）。"""
    monkeypatch.setenv("OTEL_EXPORTER", "none")
    provider = tracer_mod.init_tracing(service_name="test-svc", service_version="9.9.9")

    assert isinstance(provider, TracerProvider)
    # SDK 实际已激活（is_otel_sdk_active 通过类名判定）
    from src.observability.context import is_otel_sdk_active

    assert is_otel_sdk_active() is True
    # resource 上有 service.name / service.version
    resource_attrs = dict(provider.resource.attributes)  # type: ignore[union-attr]
    assert resource_attrs["service.name"] == "test-svc"
    assert resource_attrs["service.version"] == "9.9.9"


def test_init_tracing_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """重复调用：第二次不重置 provider；返回当前 provider。"""
    monkeypatch.setenv("OTEL_EXPORTER", "none")
    p1 = tracer_mod.init_tracing(service_name="svc-1")
    p2 = tracer_mod.init_tracing(service_name="svc-2")
    # 幂等：第二个调用被 short-circuit，service.name 仍是 svc-1
    assert p1 is p2
    assert p2 is trace.get_tracer_provider()


def test_init_tracing_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """OTEL_SDK_DISABLED=true：init_tracing 返回 None，不替换 global provider。"""
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    result = tracer_mod.init_tracing()
    assert result is None


def test_init_tracing_unknown_exporter_falls_back_to_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知 exporter 名称：回退 console（不抛错，fail-open）。"""
    monkeypatch.setenv("OTEL_EXPORTER", "bogus")
    provider = tracer_mod.init_tracing()
    assert isinstance(provider, TracerProvider)
    # console exporter 注册为 processor（OTel 1.27+ 单数命名）
    assert provider._active_span_processor is not None  # type: ignore[attr-defined]


def test_shutdown_tracing_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """shutdown 多次调用不抛错；第二次时 provider 是 noop，直接 return。"""
    monkeypatch.setenv("OTEL_EXPORTER", "none")
    tracer_mod.init_tracing()
    tracer_mod.shutdown_tracing()
    # 第二次调用：provider 已不是 TracerProvider，逻辑走 elif 分支
    tracer_mod.shutdown_tracing()


def test_get_tracer_returns_object() -> None:
    """get_tracer 在 SDK 未初始化时也返回 noop tracer（不抛错）。"""
    tracer = tracer_mod.get_tracer("any-name")
    assert tracer is not None


def test_default_service_constants() -> None:
    """默认 service.name / version 常量。"""
    assert tracer_mod.DEFAULT_SERVICE_NAME == "ai-agent-platform"
    assert tracer_mod.DEFAULT_SERVICE_VERSION == "0.1.0"


def test_init_tracing_reads_service_name_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OTEL_SERVICE_NAME 环境变量被尊重。"""
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    monkeypatch.setenv("OTEL_EXPORTER", "none")
    provider = tracer_mod.init_tracing()
    resource_attrs = dict(provider.resource.attributes)  # type: ignore[union-attr]
    assert resource_attrs["service.name"] == "from-env"
