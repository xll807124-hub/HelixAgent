"""One network attempt, a fixed TLS endpoint, bounded reads, and explicit close."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import AsyncGenerator, Callable
from typing import Any

import httpx

from .config import RESPONSES_URL, GatewayConfig
from .sse import SSEDecoder
from .types import ErrorCode, GatewayError


def status_error(status: int, retry: str | None) -> GatewayError:
    code = {
        401: ErrorCode.AUTHENTICATION,
        403: ErrorCode.PERMISSION,
        429: ErrorCode.RATE_LIMIT,
    }.get(status)
    code = code or (ErrorCode.PROVIDER_UNAVAILABLE if status >= 500 else ErrorCode.INVALID_REQUEST)
    delay = None
    if status == 429 and retry:
        try:
            number = float(retry)
            if math.isfinite(number) and 0 <= number <= 86400:
                delay = number
        except ValueError:
            pass
    return GatewayError(code, delay)


class OpenAITransport:
    def __init__(
        self,
        config: GatewayConfig,
        *,
        http_transport: httpx.AsyncBaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.config = config
        self._http_transport = http_transport  # External IO injection for contract tests only.
        self._monotonic = monotonic

    async def events(self, payload: bytes) -> AsyncGenerator[dict[str, Any], None]:
        config = self.config
        decoder = SSEDecoder(config.max_event_bytes, config.max_response_bytes, config.max_events)
        first_deadline = self._monotonic() + config.first_event_timeout
        seen = False
        timeout = httpx.Timeout(config.idle_timeout, connect=config.connect_timeout)
        try:
            async with (
                asyncio.timeout(config.first_event_timeout) as first_timer,
                httpx.AsyncClient(
                    transport=self._http_transport,
                    timeout=timeout,
                    trust_env=False,
                    follow_redirects=False,
                ) as client,
            ):
                async with client.stream(
                    "POST",
                    RESPONSES_URL,
                    content=payload,
                    headers={
                        "Authorization": "Bearer " + config.api_key.get_secret_value(),
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    if response.status_code != 200:
                        raise status_error(
                            response.status_code, response.headers.get("Retry-After")
                        )
                    content_type = response.headers.get("content-type", "").split(";")[0]
                    if (
                        content_type.strip().lower() != "text/event-stream"
                        or response.headers.get("content-encoding", "identity") != "identity"
                    ):
                        raise GatewayError(ErrorCode.OUTPUT_INVALID)
                    iterator = response.aiter_bytes().__aiter__()
                    while True:
                        delay = config.idle_timeout
                        if not seen:
                            delay = min(delay, first_deadline - self._monotonic())
                        if delay <= 0:
                            raise GatewayError(ErrorCode.TIMEOUT)
                        try:
                            chunk = await asyncio.wait_for(anext(iterator), timeout=delay)
                        except StopAsyncIteration:
                            decoder.finish()
                            return
                        for event in decoder.feed(chunk):
                            if not seen:
                                first_timer.reschedule(None)
                            seen = True
                            yield event
        except GatewayError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise GatewayError(ErrorCode.TIMEOUT) from None
        except httpx.HTTPError:
            raise GatewayError(ErrorCode.TRANSIENT_NETWORK) from None
