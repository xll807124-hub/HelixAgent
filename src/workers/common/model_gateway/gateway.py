"""One complete model decision, with budgets committed before publishing success."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from datetime import UTC, datetime
from typing import Any

from .budget import BudgetLedger
from .config import GatewayConfig
from .protocol import build_payload, parse_result
from .transport import OpenAITransport
from .types import (
    CancellationToken,
    ErrorCode,
    GatewayError,
    ModelEvent,
    ModelRequest,
    ModelResult,
)

_METADATA = {
    "response.created",
    "response.in_progress",
    "response.output_item.added",
    "response.output_item.done",
    "response.content_part.added",
    "response.content_part.done",
    "response.output_text.done",
    "response.function_call_arguments.done",
}


async def _db(operation: Callable[..., Any], *args: Any) -> Any:
    """Wait for a short SQLite operation to finish before cancellation cleanup races it."""
    job = asyncio.create_task(asyncio.to_thread(operation, *args))
    try:
        return await asyncio.shield(job)
    except asyncio.CancelledError:
        await job
        raise


class ModelGateway:
    def __init__(
        self,
        config: GatewayConfig,
        ledger: BudgetLedger,
        *,
        transport: OpenAITransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if ledger.path.resolve() != config.budget_db.resolve():
            raise GatewayError(ErrorCode.INVALID_REQUEST)
        self.config = config
        self.ledger = ledger
        self.transport = transport or OpenAITransport(config)
        self.clock = clock

    async def complete(
        self, request: ModelRequest, cancel: CancellationToken | None = None
    ) -> ModelResult:
        async with aclosing(self.stream(request, cancel)) as events:
            async for event in events:
                if event.error is not None:
                    raise GatewayError(event.error, event.retry_after)
                if event.result is not None:
                    return event.result
        raise GatewayError(ErrorCode.STREAM_INTERRUPTED)

    async def stream(
        self, request: ModelRequest, cancel: CancellationToken | None = None
    ) -> AsyncGenerator[ModelEvent, None]:
        # Pydantic's frozen containers are shallow: isolate nested messages and schemas.
        try:
            # Serializer warnings can echo invalid input values; reject them without logging.
            snapshot = ModelRequest.model_validate(request.model_dump(warnings=False)).model_copy(
                deep=True
            )
        except Exception:
            raise GatewayError(ErrorCode.INVALID_REQUEST) from None
        token = cancel or CancellationToken()
        queue: asyncio.Queue[ModelEvent] = asyncio.Queue(self.config.queue_size)
        producer = asyncio.create_task(self._produce(snapshot, token, queue))

        async def watch_cancel() -> None:
            await token.wait()
            producer.cancel()

        watcher = asyncio.create_task(watch_cancel())
        try:
            while True:
                event = await queue.get()
                yield event
                if event.type in ("completed", "failed", "cancelled", "timed_out"):
                    break
        finally:
            if not producer.done():
                producer.cancel()
            watcher.cancel()
            await asyncio.gather(producer, watcher, return_exceptions=True)

    async def _produce(
        self, request: ModelRequest, token: CancellationToken, queue: asyncio.Queue[ModelEvent]
    ) -> None:
        context = request.context
        key = (*context.account, context.request_id, context.attempt)
        reserved = False
        sequence = 0
        failure: GatewayError | None = None

        def emit(kind: Any, **values: Any) -> None:
            nonlocal sequence
            sequence += 1
            event = ModelEvent(
                request_id=context.request_id,
                attempt=context.attempt,
                sequence=sequence,
                type=kind,
                **values,
            )
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                raise GatewayError(ErrorCode.OUTPUT_INVALID) from None

        try:
            token.check()
            now = self.clock()
            duration = min(self.config.total_timeout, (context.deadline_at - now).total_seconds())
            if duration <= 0:
                raise GatewayError(ErrorCode.TIMEOUT)
            async with asyncio.timeout(duration):
                profile = self.config.profile
                profile.validate_at(now)
                payload = build_payload(request, self.config)
                tokens = profile.context_window + request.max_output_tokens
                cost = profile.cost(profile.context_window, request.max_output_tokens)
                await _db(
                    self.ledger.reserve,
                    *context.account,
                    context.scope_digest,
                    context.request_id,
                    context.attempt,
                    request.digest(),
                    tokens,
                    cost,
                    profile.pricing_version,
                )
                reserved = True
                token.check()
                emit("started")
                await _db(self.ledger.dispatch, *key)
                token.check()
                previous_sequence = -1
                async with aclosing(self.transport.events(payload)) as events:
                    async for event in events:
                        token.check()
                        current = event.get("sequence_number")
                        if type(current) is not int or current <= previous_sequence:
                            raise GatewayError(ErrorCode.OUTPUT_INVALID)
                        previous_sequence = current
                        kind = event.get("type")
                        if kind in _METADATA:
                            continue
                        if kind in (
                            "response.output_text.delta",
                            "response.function_call_arguments.delta",
                        ):
                            delta = event.get("delta")
                            if not isinstance(delta, str):
                                raise GatewayError(ErrorCode.OUTPUT_INVALID)
                            emit(
                                "text_delta"
                                if kind == "response.output_text.delta"
                                else "tool_arguments_delta",
                                delta=delta,
                            )
                            # Let an active consumer drain a burst; a stalled one stays bounded.
                            await asyncio.sleep(0)
                        elif kind == "response.completed":
                            profile.validate_at(self.clock())
                            result = parse_result(event.get("response", {}), request, profile)
                            token.check()
                            out_of_bounds = (
                                result.usage.input_tokens > profile.context_window
                                or result.usage.output_tokens > request.max_output_tokens
                            )
                            await _db(
                                self.ledger.settle,
                                *key,
                                result.usage.total_tokens,
                                result.usage.cost_microusd,
                                result.provider_request_id,
                                out_of_bounds,
                            )
                            token.check()
                            emit("completed", result=result)
                            return
                        elif kind in ("response.refusal.delta", "response.refusal.done"):
                            raise GatewayError(ErrorCode.REFUSAL)
                        elif kind in ("error", "response.failed"):
                            raise GatewayError(ErrorCode.PROVIDER_UNAVAILABLE)
                        elif kind == "response.incomplete":
                            raise GatewayError(ErrorCode.OUTPUT_INVALID)
                        else:
                            raise GatewayError(ErrorCode.UNSUPPORTED_CAPABILITY)
                raise GatewayError(ErrorCode.STREAM_INTERRUPTED)
        except GatewayError as error:
            failure = error
        except TimeoutError:
            failure = GatewayError(ErrorCode.TIMEOUT)
        except asyncio.CancelledError:
            failure = GatewayError(ErrorCode.CANCELLED)
        except Exception:
            failure = GatewayError(ErrorCode.PROVIDER_UNAVAILABLE)
        finally:
            if failure is not None:
                if reserved:
                    try:
                        await _db(self.ledger.abort, *key)
                    except GatewayError:
                        # Failed cleanup retains the hold; never release optimistically.
                        failure = GatewayError(ErrorCode.STORAGE_UNAVAILABLE)
                while not queue.empty():
                    queue.get_nowait()
                terminal = {ErrorCode.CANCELLED: "cancelled", ErrorCode.TIMEOUT: "timed_out"}
                emit(
                    terminal.get(failure.code, "failed"),
                    error=failure.code,
                    retry_after=failure.retry_after,
                )
