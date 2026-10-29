"""Isolated design probe: local SQLite reservation atomicity, never imported by src.

Uses a temporary database and synthetic integers only. This is not a production
budget ledger, a billing implementation, or a model integration test.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path


def reserve(path: str, tenant: str, request: str, amount: int) -> str:
    if amount <= 0:
        raise ValueError("positive amount required")
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute(
            "SELECT amount FROM reservation WHERE tenant=? AND request=?",
            (tenant, request),
        ).fetchone()
        if old:
            return "duplicate" if old[0] == amount else "conflict"
        remaining = db.execute(
            "SELECT remaining FROM budget WHERE tenant=?", (tenant,)
        ).fetchone()
        if remaining is None or remaining[0] < amount:
            return "denied"
        db.execute("UPDATE budget SET remaining=remaining-? WHERE tenant=?", (amount, tenant))
        db.execute(
            "INSERT INTO reservation VALUES (?,?,?,?)", (tenant, request, amount, "reserved")
        )
    return "reserved"


def contender(path: str, request: str, start, results) -> None:
    if not start.wait(timeout=10):
        raise TimeoutError("probe start signal missing")
    results.put(reserve(path, "tenant-a", request, 70))


def main() -> None:
    started = time.perf_counter()
    cases = {}
    with tempfile.TemporaryDirectory(prefix="w-model-budget-probe-") as directory:
        path = str(Path(directory) / "budget.sqlite3")
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(
                "CREATE TABLE budget (tenant TEXT PRIMARY KEY, remaining INTEGER NOT NULL);"
                "CREATE TABLE reservation (tenant TEXT, request TEXT, amount INTEGER, "
                "state TEXT, PRIMARY KEY(tenant,request));"
                "INSERT INTO budget VALUES ('tenant-a',100),('tenant-b',100);"
            )
        context = mp.get_context("spawn")
        start, results = context.Event(), context.Queue()
        children = [
            context.Process(target=contender, args=(path, str(i), start, results))
            for i in range(2)
        ]
        try:
            for child in children:
                child.start()
            start.set()
            outcomes = sorted(results.get(timeout=15) for _ in children)
            for child in children:
                child.join(timeout=10)
                assert child.exitcode == 0, child.exitcode
            assert outcomes == ["denied", "reserved"], outcomes
            cases["two_process_competition"] = outcomes
        finally:
            for child in children:
                if child.is_alive():
                    child.terminate()
                    child.join(timeout=5)
            results.close()
            results.join_thread()
        with closing(sqlite3.connect(path)) as db, db:
            winner = db.execute("SELECT request FROM reservation").fetchone()[0]
            remaining = db.execute(
                "SELECT remaining FROM budget WHERE tenant='tenant-a'"
            ).fetchone()[0]
            assert remaining == 30
        cases["reopen_preserves_reservation"] = True
        assert reserve(path, "tenant-a", winner, 70) == "duplicate"
        cases["identical_request_no_second_debit"] = True
        assert reserve(path, "tenant-a", winner, 71) == "conflict"
        cases["changed_amount_rejected"] = True
        assert reserve(path, "tenant-b", winner, 70) == "reserved"
        cases["tenant_key_isolation"] = True
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("UPDATE reservation SET state='unknown' WHERE tenant='tenant-a'")
        assert reserve(path, "tenant-a", "new", 31) == "denied"
        cases["unknown_cost_retains_hold"] = True
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE budget SET remaining=0 WHERE tenant='tenant-a'")
            db.rollback()
        assert reserve(path, "tenant-a", "exact", 30) == "reserved"
        assert reserve(path, "tenant-a", "after-exact", 1) == "denied"
        cases["rollback_and_exact_budget_boundary"] = True
    summary = {
        "cases": cases,
        "passed": len(cases),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
