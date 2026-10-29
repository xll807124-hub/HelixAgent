"""Explicit opt-in synthetic OpenAI smoke. No repository content or tool execution."""

import argparse
import asyncio
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

from src.workers.common.model_gateway.budget import BudgetLedger
from src.workers.common.model_gateway.environment import ConfigurationError, load_config
from src.workers.common.model_gateway.gateway import ModelGateway
from src.workers.common.model_gateway.types import (
    GatewayError,
    Message,
    ModelRequest,
    RequestContext,
)


async def run_live():
    config = load_config()
    try:
        tokens = int(os.environ["AI_MODEL_SMOKE_LIMIT_TOKENS"])
        microusd = int(os.environ["AI_MODEL_SMOKE_LIMIT_MICROUSD"])
        if not 0 < tokens <= 10**9 or not 0 < microusd <= 10**9:
            raise ValueError("invalid smoke limits")
    except (KeyError, ValueError):
        raise ConfigurationError() from None
    context = RequestContext(
        organization_id="synthetic-smoke",
        project_id="synthetic-project",
        repository_id="synthetic-repository",
        task_id="smoke-" + uuid.uuid4().hex,
        workflow_id="synthetic-workflow",
        worker_id="synthetic-worker",
        step_id="synthetic-step",
        trace_id=uuid.uuid4().hex,
        span_id=uuid.uuid4().hex[:16],
        request_id=uuid.uuid4().hex,
        deadline_at=datetime.now(UTC) + timedelta(seconds=config.total_timeout),
    )
    ledger = BudgetLedger(config.budget_db)
    ledger.create_account(*context.account, context.scope_digest, tokens, microusd)
    request = ModelRequest(
        context=context,
        profile_ref=config.profile.profile_ref,
        toolset_version="smoke-v1",
        messages=(
            Message(role="user", content="Return a final summary containing the word READY."),
        ),
        max_output_tokens=config.profile.max_output_tokens,
    )
    result = await ModelGateway(config, ledger).complete(request)
    return {
        "status": "passed",
        "scope": "synthetic model transport only; no tool or M1 acceptance",
        "model_id": result.model_id,
        "usage": result.usage.model_dump(),
        "provider_id_sha256": hashlib.sha256(result.provider_request_id.encode()).hexdigest(),
        "final_summary_present": bool(result.final_summary),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Explicitly allow one billable API call"
    )
    parser.add_argument(
        "--check-config", action="store_true", help="Validate config without network"
    )
    args = parser.parse_args()
    try:
        if args.check_config:
            load_config()
            report = {"status": "configured", "live_executed": False}
        elif args.live:
            report = asyncio.run(run_live())
        else:
            report = {"status": "not_executed", "reason": "live smoke requires --live"}
    except ConfigurationError as error:
        print(json.dumps({"status": "not_executed", "reason": str(error)}))
        return 2
    except GatewayError as error:
        print(json.dumps({"status": "failed", "error": error.code.value}))
        return 1
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
