"""Real sockets verify transport shutdown, restart and failed-start cleanup."""

import asyncio
import socket
from unittest.mock import AsyncMock

import aiohttp
import pytest

from src.security.mcp_connector_governance.protocol.transport import HTTPTransport, SSETransport


def bound_port(transport):
    return transport._runner.addresses[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_class", [HTTPTransport, SSETransport])
async def test_stop_releases_listener_and_restart_succeeds(transport_class):
    transport = transport_class(AsyncMock(return_value='{"result": {}}'), port=0)
    try:
        await transport.start()
        port = bound_port(transport)
        runner = transport._runner
        await transport.start()
        assert transport._runner is runner
        await transport.stop()
        assert transport._runner is None
        assert not transport._running
        await transport.stop()
        transport.port = port
        await transport.start()
        assert bound_port(transport) == port
    finally:
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_class", [HTTPTransport, SSETransport])
async def test_bind_failure_does_not_leave_transport_running(transport_class):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        transport = transport_class(AsyncMock(), port=occupied.getsockname()[1])
        try:
            with pytest.raises(OSError):
                await transport.start()
            assert not transport._running
            assert transport._runner is None
            assert transport._app is None
        finally:
            await transport.stop()


@pytest.mark.asyncio
async def test_sse_shutdown_wakes_open_stream_without_waiting_for_heartbeat():
    transport = SSETransport(AsyncMock(), port=0)
    try:
        await transport.start()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{bound_port(transport)}/mcp/events"
            ) as response:
                assert b"connected" in await response.content.readline()
                await asyncio.wait_for(transport.stop(), timeout=2)
                await asyncio.wait_for(response.read(), timeout=2)
    finally:
        await transport.stop()
