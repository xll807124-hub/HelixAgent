"""Real loopback TCP/HTTP and real SQLite; no OpenAI service is contacted."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from src.workers.common.model_gateway.budget import BudgetLedger
from src.workers.common.model_gateway.gateway import ModelGateway
from src.workers.common.model_gateway.transport import OpenAITransport
from src.workers.common.model_gateway.types import CancellationToken, GatewayError
from tests.unit.workers.model_gateway.conftest import completed, encode_events

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class LoopbackTransport(httpx.AsyncBaseTransport):
    """Test-only routing; production still constructs a fixed TLS OpenAI request."""

    def __init__(self, port):
        self.port = port
        self.inner = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        local = httpx.Request(
            request.method,
            f"http://127.0.0.1:{self.port}/v1/responses",
            headers=request.headers,
            content=request.content,
            extensions=request.extensions,
        )
        return await self.inner.handle_async_request(local)

    async def aclose(self):
        await self.inner.aclose()


@asynccontextmanager
async def server(mode):
    received, disconnected = asyncio.Event(), asyncio.Event()
    observations = []
    jobs = set()

    async def handle(reader, writer):
        jobs.add(asyncio.current_task())
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1])
                for line in header.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            observations.append(await reader.readexactly(length))
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
            )
            await writer.drain()
            received.set()
            if mode == "valid":
                body = encode_events(completed())
                for offset in range(0, len(body), 7):
                    chunk = body[offset : offset + 7]
                    writer.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    await writer.drain()
                    await asyncio.sleep(0)
                writer.write(b"0\r\n\r\n")
                await writer.drain()
            elif mode == "disconnect":
                writer.write(b'20\r\ndata: {"type":"response')  # Deliberate mid-chunk EOF.
                await writer.drain()
            else:
                # Reader EOF proves cancellation/timeout closed the actual client connection.
                assert await reader.read() == b""
        finally:
            writer.close()
            await writer.wait_closed()
            disconnected.set()
            jobs.discard(asyncio.current_task())

    listener = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield listener.sockets[0].getsockname()[1], received, disconnected, observations
    finally:
        listener.close()
        await listener.wait_closed()
        if jobs:
            await asyncio.wait_for(asyncio.gather(*tuple(jobs)), 2)


def gateway_for(config, request_model, port):
    ledger = BudgetLedger(config.budget_db)
    ledger.create_account(
        *request_model.context.account, request_model.context.scope_digest, 100000, 1000000
    )
    return ModelGateway(
        config, ledger, transport=OpenAITransport(config, http_transport=LoopbackTransport(port))
    )


async def test_real_chunked_http_success(config, request_model):
    async with server("valid") as (port, _, closed, observations):
        gateway = gateway_for(config, request_model, port)
        result = await gateway.complete(request_model)
        await asyncio.wait_for(closed.wait(), 2)
        assert result.final_summary == "合成回答" and len(observations) == 1
        assert gateway.ledger.snapshot("org", "task")["settled_cost"] == 20


async def test_actual_disconnect_retains_unknown_cost(config, request_model):
    async with server("disconnect") as (port, _, closed, _):
        gateway = gateway_for(config, request_model, port)
        with pytest.raises(GatewayError, match="TRANSIENT_NETWORK"):
            await gateway.complete(request_model)
        await asyncio.wait_for(closed.wait(), 2)
        assert gateway.ledger.snapshot("org", "task")["reserved_cost"] == 1200


@pytest.mark.parametrize("cause", ["cancel", "timeout"])
async def test_actual_client_socket_closes(cause, config, request_model):
    if cause == "timeout":
        config = config.model_copy(update={"idle_timeout": 0.05})
    async with server("stall") as (port, received, closed, _):
        gateway = gateway_for(config, request_model, port)
        token = CancellationToken()
        job = asyncio.create_task(gateway.complete(request_model, token))
        await asyncio.wait_for(received.wait(), 2)
        if cause == "cancel":
            token.cancel()
        with pytest.raises(GatewayError, match="CANCELLED" if cause == "cancel" else "TIMEOUT"):
            await asyncio.wait_for(job, 2)
        await asyncio.wait_for(closed.wait(), 2)
        assert gateway.ledger.snapshot("org", "task")["locked"] == 1
