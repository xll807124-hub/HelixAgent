"""Bounded SSE decoding across byte and UTF-8 boundaries."""

from .protocol import parse_json
from .types import ErrorCode, GatewayError


class SSEDecoder:
    def __init__(self, max_event_bytes: int, max_response_bytes: int, max_events: int):
        self.max_event_bytes = max_event_bytes
        self.max_response_bytes = max_response_bytes
        self.max_events = max_events
        self.buffer = b""
        self.lines: list[bytes] = []
        self.event_bytes = 0
        self.total = 0
        self.count = 0

    def feed(self, chunk: bytes) -> list[dict]:
        self.total += len(chunk)
        if self.total > self.max_response_bytes:
            raise GatewayError(ErrorCode.OUTPUT_INVALID)
        self.buffer += chunk
        events = []
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            self.event_bytes += len(line) + 1
            if self.event_bytes > self.max_event_bytes:
                raise GatewayError(ErrorCode.OUTPUT_INVALID)
            line = line.removesuffix(b"\r")
            if not line:
                if self.lines:
                    self.count += 1
                    if self.count > self.max_events:
                        raise GatewayError(ErrorCode.OUTPUT_INVALID)
                    events.append(parse_json(b"\n".join(self.lines), self.max_event_bytes))
                self.lines = []
                self.event_bytes = 0
            elif line.startswith(b"data:"):
                value = line[5:]
                self.lines.append(value[1:] if value.startswith(b" ") else value)
            elif line.startswith((b":", b"event:", b"id:", b"retry:")):
                continue
            else:
                raise GatewayError(ErrorCode.OUTPUT_INVALID)
        if len(self.buffer) + self.event_bytes > self.max_event_bytes:
            raise GatewayError(ErrorCode.OUTPUT_INVALID)
        return events

    def finish(self) -> None:
        if self.buffer or self.lines:
            raise GatewayError(ErrorCode.STREAM_INTERRUPTED)
