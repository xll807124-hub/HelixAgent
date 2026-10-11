"""
模型客户端抽象与 Mock 实现

职责：
- 定义 Coder Worker 与 LLM 之间的最小契约（ModelClient Protocol）
- 提供 MockModelClient：按剧本返回响应，可注入异常，用于确定性测试

说明：真实 LLM 适配器（Model Gateway）不在本阶段接入，只保留接口。
对齐：REQ-SEC-006（模型输出不可信，必须结构化校验后才能转成 Action）
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelClientError(Exception):
    """模型调用失败（网络、限流、服务端错误等）。"""


class ModelOutputError(ModelClientError):
    """模型输出无法解析为合法的结构化响应。"""


class ModelMessage(BaseModel):
    """发送给模型的一条消息。"""

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class ToolSpec(BaseModel):
    """暴露给模型的工具描述（名称与真实参数 Schema）。"""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """模型提议的一次工具调用（只是提议，不会被直接执行）。"""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelUsage(BaseModel):
    """一次模型调用的资源消耗。"""

    model_config = ConfigDict(frozen=True)

    tokens: int = Field(default=0, ge=0)
    cost_cents: int = Field(default=0, ge=0)


class ModelResponse(BaseModel):
    """模型的结构化响应：要么提议一次工具调用，要么声明完成。"""

    model_config = ConfigDict(frozen=True)

    thought: str = ""
    tool_call: ToolCall | None = None
    final_summary: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)

    @model_validator(mode="after")
    def _exactly_one_outcome(self) -> ModelResponse:
        has_call = self.tool_call is not None
        has_final = self.final_summary is not None
        if has_call == has_final:
            raise ValueError("ModelResponse 必须且只能包含 tool_call 或 final_summary 之一")
        return self

    @property
    def is_final(self) -> bool:
        return self.final_summary is not None


@runtime_checkable
class ModelClient(Protocol):
    """模型客户端协议。实现方必须返回已解析的 ModelResponse。"""

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec],
    ) -> ModelResponse:
        """调用模型。

        Raises:
            ModelClientError: 调用失败
            ModelOutputError: 输出无法解析为合法响应
        """
        ...


class MockModelClient:
    """按剧本返回响应的 Mock 客户端。

    剧本项可以是 ModelResponse（正常返回）或 Exception（抛出，用于注入故障）。
    剧本耗尽后再次调用会抛 ModelClientError，避免测试悄悄死循环。
    """

    def __init__(self, script: Sequence[ModelResponse | Exception]) -> None:
        self._script = list(script)
        self._cursor = 0
        self.calls: list[tuple[list[ModelMessage], list[ToolSpec]]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec],
    ) -> ModelResponse:
        self.calls.append((list(messages), list(tools)))
        if self._cursor >= len(self._script):
            raise ModelClientError("MockModelClient 剧本已耗尽")
        item = self._script[self._cursor]
        self._cursor += 1
        if isinstance(item, Exception):
            raise item
        return item
