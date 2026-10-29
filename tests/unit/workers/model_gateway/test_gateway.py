import asyncio
import json
from contextlib import aclosing
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.workers.coder.model_client import (
    ModelClient,
    ModelClientError,
    ModelMessage,
    ModelOutputError,
)
from src.workers.common.model_client import GatewayModelClient
from src.workers.common.model_gateway.gateway import ModelGateway, _db
from src.workers.common.model_gateway.types import CancellationToken, ErrorCode, GatewayError

from .conftest import WireStream, completed, encode_events, final_response

pytestmark = pytest.mark.asyncio


async def test_complete_persists_cost_then_prevents_duplicate(make_gateway, request_model):
    gateway, wire, calls = make_gateway()
    result = await gateway.complete(request_model)
    assert result.final_summary == "合成回答" and result.usage.total_tokens == 15
    assert gateway.ledger.snapshot("org", "task")["settled_cost"] == 20
    assert wire.closed and len(calls) == 1
    assert str(calls[0].url) == "https://api.openai.com/v1/responses"
    assert calls[0].headers["accept-encoding"] == "identity"
    assert json.loads(calls[0].content)["store"] is False
    with pytest.raises(GatewayError, match="BUDGET_PENDING"):
        await gateway.complete(request_model)
    assert len(calls) == 1


async def test_stream_has_one_terminal_and_complete_equivalence(make_gateway, request_model):
    gateway, wire, _ = make_gateway(
        {"type": "response.created", "sequence_number": 0},
        {"type": "response.output_text.delta", "sequence_number": 1, "delta": "展示"},
        {"type": "response.function_call_arguments.delta", "sequence_number": 2, "delta": "{}"},
        completed(sequence=3),
    )
    events = [event async for event in gateway.stream(request_model)]
    assert [e.type for e in events] == [
        "started",
        "text_delta",
        "tool_arguments_delta",
        "completed",
    ]
    assert [e.sequence for e in events] == sorted({e.sequence for e in events})
    assert events[-1].result.usage.total_tokens == 15 and wire.closed


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "AUTHENTICATION"),
        (403, "PERMISSION"),
        (429, "RATE_LIMIT"),
        (500, "PROVIDER_UNAVAILABLE"),
        (302, "INVALID_REQUEST"),
        (400, "INVALID_REQUEST"),
    ],
)
async def test_http_errors_do_not_retry_or_leak(status, code, make_gateway, request_model):
    gateway, wire, calls = make_gateway(
        status=status, headers={"Retry-After": "2.5", "Location": "https://untrusted.example"}
    )
    with pytest.raises(GatewayError, match=f"^{code}$") as failure:
        await gateway.complete(request_model)
    assert failure.value.retry_after == (2.5 if status == 429 else None)
    assert len(calls) == 1 and wire.closed
    account = gateway.ledger.snapshot("org", "task")
    assert account["locked"] == 1 and account["reserved_cost"] == 1200


@pytest.mark.parametrize(
    ("event", "code"),
    [
        ({"type": "response.refusal.delta", "delta": "raw-sensitive"}, "REFUSAL"),
        ({"type": "response.refusal.done"}, "REFUSAL"),
        ({"type": "response.failed", "error": "raw-sensitive"}, "PROVIDER_UNAVAILABLE"),
        ({"type": "error", "error": "raw-sensitive"}, "PROVIDER_UNAVAILABLE"),
        ({"type": "response.incomplete"}, "OUTPUT_INVALID"),
        ({"type": "unexpected"}, "UNSUPPORTED_CAPABILITY"),
        ({"type": "response.output_text.delta", "delta": 123}, "OUTPUT_INVALID"),
        ({"type": "response.created", "sequence_number": -1}, "OUTPUT_INVALID"),
    ],
)
async def test_bad_events_close_and_hold(event, code, make_gateway, request_model):
    event.setdefault("sequence_number", 1)
    gateway, wire, calls = make_gateway(event)
    with pytest.raises(GatewayError, match=f"^{code}$"):
        await gateway.complete(request_model)
    assert wire.closed and len(calls) == 1
    assert gateway.ledger.snapshot("org", "task")["locked"] == 1


async def test_missing_terminal_and_duplicate_sequence(make_gateway, request_model):
    gateway, wire, _ = make_gateway({"type": "response.created", "sequence_number": 1})
    with pytest.raises(GatewayError, match="STREAM_INTERRUPTED"):
        await gateway.complete(request_model)
    assert wire.closed


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "text/html"},
        {"Content-Type": "text/event-stream", "Content-Encoding": "gzip"},
    ],
)
async def test_wrong_media_type_or_compression(headers, make_gateway, request_model):
    gateway, wire, _ = make_gateway(headers=headers)
    with pytest.raises(GatewayError, match="OUTPUT_INVALID"):
        await gateway.complete(request_model)
    assert wire.closed


@pytest.mark.parametrize("error", [httpx.ReadError("raw-secret"), httpx.ConnectError("raw-secret")])
async def test_network_errors_are_sanitized(error, make_gateway, request_model):
    gateway, wire, _ = make_gateway(stream=WireStream(failure=error))
    with pytest.raises(GatewayError, match="^TRANSIENT_NETWORK$"):
        await gateway.complete(request_model)
    assert wire.closed


async def test_cancel_before_send_has_no_cost(make_gateway, request_model):
    gateway, _, calls = make_gateway()
    token = CancellationToken()
    token.cancel()
    with pytest.raises(GatewayError, match="CANCELLED"):
        await asyncio.wait_for(gateway.complete(request_model, token), 2)
    assert not calls and gateway.ledger.snapshot("org", "task")["reserved_cost"] == 0


async def test_token_cancel_during_stream_closes_and_locks(make_gateway, request_model):
    wire = WireStream(stall=True)
    gateway, _, calls = make_gateway(stream=wire)
    token = CancellationToken()
    pending = asyncio.create_task(gateway.complete(request_model, token))
    await asyncio.wait_for(wire.entered.wait(), 2)
    token.cancel()
    with pytest.raises(GatewayError, match="CANCELLED"):
        await asyncio.wait_for(pending, 2)
    assert wire.closed and len(calls) == 1
    assert gateway.ledger.snapshot("org", "task")["locked"] == 1


async def test_caller_task_cancel_propagates_after_cleanup(make_gateway, request_model):
    wire = WireStream(stall=True)
    gateway, _, _ = make_gateway(stream=wire)
    pending = asyncio.create_task(gateway.complete(request_model))
    await asyncio.wait_for(wire.entered.wait(), 2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 2)
    assert wire.closed and gateway.ledger.snapshot("org", "task")["locked"] == 1


async def test_close_iterator_does_not_leave_producer(make_gateway, request_model):
    wire = WireStream(stall=True)
    gateway, _, _ = make_gateway(stream=wire)
    async with aclosing(gateway.stream(request_model)) as stream:
        assert (await anext(stream)).type == "started"
        await asyncio.wait_for(wire.entered.wait(), 2)
    assert wire.closed and gateway.ledger.snapshot("org", "task")["locked"] == 1


@pytest.mark.parametrize("timeout", ["total_timeout", "first_event_timeout", "idle_timeout"])
async def test_timeout_bounds_read(timeout, config, make_gateway, request_model):
    # Total includes real SQLite writes; allow IO setup before exercising a stalled read.
    config = config.model_copy(update={timeout: 0.5 if timeout == "total_timeout" else 0.03})
    wire = WireStream(stall=True)
    gateway, _, _ = make_gateway(stream=wire, cfg=config)
    with pytest.raises(GatewayError, match="TIMEOUT"):
        await asyncio.wait_for(gateway.complete(request_model), 2)
    assert wire.closed and gateway.ledger.snapshot("org", "task")["locked"] == 1


async def test_expired_deadline_and_price_fail_before_send(config, make_gateway, request_model):
    expired = datetime.now(UTC) - timedelta(seconds=1)
    req = request_model.model_copy(
        update={"context": request_model.context.model_copy(update={"deadline_at": expired})}
    )
    gateway, _, calls = make_gateway()
    with pytest.raises(GatewayError, match="TIMEOUT"):
        await gateway.complete(req)
    cfg = config.model_copy(
        update={"profile": config.profile.model_copy(update={"pricing_valid_until": expired})}
    )
    gateway, _, calls = make_gateway(cfg=cfg)
    with pytest.raises(GatewayError, match="INVALID_REQUEST"):
        await gateway.complete(request_model)
    assert not calls


async def test_overrun_records_actual_usage_and_locks(make_gateway, request_model):
    gateway, wire, _ = make_gateway(
        completed(
            final_response(usage={"input_tokens": 1, "output_tokens": 101, "total_tokens": 102})
        )
    )
    with pytest.raises(GatewayError, match="BUDGET_EXCEEDED"):
        await gateway.complete(request_model)
    account = gateway.ledger.snapshot("org", "task")
    assert account["locked"] == 1 and account["settled_tokens"] == 102
    assert account["reserved_cost"] == 0 and wire.closed


async def test_slow_consumer_is_bounded(config, make_gateway, request_model):
    events = [
        {"type": "response.output_text.delta", "sequence_number": i, "delta": "x"}
        for i in range(30)
    ]
    gateway, wire, _ = make_gateway(*events, cfg=config.model_copy(update={"queue_size": 1}))
    async with aclosing(gateway.stream(request_model)) as stream:
        await anext(stream)
        # Wait for the observable close, not a slow artificial consumer timeout.
        async with asyncio.timeout(2):
            while not wire.closed:
                await asyncio.sleep(0.001)
        remaining = [event async for event in stream]
        assert len(remaining) <= 2  # One already queued delta, then cleanup's terminal.
        assert remaining[-1].type == "failed"
        assert remaining[-1].error == ErrorCode.OUTPUT_INVALID
        assert not any(event.result for event in remaining)
    assert gateway.ledger.snapshot("org", "task")["locked"] == 1


async def test_adapter_keeps_old_contract(make_gateway, request_model):
    gateway, _, _ = make_gateway()

    async def context():
        return request_model.context

    adapter = GatewayModelClient(gateway, context, toolset_version="v1")
    assert isinstance(adapter, ModelClient)
    result = await adapter.complete([ModelMessage(role="user", content="synthetic")], [])
    assert result.is_final and result.thought == "" and result.usage.cost_cents == 1


@pytest.mark.parametrize(
    ("event", "kind"),
    [
        ({"type": "response.refusal.done", "sequence_number": 0}, ModelOutputError),
        ({"type": "response.failed", "sequence_number": 0}, ModelClientError),
    ],
)
async def test_adapter_error_mapping(event, kind, make_gateway, request_model):
    gateway, _, _ = make_gateway(event)

    async def context():
        return request_model.context

    with pytest.raises(kind):
        await GatewayModelClient(gateway, context, toolset_version="v1").complete(
            [ModelMessage(role="user", content="synthetic")], []
        )


async def test_database_cancellation_waits_for_commit():
    import threading

    entered, release = threading.Event(), threading.Event()

    def slow_operation():
        entered.set()
        assert release.wait(2)
        return 1

    job = asyncio.create_task(_db(slow_operation))
    await asyncio.to_thread(entered.wait, 2)
    job.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await job


async def test_wrong_db_path_is_rejected(config, make_gateway):
    gateway, _, _ = make_gateway()
    with pytest.raises(GatewayError):
        ModelGateway(
            config.model_copy(update={"budget_db": config.budget_db.with_name("other.db")}),
            gateway.ledger,
        )


async def test_duplicate_stream_sequence_fails(make_gateway, request_model):
    gateway, _, _ = make_gateway(
        {"type": "response.created", "sequence_number": 1}, completed(sequence=1)
    )
    with pytest.raises(GatewayError, match="OUTPUT_INVALID"):
        await gateway.complete(request_model)


async def test_utf8_split_stream(make_gateway, request_model):
    body = encode_events(completed())
    wire = WireStream([body[i : i + 1] for i in range(len(body))])
    gateway, _, _ = make_gateway(stream=wire)
    assert (await gateway.complete(request_model)).final_summary == "合成回答"
    assert wire.closed
