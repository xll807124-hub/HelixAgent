import json

import pytest
from pydantic import ValidationError

from src.workers.common.model_gateway.protocol import build_payload, parse_json, parse_result
from src.workers.common.model_gateway.types import GatewayError, Message

from .conftest import final_response


@pytest.mark.parametrize(
    "raw",
    [
        '{"x":1,"x":2}',
        '{"x":NaN}',
        "[]",
        b"\xff",
        '{"x":' + "[" * 34 + "0" + "]" * 34 + "}",
        "{broken",
        "null",
    ],
)
def test_untrusted_json_is_rejected(raw):
    with pytest.raises(GatewayError, match="OUTPUT_INVALID"):
        parse_json(raw)


def test_json_byte_limit_and_nested_array():
    assert parse_json('{"x":[{"y":1}]}') == {"x": [{"y": 1}]}
    with pytest.raises(GatewayError):
        parse_json('{"x":"中"}', limit=8)
    with pytest.raises(GatewayError):
        parse_json('{"x":1e999}')


def test_structured_payload_and_valid_proposal(config, request_model):
    payload = json.loads(build_payload(request_model, config))
    assert payload["store"] is False and payload["stream"] is True
    assert payload["text"]["format"]["strict"] is True
    assert "synthetic-placeholder" not in str(payload)
    result = parse_result(
        final_response(
            json.dumps(
                {
                    "kind": "tool",
                    "tool_name": "read_file",
                    "arguments_json": '{"path":"a.py"}',
                    "final_summary": None,
                }
            )
        ),
        request_model,
        config.profile,
    )
    assert result.tool_proposal.arguments == {"path": "a.py"}
    assert result.usage.cost_microusd == 20


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "$ref": "https://invalid.example/schema"},
        {"type": "object", "$dynamicRef": "file:///secret"},
        {"type": "object", "$schema": "http://json-schema.org/draft-07/schema#"},
        {"type": "object", "format": "unknown-assertion"},
        {"type": "array"},
        {"type": "object", "required": "bad"},
    ],
)
def test_invalid_schema_fails_before_network(schema, config, request_model):
    tool = request_model.tools[0].model_copy(update={"input_schema": schema})
    with pytest.raises(GatewayError, match="INVALID_REQUEST"):
        build_payload(request_model.model_copy(update={"tools": (tool,)}), config)


def test_local_refs_and_formats_are_enforced(config, request_model):
    schema = {
        "type": "object",
        "$defs": {"identifier": {"type": "string", "format": "uuid"}},
        "properties": {"path": {"$ref": "#/$defs/identifier"}},
        "required": ["path"],
    }
    req = request_model.model_copy(
        update={"tools": (request_model.tools[0].model_copy(update={"input_schema": schema}),)}
    )
    build_payload(req, config)
    text = json.dumps(
        {
            "kind": "tool",
            "tool_name": "read_file",
            "arguments_json": '{"path":"not-a-uuid"}',
            "final_summary": None,
        }
    )
    with pytest.raises(GatewayError):
        parse_result(final_response(text), req, config.profile)


@pytest.mark.parametrize(
    "decision",
    [
        {"kind": "final", "tool_name": None, "arguments_json": None, "final_summary": " "},
        {"kind": "final", "tool_name": "read_file", "arguments_json": None, "final_summary": "x"},
        {"kind": "tool", "tool_name": "read_file", "arguments_json": "{}", "final_summary": None},
        {"kind": "tool", "tool_name": "read_file", "arguments_json": "[]", "final_summary": None},
        {"kind": "tool", "tool_name": "unknown", "arguments_json": "{}", "final_summary": None},
        {"kind": "tool", "tool_name": "read_file", "arguments_json": "{}", "final_summary": "x"},
        {"kind": "tool", "tool_name": "read_file", "arguments_json": None, "final_summary": None},
        {"kind": "final"},
    ],
)
def test_decisions_fail_closed(decision, config, request_model):
    with pytest.raises(GatewayError, match="OUTPUT_INVALID"):
        parse_result(final_response(json.dumps(decision)), request_model, config.profile)


@pytest.mark.parametrize(
    "change",
    [
        {"status": "incomplete"},
        {"model": "unexpected"},
        {"id": "untrusted\nidentifier"},
        {"usage": None},
        {"usage": {"input_tokens": True, "output_tokens": 0, "total_tokens": 1}},
        {"usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 1}},
        {"usage": {"input_tokens": -1, "output_tokens": 1, "total_tokens": 0}},
        {"output": [{"type": "message", "role": "user", "status": "completed"}]},
        {"output": [{"type": "web_search_call"}]},
        {"output": []},
    ],
)
def test_invalid_provider_receipts(change, config, request_model):
    response = final_response() | change
    with pytest.raises(GatewayError):
        parse_result(response, request_model, config.profile)


def test_native_history_and_result(config, request_model):
    req = request_model.model_copy(
        update={
            "mode": "native",
            "messages": (
                Message(
                    role="assistant",
                    content="",
                    call_id="call_1",
                    tool_name="read_file",
                    arguments={"path": "a.py"},
                ),
                Message(role="tool", content="synthetic output", call_id="call_1"),
            ),
        }
    )
    payload = json.loads(build_payload(req, config))
    assert payload["input"][0]["type"] == "function_call"
    assert payload["input"][1]["call_id"] == "call_1"
    assert payload["tools"][0]["strict"] is False
    assert payload["parallel_tool_calls"] is False
    call = {
        "type": "function_call",
        "status": "completed",
        "call_id": "call_2",
        "name": "read_file",
        "arguments": '{"path":"b.py"}',
    }
    result = parse_result(final_response(output=[call]), req, config.profile)
    assert result.tool_proposal.call_id == "call_2"
    assert parse_result(final_response("done"), req, config.profile).final_summary == "done"
    for output in (
        [call, call],
        [call | {"status": "in_progress"}],
        [call | {"call_id": "!"}],
        [call | {"arguments": "[]"}],
    ):
        with pytest.raises(GatewayError):
            parse_result(final_response(output=output), req, config.profile)


@pytest.mark.parametrize(
    "messages",
    [
        (Message(role="tool", content="x", call_id="missing"),),
        (Message(role="assistant", content="", call_id="a", tool_name="read_file", arguments={}),),
        (Message(role="assistant", content="x", call_id="a", tool_name="read_file", arguments={}),),
        (Message(role="user", content="x", arguments={}),),
        (
            Message(role="assistant", content="", call_id="a", tool_name="read_file", arguments={}),
            Message(role="user", content="x"),
        ),
    ],
)
def test_native_invalid_history(messages, config, request_model):
    req = request_model.model_copy(update={"messages": messages, "mode": "native"})
    with pytest.raises(GatewayError):
        build_payload(req, config)


def test_capability_and_body_limits(config, request_model):
    for req in (
        request_model.model_copy(update={"profile_ref": "unknown"}),
        request_model.model_copy(update={"max_output_tokens": 101}),
        request_model.model_copy(update={"tools": request_model.tools * 2}),
        request_model.model_copy(update={"messages": (Message(role="tool", content="x"),)}),
    ):
        with pytest.raises(GatewayError):
            build_payload(req, config)
    for mode, flag in (("native", "native_tools"), ("structured", "structured_outputs")):
        cfg = config.model_copy(update={"profile": config.profile.model_copy(update={flag: False})})
        with pytest.raises(GatewayError):
            build_payload(request_model.model_copy(update={"mode": mode}), cfg)
    with pytest.raises(GatewayError):
        build_payload(request_model, config.model_copy(update={"max_body_bytes": 128}))


def test_refusal_private_reasoning_and_xor(config, request_model):
    response = final_response()
    response["output"].insert(0, {"type": "reasoning", "content": "private-synthetic-thought"})
    result = parse_result(response, request_model, config.profile)
    assert "private-synthetic-thought" not in str(result.model_dump())
    response["output"][-1]["content"] = [{"type": "refusal", "refusal": "raw-sensitive"}]
    with pytest.raises(GatewayError, match="^REFUSAL$"):
        parse_result(response, request_model, config.profile)
    with pytest.raises(ValidationError):
        type(result).model_validate(result.model_dump() | {"final_summary": None})
