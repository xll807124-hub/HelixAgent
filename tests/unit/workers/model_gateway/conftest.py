"""Synthetic profiles and wire fixtures: no provider requests or real credentials."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from src.workers.common.model_gateway.budget import BudgetLedger
from src.workers.common.model_gateway.config import GatewayConfig, ModelProfile
from src.workers.common.model_gateway.gateway import ModelGateway
from src.workers.common.model_gateway.transport import OpenAITransport
from src.workers.common.model_gateway.types import (
    Message,
    ModelRequest,
    RequestContext,
    ToolDefinition,
)


@pytest.fixture
def config(tmp_path):
    return GatewayConfig(
        api_key=SecretStr("synthetic-placeholder"),
        budget_db=tmp_path / "budget.db",
        profile=ModelProfile(
            profile_ref="test-profile",
            model_id="test-model",
            model_revision="test-revision",
            context_window=1000,
            max_output_tokens=100,
            input_microusd_per_mtoken=1000000,
            output_microusd_per_mtoken=2000000,
            pricing_version="synthetic-v1",
            pricing_valid_until=datetime.now(UTC) + timedelta(days=1),
            native_tools=True,
        ),
    )


@pytest.fixture
def request_model():
    return ModelRequest(
        context=RequestContext(
            organization_id="org",
            project_id="project",
            repository_id="repo",
            task_id="task",
            workflow_id="workflow",
            worker_id="worker",
            step_id="step",
            trace_id="a" * 32,
            span_id="b" * 16,
            request_id="request",
            deadline_at=datetime.now(UTC) + timedelta(minutes=2),
        ),
        profile_ref="test-profile",
        messages=(Message(role="user", content="Synthetic question"),),
        tools=(
            ToolDefinition(
                name="read_file",
                schema_version="v1",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string", "minLength": 1}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            ),
        ),
        toolset_version="v1",
        max_output_tokens=100,
    )


def final_response(text=None, *, output=None, usage=None):
    if text is None:
        text = json.dumps(
            {
                "kind": "final",
                "tool_name": None,
                "arguments_json": None,
                "final_summary": "合成回答",
            },
            ensure_ascii=False,
        )
    return {
        "id": "resp_synthetic",
        "model": "test-model",
        "status": "completed",
        "usage": usage or {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        "output": output
        if output is not None
        else [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }


def encode_events(*events):
    return b"".join(
        ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode() for event in events
    )


def completed(response=None, sequence=1):
    return {
        "type": "response.completed",
        "sequence_number": sequence,
        "response": response or final_response(),
    }


class WireStream(httpx.AsyncByteStream):
    def __init__(self, chunks=(), *, stall=False, failure=None):
        self.chunks = chunks
        self.stall = stall
        self.failure = failure
        self.closed = False
        self.entered = asyncio.Event()

    async def __aiter__(self):
        self.entered.set()
        for chunk in self.chunks:
            yield chunk
            await asyncio.sleep(0)
        if self.failure:
            raise self.failure
        if self.stall:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@pytest.fixture
def make_gateway(config, request_model):
    def factory(*events, stream=None, status=200, headers=None, cfg=None):
        chosen = cfg or config
        wire = stream or WireStream([encode_events(*(events or (completed(),)))])
        calls = []

        async def handler(request):
            calls.append(request)
            return httpx.Response(
                status, headers=headers or {"Content-Type": "text/event-stream"}, stream=wire
            )

        ledger = BudgetLedger(chosen.budget_db)
        ledger.create_account(
            *request_model.context.account, request_model.context.scope_digest, 100000, 1000000
        )
        gateway = ModelGateway(
            chosen,
            ledger,
            transport=OpenAITransport(chosen, http_transport=httpx.MockTransport(handler)),
        )
        return gateway, wire, calls

    return factory
