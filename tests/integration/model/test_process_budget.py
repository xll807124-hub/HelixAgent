"""Separate spawned processes contend on the same local coordination database."""

import multiprocessing
from pathlib import Path

import pytest

from src.workers.common.model_gateway.budget import BudgetLedger
from src.workers.common.model_gateway.types import GatewayError

pytestmark = pytest.mark.integration


def contender(path, barrier, output, request):
    ledger = BudgetLedger(Path(path), lock_timeout=2)
    barrier.wait(timeout=10)
    try:
        ledger.reserve("org", "task", "scope", request, 1, "digest", 70, 70, "v1")
        output.put("reserved")
    except GatewayError as error:
        output.put(error.code.value)


def test_process_race_and_restart_cannot_expand_quota(tmp_path):
    path = tmp_path / "process.db"
    ledger = BudgetLedger(path)
    ledger.create_account("org", "task", "scope", 100, 100)
    context = multiprocessing.get_context("spawn")
    barrier, output = context.Barrier(2), context.Queue()
    processes = [
        context.Process(target=contender, args=(str(path), barrier, output, str(index)))
        for index in range(2)
    ]
    try:
        for process in processes:
            process.start()
        results = [output.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        assert sorted(results) == ["BUDGET_PENDING", "reserved"]
        reopened = BudgetLedger(path)
        assert reopened.snapshot("org", "task")["reserved_tokens"] == 70
        with pytest.raises(GatewayError, match="BUDGET_PENDING"):
            reopened.reserve("org", "task", "scope", "new", 1, "new", 30, 30, "v1")
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        output.close()
        output.join_thread()
