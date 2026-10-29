import asyncio
import sqlite3
import warnings
from contextlib import closing

import httpx
import pytest

from src.workers.common.model_gateway.budget import BudgetLedger
from src.workers.common.model_gateway.gateway import ModelGateway
from src.workers.common.model_gateway.transport import OpenAITransport
from src.workers.common.model_gateway.types import CancellationToken, GatewayError

from .conftest import WireStream, completed, encode_events

pytestmark = pytest.mark.asyncio


async def test_cancel_after_settlement_never_publishes_result(config, request_model):
    token = CancellationToken()
    loop = asyncio.get_running_loop()

    class SignallingLedger(BudgetLedger):
        def settle(self, *args, **kwargs):
            super().settle(*args, **kwargs)
            loop.call_soon_threadsafe(token.cancel)

    ledger = SignallingLedger(config.budget_db)
    ledger.create_account(
        *request_model.context.account, request_model.context.scope_digest, 10000, 10000
    )
    wire = WireStream([encode_events(completed())])
    transport = OpenAITransport(
        config,
        http_transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"Content-Type": "text/event-stream"}, stream=wire
            )
        ),
    )
    gateway = ModelGateway(config, ledger, transport=transport)
    with pytest.raises(GatewayError, match="CANCELLED"):
        await gateway.complete(request_model, token)
    assert wire.closed
    assert ledger.snapshot("org", "task")["settled_cost"] == 20
    assert ledger.snapshot("org", "task")["reserved_cost"] == 0


async def test_abort_storage_failure_retains_durable_hold(config, request_model):
    ledger = BudgetLedger(config.budget_db, lock_timeout=0.01)
    ledger.create_account(
        *request_model.context.account, request_model.context.scope_digest, 10000, 10000
    )
    with closing(sqlite3.connect(config.budget_db)) as lock:
        wire = WireStream(failure=httpx.ReadError("synthetic failure"))

        async def handler(_):
            lock.execute("BEGIN IMMEDIATE")  # Actual external writer contention during cleanup.
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=wire)

        transport = OpenAITransport(config, http_transport=httpx.MockTransport(handler))
        with pytest.raises(GatewayError, match="STORAGE_UNAVAILABLE"):
            await ModelGateway(config, ledger, transport=transport).complete(request_model)
        lock.rollback()
    assert wire.closed
    assert ledger.snapshot("org", "task")["reserved_cost"] == 1200
    with pytest.raises(GatewayError, match="BUDGET_PENDING"):
        ledger.reserve("org", "task", request_model.context.scope_digest, "new", 1, "d", 1, 1, "v")


async def test_keepalive_cannot_reset_first_event_deadline(config, request_model):
    ledger = BudgetLedger(config.budget_db)
    ledger.create_account(
        *request_model.context.account, request_model.context.scope_digest, 10000, 10000
    )
    wire = WireStream([b":keepalive\n\n"] * 10)
    ticks = iter([0, 1, 31])
    transport = OpenAITransport(
        config,
        monotonic=lambda: next(ticks),
        http_transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"Content-Type": "text/event-stream"}, stream=wire
            )
        ),
    )
    with pytest.raises(GatewayError, match="TIMEOUT"):
        await ModelGateway(config, ledger, transport=transport).complete(request_model)
    assert wire.closed


async def test_unexpected_io_error_is_sanitized(make_gateway, request_model):
    gateway, wire, _ = make_gateway(stream=WireStream(failure=RuntimeError("sensitive detail")))
    with pytest.raises(GatewayError, match="^PROVIDER_UNAVAILABLE$"):
        await gateway.complete(request_model)
    assert wire.closed


async def test_mutated_request_validated_before_send(make_gateway, request_model):
    gateway, _, calls = make_gateway()
    req = request_model.model_copy(update={"max_output_tokens": "invalid"})
    with warnings.catch_warnings(record=True) as recorded:
        with pytest.raises(GatewayError, match="INVALID_REQUEST"):
            await gateway.complete(req)
    assert not recorded
    assert not calls


async def test_first_event_timeout_covers_response_headers(config, request_model):
    config = config.model_copy(update={"first_event_timeout": 0.03})
    ledger = BudgetLedger(config.budget_db)
    ledger.create_account(
        *request_model.context.account, request_model.context.scope_digest, 10000, 10000
    )
    closed = asyncio.Event()

    async def handler(_):
        try:
            await asyncio.Event().wait()  # Headers never arrive.
        finally:
            closed.set()

    transport = OpenAITransport(config, http_transport=httpx.MockTransport(handler))
    with pytest.raises(GatewayError, match="TIMEOUT"):
        await asyncio.wait_for(
            ModelGateway(config, ledger, transport=transport).complete(request_model), 2
        )
    assert closed.is_set()


async def test_approved_coder_tools_preserve_compatibility(config, request_model):
    from src.workers.coder.prompts import TOOL_SPECS
    from src.workers.common.model_gateway.protocol import build_payload
    from src.workers.common.model_gateway.types import ToolDefinition

    req = request_model.model_copy(
        update={
            "tools": tuple(
                ToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    schema_version="coder-v1",
                )
                for tool in TOOL_SPECS
            )
        }
    )
    assert build_payload(req, config)
