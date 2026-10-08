"""
TraceContext 实体定义。

对应契约：docs/design-specs/REQ-RT-006-Trace-传播和审计关联.md §2（共享契约与术语）
         docs/design-specs/REQ-RT-001-core-runtime-entities.md §3.7（TraceContext）

TraceContext 是 Runtime 核心实体之一，表示一次分布式追踪的上下文标识。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..common.types import is_valid_span_id, is_valid_trace_id


class TraceContext(BaseModel):
    """分布式追踪上下文（REQ-RT-001 §3.7 / REQ-RT-006 §2）。

    遵循 OpenTelemetry 语义：
    - trace_id：32 位十六进制字符串（全局唯一，标识完整追踪链路）
    - span_id：16 位十六进制字符串（当前操作的 Span 标识）
    - trace_flags：8 位标志（bit 0 = sampled）
    - baggage：跨服务传播的键值对（白名单控制，默认为空）

    核心原则（REQ-RT-006 §2）：
    - TraceId 与业务 TaskId 分离（不混用）
    - trace_id/span_id 不能用于推断业务顺序
    - Baggage 采用白名单，禁止凭据/敏感信息
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str = Field(
        description="32 位十六进制 TraceId（OpenTelemetry 标准）",
        min_length=32,
        max_length=32,
    )
    span_id: str = Field(
        description="16 位十六进制 SpanId（当前操作标识）",
        min_length=16,
        max_length=16,
    )
    trace_flags: int = Field(
        default=1,  # 默认采样（bit 0 = 1）
        ge=0,
        le=255,
        description="8 位 trace flags（bit 0 表示是否采样）",
    )
    baggage: dict[str, str] = Field(
        default_factory=dict,
        description="跨服务传播的键值对（白名单控制）",
    )

    @field_validator("trace_id")
    @classmethod
    def _validate_trace_id(cls, v: str) -> str:
        if not is_valid_trace_id(v):
            raise ValueError(f"trace_id 必须是 32 位十六进制字符串，收到: {v!r}")
        return v

    @field_validator("span_id")
    @classmethod
    def _validate_span_id(cls, v: str) -> str:
        if not is_valid_span_id(v):
            raise ValueError(f"span_id 必须是 16 位十六进制字符串，收到: {v!r}")
        return v

    @field_validator("baggage")
    @classmethod
    def _validate_baggage(cls, v: dict[str, str]) -> dict[str, str]:
        """校验 baggage 键名（REQ-RT-006 §7.4：禁止凭据/敏感信息）。"""
        forbidden_keys = {
            "api_key",
            "access_token",
            "refresh_token",
            "private_key",
            "password",
            "secret",
            "credential",
        }
        for key in v.keys():
            key_lower = key.lower()
            if any(forbidden in key_lower for forbidden in forbidden_keys):
                raise ValueError(
                    f"baggage 键名 {key!r} 命中禁止的敏感字段；"
                    "不得通过 baggage 传播凭据（REQ-RT-006 §5.3/§7.4）"
                )
        return v

    @property
    def is_sampled(self) -> bool:
        """是否被采样（trace_flags bit 0）。"""
        return bool(self.trace_flags & 0x01)

    def with_new_span(self, new_span_id: str) -> TraceContext:
        """创建新的 Span，继承当前 TraceId 和 trace_flags。"""
        return TraceContext(
            trace_id=self.trace_id,
            span_id=new_span_id,
            trace_flags=self.trace_flags,
            baggage=self.baggage.copy(),
        )
