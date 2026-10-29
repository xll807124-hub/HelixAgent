from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.workers.common.model_gateway.budget import BudgetLedger
from src.workers.common.model_gateway.types import ErrorCode, GatewayError


def test_reservation_survives_reopen_and_prevents_replay(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "budget.db")
    ledger.create_account("org", "task", "scope", 100, 100)
    ledger.reserve("org", "task", "scope", "r1", 1, "digest", 70, 70, "price")
    reopened = BudgetLedger(tmp_path / "budget.db")
    with pytest.raises(GatewayError) as exc:
        reopened.reserve("org", "task", "scope", "r1", 1, "changed", 70, 70, "price")
    assert exc.value.code == ErrorCode.REQUEST_CONFLICT
    with pytest.raises(GatewayError):
        reopened.reserve("org", "task", "scope", "r1", 1, "digest", 70, 70, "price")
    assert reopened.snapshot("org", "task")["reserved_cost"] == 70


def test_concurrent_budget_has_one_winner(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "budget.db")
    ledger.create_account("org", "task", "scope", 100, 100)

    def contender(index):
        try:
            ledger.reserve("org", "task", "scope", str(index), 1, str(index), 70, 70, "p")
            return True
        except GatewayError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(contender, range(2))) == 1
    assert ledger.snapshot("org", "task")["reserved_cost"] == 70


def test_unknown_cost_locks_new_requests(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "budget.db")
    ledger.create_account("org", "task", "scope", 1000, 1000)
    ledger.reserve("org", "task", "scope", "r", 1, "d", 10, 10, "p")
    ledger.dispatch("org", "task", "r", 1)
    ledger.unknown("org", "task", "r", 1)
    with pytest.raises(GatewayError) as exc:
        ledger.reserve("org", "task", "scope", "new", 1, "new", 10, 10, "p")
    assert exc.value.code == ErrorCode.BUDGET_PENDING
    assert ledger.snapshot("org", "task")["reserved_cost"] == 10


def test_settlement_does_not_lose_fractional_cents(tmp_path: Path):
    ledger = BudgetLedger(tmp_path / "budget.db")
    ledger.create_account("org", "task", "scope", 100, 30000)
    for request in ("r1", "r2"):
        ledger.reserve("org", "task", "scope", request, 1, request, 10, 10000, "p")
        ledger.dispatch("org", "task", request, 1)
        ledger.settle("org", "task", request, 1, 5, 1, "resp-safe")
    assert ledger.snapshot("org", "task")["settled_cost"] == 2
    assert ledger.legacy_cents("org", "task", "r1", 1) == 1
    assert ledger.legacy_cents("org", "task", "r2", 1) == 0


@pytest.fixture
def funded(tmp_path):
    ledger = BudgetLedger(tmp_path / "funded.db")
    ledger.create_account("o", "t", "s", 100, 100)
    return ledger


def reserve(ledger, request="r", **changes):
    params = (
        dict(
            org="o",
            task="t",
            scope="s",
            request=request,
            attempt=1,
            digest="d",
            tokens=80,
            cost=80,
            pricing="v1",
        )
        | changes
    )
    ledger.reserve(**params)


@pytest.mark.parametrize("changes", [{"scope": "forged"}, {"org": "other"}, {"task": "other"}])
def test_scope_and_tenant_do_not_share_quota(funded, changes):
    with pytest.raises(GatewayError, match="PERMISSION"):
        reserve(funded, **changes)
    assert funded.snapshot("o", "t")["reserved_tokens"] == 0


@pytest.mark.parametrize("changes", [{"tokens": 101}, {"cost": 101}])
def test_budget_insufficient_is_atomic(funded, changes):
    with pytest.raises(GatewayError, match="BUDGET_EXCEEDED"):
        reserve(funded, **changes)
    assert funded.snapshot("o", "t")["reserved_cost"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"attempt": 0},
        {"request": ""},
        {"digest": ""},
        {"pricing": ""},
        {"tokens": -1},
        {"tokens": True},
        {"cost": 10**16},
    ],
)
def test_invalid_reservation(funded, changes):
    with pytest.raises(GatewayError, match="INVALID_REQUEST"):
        reserve(funded, **changes)


def test_account_immutable_and_invalid(funded):
    funded.create_account("o", "t", "s", 100, 100)
    with pytest.raises(GatewayError, match="REQUEST_CONFLICT"):
        funded.create_account("o", "t", "s", 200, 100)
    with pytest.raises(GatewayError, match="INVALID_REQUEST"):
        funded.create_account("", "t", "s", 100, 100)
    with pytest.raises(GatewayError, match="PERMISSION"):
        funded.snapshot("missing", "t")


def test_abort_before_dispatch_releases_only_once(funded):
    reserve(funded)
    funded.abort("o", "t", "r", 1)
    funded.abort("o", "t", "r", 1)
    assert funded.snapshot("o", "t")["reserved_tokens"] == 0
    with pytest.raises(GatewayError, match="BUDGET_PENDING"):
        reserve(funded)
    reserve(funded, "r2")


def test_release_and_dispatch_transitions(funded):
    with pytest.raises(GatewayError, match="INVALID_REQUEST"):
        funded.release("o", "t", "missing", 1)
    with pytest.raises(GatewayError, match="BUDGET_PENDING"):
        funded.dispatch("o", "t", "missing", 1)
    reserve(funded)
    with pytest.raises(GatewayError, match="BUDGET_PENDING"):
        funded.legacy_cents("o", "t", "r", 1)
    with pytest.raises(GatewayError, match="BUDGET_PENDING"):
        funded.settle("o", "t", "r", 1, 1, 1, "resp_1")
    funded.release("o", "t", "r", 1)
    assert funded.snapshot("o", "t")["reserved_cost"] == 0
    with pytest.raises(GatewayError, match="BUDGET_PENDING"):
        funded.release("o", "t", "r", 1)


def test_reconcile_unknown_unlocks_and_settlement_idempotent(funded):
    reserve(funded)
    funded.dispatch("o", "t", "r", 1)
    funded.abort("o", "t", "r", 1)
    funded.unknown("o", "t", "missing", 1)
    with pytest.raises(GatewayError, match="BUDGET_PENDING"):
        funded.release("o", "t", "r", 1)
    funded.settle("o", "t", "r", 1, 10, 10, "resp_1")
    funded.settle("o", "t", "r", 1, 10, 10, "resp_1")
    funded.abort("o", "t", "r", 1)
    funded.unknown("o", "t", "r", 1)
    assert funded.snapshot("o", "t")["locked"] == 0
    with pytest.raises(GatewayError, match="REQUEST_CONFLICT"):
        funded.settle("o", "t", "r", 1, 11, 10, "resp_1")
    reserve(funded, "r2")


@pytest.mark.parametrize(("tokens", "cost"), [(81, 10), (10, 81)])
def test_overrun_persists_actual_and_locks(funded, tokens, cost):
    reserve(funded)
    funded.dispatch("o", "t", "r", 1)
    with pytest.raises(GatewayError, match="BUDGET_EXCEEDED"):
        funded.settle("o", "t", "r", 1, tokens, cost, "resp_1")
    account = funded.snapshot("o", "t")
    assert account["settled_cost"] == cost and account["settled_tokens"] == tokens
    assert account["reserved_tokens"] == 0 and account["locked"] == 1
    with pytest.raises(GatewayError, match="BUDGET_PENDING"):
        reserve(funded, "r2", tokens=1, cost=1)


def test_path_errors_and_lock_contention(tmp_path, funded):
    import sqlite3
    from contextlib import closing

    with pytest.raises(GatewayError, match="INVALID_REQUEST"):
        BudgetLedger(Path("relative.db"))
    with pytest.raises(GatewayError, match="INVALID_REQUEST"):
        BudgetLedger(tmp_path / "x.db", lock_timeout=0)
    with pytest.raises(GatewayError, match="STORAGE_UNAVAILABLE"):
        BudgetLedger(tmp_path)  # Existing directory cannot be opened as a DB.
    with closing(sqlite3.connect(funded.path)) as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(GatewayError, match="STORAGE_UNAVAILABLE"):
            reserve(funded)
        db.rollback()
    reserve(funded)


def test_zero_budget_and_same_key_in_separate_org(funded):
    funded.create_account("zero", "t", "s", 0, 0)
    with pytest.raises(GatewayError, match="BUDGET_EXCEEDED"):
        reserve(funded, org="zero")
    funded.create_account("other", "t", "s", 100, 100)
    reserve(funded)
    reserve(funded, org="other")
    assert funded.snapshot("other", "t")["reserved_cost"] == 80
