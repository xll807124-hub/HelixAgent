import pytest

from src.workers.common.model_gateway.sse import SSEDecoder
from src.workers.common.model_gateway.transport import status_error
from src.workers.common.model_gateway.types import GatewayError


def test_multiline_crlf_comments_and_metadata():
    decoder = SSEDecoder(1000, 10000, 10)
    assert decoder.feed(
        b":comment\r\nevent: response\r\nid: 1\r\nretry: 10\r\n"
        b'data: {"type":\r\ndata:"created"}\r\n\r\n'
    ) == [{"type": "created"}]
    decoder.finish()


@pytest.mark.parametrize("body", [b'data: {"x":1}', b'data: {"x":1}\n'])
def test_truncated_stream(body):
    decoder = SSEDecoder(100, 100, 10)
    decoder.feed(body)
    with pytest.raises(GatewayError, match="STREAM_INTERRUPTED"):
        decoder.finish()


@pytest.mark.parametrize(
    ("limits", "body"),
    [
        ((100, 10, 10), b"a" * 11),
        ((10, 100, 10), b"a" * 11),
        ((10, 100, 10), b"a" * 11 + b"\n"),
        ((100, 100, 1), b"data:{}\n\ndata:{}\n\n"),
        ((100, 100, 10), b"unknown:x\n"),
        ((100, 100, 10), b"data: [DONE]\n\n"),
    ],
)
def test_size_event_count_and_bad_wire(limits, body):
    with pytest.raises(GatewayError, match="OUTPUT_INVALID"):
        SSEDecoder(*limits).feed(body)


@pytest.mark.parametrize("retry", ["NaN", "inf", "-1", "86401", "date", None])
def test_invalid_retry_after_not_exposed(retry):
    assert status_error(429, retry).retry_after is None
