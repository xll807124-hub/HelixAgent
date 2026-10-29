"""Compatibility entry point. Existing Coder and Mock signatures remain intact."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from pydantic import ValidationError

from src.workers.coder.model_client import (
    ModelClientError,
    ModelMessage,
    ModelOutputError,
    ModelResponse,
    ModelUsage,
    ToolCall,
    ToolSpec,
)

from .model_gateway.gateway import ModelGateway, _db
from .model_gateway.types import (
    CancellationToken,
    ErrorCode,
    GatewayError,
    Message,
    ModelRequest,
    RequestContext,
    ToolDefinition,
)


class GatewayModelClient:
    """A trusted context provider must bind identity, deadline, budget and toolset."""

    def __init__(
        self,
        gateway: ModelGateway,
        context_provider: Callable[[], Awaitable[RequestContext]],
        *,
        toolset_version: str,
        cancel: CancellationToken | None = None,
    ):
        self.gateway = gateway
        self.context_provider = context_provider
        self.toolset_version = toolset_version
        self.cancel = cancel

    async def complete(
        self, messages: Sequence[ModelMessage], tools: Sequence[ToolSpec]
    ) -> ModelResponse:
        try:
            context = await self.context_provider()
            request = ModelRequest(
                context=context,
                profile_ref=self.gateway.config.profile.profile_ref,
                toolset_version=self.toolset_version,
                max_output_tokens=self.gateway.config.profile.max_output_tokens,
                messages=tuple(
                    Message(
                        role=m.role,
                        content=m.content,
                        source="trusted_config" if m.role == "system" else "user",
                        trust="trusted" if m.role == "system" else "untrusted",
                    )
                    for m in messages
                ),
                tools=tuple(
                    ToolDefinition(
                        name=t.name,
                        description=t.description,
                        input_schema=t.input_schema,
                        schema_version=self.toolset_version,
                    )
                    for t in tools
                ),
            )
            result = await self.gateway.complete(request, self.cancel)
            cents = await _db(
                self.gateway.ledger.legacy_cents,
                *context.account,
                context.request_id,
                context.attempt,
            )
            call = result.tool_proposal
            return ModelResponse(
                thought="",
                tool_call=ToolCall(name=call.name, arguments=call.arguments) if call else None,
                final_summary=result.final_summary,
                usage=ModelUsage(tokens=result.usage.total_tokens, cost_cents=cents),
            )
        except ValidationError:
            raise ModelClientError(ErrorCode.INVALID_REQUEST.value) from None
        except GatewayError as error:
            error_type = (
                ModelOutputError
                if error.code in (ErrorCode.OUTPUT_INVALID, ErrorCode.REFUSAL)
                else ModelClientError
            )
            raise error_type(error.code.value) from None
