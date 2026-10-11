"""
OpenTelemetry TracerProvider 单例（src/observability/tracer.py）。

设计原则（OBS-001）：
- 单例 TracerProvider（lifespan 启动期初始化一次）
- 默认 console exporter（MVP 演示用；不依赖外部 collector）
- OTLP exporter 可选（生产部署时启用）
- 关停 SDK 时不抛错（fail-open 观察）
- service.name / service.version 强制设置
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_NAME = "ai-agent-platform"
DEFAULT_SERVICE_VERSION = "0.1.0"

_lock = threading.Lock()
_initialized: bool = False


def _resolve_exporter() -> tuple[SpanExporter | None, str]:
    """根据 OTEL_EXPORTER 环境变量选 exporter；返回 (exporter, name)。"""
    choice = os.environ.get("OTEL_EXPORTER", "console").strip().lower()
    if choice == "none":
        return None, "none"
    if choice == "console":
        return ConsoleSpanExporter(), "console"
    if choice == "otlp":
        # 延迟导入：避免生产部署时强制装 OTLP 包
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            endpoint = os.environ.get(
                "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
            )
            return OTLPSpanExporter(endpoint=endpoint, insecure=True), "otlp"
        except ImportError as exc:
            logger.warning(
                "OTEL_EXPORTER=otlp 但 opentelemetry-exporter-otlp 未安装，回退 console: %s",
                exc,
            )
            return ConsoleSpanExporter(), "console"
    logger.warning("unknown OTEL_EXPORTER=%s，回退 console", choice)
    return ConsoleSpanExporter(), "console"


def init_tracing(
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    sampler: Any = None,
) -> TracerProvider | None:
    """初始化全局 TracerProvider（lifespan 启动期调用一次）。

    返回 TracerProvider；如被 `OTEL_SDK_DISABLED=true` 关闭则返回 None。
    重复调用幂等（仅第一次生效）。
    """
    global _initialized

    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        logger.info("OTel SDK disabled by env (OTEL_SDK_DISABLED)")
        return None

    with _lock:
        if _initialized:
            return trace.get_tracer_provider()  # type: ignore[return-value]

        resource = Resource.create(
            {
                "service.name": str(
                    service_name
                    or os.environ.get("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME)
                ),
                "service.version": str(
                    service_version or DEFAULT_SERVICE_VERSION
                ),
            }
        )
        provider = TracerProvider(resource=resource, sampler=sampler)

        exporter, exporter_name = _resolve_exporter()
        if exporter is not None:
            # SimpleSpanProcessor：立即 flush（debug 友好；不依赖后台线程）
            # 生产应改 BatchSpanProcessor；MVP 用 Simple 减少复杂度
            use_batch = os.environ.get("OTEL_USE_BATCH", "").strip().lower() in {
                "1",
                "true",
                "yes",
            }
            processor: Any = (
                BatchSpanProcessor(exporter) if use_batch else SimpleSpanProcessor(exporter)
            )
            provider.add_span_processor(processor)
            logger.info(
                "OTel SDK initialized: service=%s exporter=%s processor=%s",
                service_name or DEFAULT_SERVICE_NAME,
                exporter_name,
                "batch" if use_batch else "simple",
            )
        else:
            logger.info("OTel SDK initialized: no exporter (none mode)")

        trace.set_tracer_provider(provider)
        _initialized = True
        return provider


def get_tracer(name: str = "ai-agent-platform") -> Any:
    """获取当前 tracer（按 name）；如果 SDK 未初始化则返回 noop tracer。"""
    return trace.get_tracer(name)


def shutdown_tracing() -> None:
    """关闭 TracerProvider（lifespan 关闭期调用）；幂等。"""
    global _initialized
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        try:
            provider.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TracerProvider shutdown failed: %s", exc)
    _initialized = False


__all__ = [
    "DEFAULT_SERVICE_NAME",
    "DEFAULT_SERVICE_VERSION",
    "get_tracer",
    "init_tracing",
    "shutdown_tracing",
]