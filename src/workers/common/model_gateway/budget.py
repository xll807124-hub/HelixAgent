"""Durable local-model budget holds. No prompt bodies or credentials are stored.

One unresolved request per account is deliberately conservative: after a crash,
opening the database cannot distinguish a live writer from a lost receipt. New
billing waits for settlement; unrelated task accounts can proceed concurrently.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from .types import ErrorCode, GatewayError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
 org TEXT NOT NULL, task TEXT NOT NULL, scope TEXT NOT NULL,
 limit_tokens INTEGER NOT NULL, limit_cost INTEGER NOT NULL,
 settled_tokens INTEGER NOT NULL DEFAULT 0, settled_cost INTEGER NOT NULL DEFAULT 0,
 reserved_tokens INTEGER NOT NULL DEFAULT 0, reserved_cost INTEGER NOT NULL DEFAULT 0,
 locked INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(org, task));
CREATE TABLE IF NOT EXISTS reservations (
 org TEXT NOT NULL, task TEXT NOT NULL, request TEXT NOT NULL, attempt INTEGER NOT NULL,
 digest TEXT NOT NULL, tokens INTEGER NOT NULL, cost INTEGER NOT NULL,
 pricing TEXT NOT NULL, state TEXT NOT NULL, actual_tokens INTEGER, actual_cost INTEGER,
 provider_id TEXT, legacy_cents INTEGER, PRIMARY KEY(org, task, request, attempt));
"""


def _amount(*values: int) -> None:
    if any(type(v) is not int or not 0 <= v <= 10**15 for v in values):
        raise GatewayError(ErrorCode.INVALID_REQUEST)


class BudgetLedger:
    """Thread-safe via SQLite transactions; use asyncio.to_thread at async boundaries."""

    def __init__(self, path: Path, lock_timeout: float = 0.25):
        if not path.is_absolute() or str(path).startswith(("//", "\\\\")):
            raise GatewayError(ErrorCode.INVALID_REQUEST)
        if not 0 < lock_timeout <= 5:
            raise GatewayError(ErrorCode.INVALID_REQUEST)
        self.path = path
        self.lock_timeout = lock_timeout
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(path, timeout=lock_timeout)) as db:
                db.executescript(_SCHEMA)
        except (OSError, sqlite3.Error):
            raise GatewayError(ErrorCode.STORAGE_UNAVAILABLE) from None

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(sqlite3.connect(self.path, timeout=self.lock_timeout)) as db, db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN IMMEDIATE")
                yield db
        except sqlite3.Error:
            raise GatewayError(ErrorCode.STORAGE_UNAVAILABLE) from None

    def create_account(
        self, org: str, task: str, scope: str, limit_tokens: int, limit_cost: int
    ) -> None:
        """Trusted provisioning only. Reopening never changes an existing limit."""
        _amount(limit_tokens, limit_cost)
        if not org or not task or not scope:
            raise GatewayError(ErrorCode.INVALID_REQUEST)
        with self._transaction() as db:
            old = db.execute("SELECT * FROM accounts WHERE org=? AND task=?", (org, task))
            row = old.fetchone()
            if row is not None:
                if (row["scope"], row["limit_tokens"], row["limit_cost"]) != (
                    scope,
                    limit_tokens,
                    limit_cost,
                ):
                    raise GatewayError(ErrorCode.REQUEST_CONFLICT)
                return
            db.execute(
                "INSERT INTO accounts(org,task,scope,limit_tokens,limit_cost) VALUES(?,?,?,?,?)",
                (org, task, scope, limit_tokens, limit_cost),
            )

    def reserve(
        self,
        org: str,
        task: str,
        scope: str,
        request: str,
        attempt: int,
        digest: str,
        tokens: int,
        cost: int,
        pricing: str,
    ) -> None:
        _amount(tokens, cost, attempt)
        if not request or not digest or not pricing or attempt == 0:
            raise GatewayError(ErrorCode.INVALID_REQUEST)
        with self._transaction() as db:
            account = db.execute(
                "SELECT * FROM accounts WHERE org=? AND task=?", (org, task)
            ).fetchone()
            if account is None or account["scope"] != scope:
                raise GatewayError(ErrorCode.PERMISSION)
            old = db.execute(
                "SELECT * FROM reservations WHERE org=? AND task=? AND request=? AND attempt=?",
                (org, task, request, attempt),
            ).fetchone()
            if old:
                code = (
                    ErrorCode.REQUEST_CONFLICT
                    if old["digest"] != digest
                    else ErrorCode.BUDGET_PENDING
                )
                raise GatewayError(code)
            pending = db.execute(
                "SELECT 1 FROM reservations WHERE org=? AND task=? "
                "AND state IN ('RESERVED','DISPATCHED','UNKNOWN') LIMIT 1",
                (org, task),
            ).fetchone()
            if account["locked"] or pending:
                raise GatewayError(ErrorCode.BUDGET_PENDING)
            if (
                account["settled_tokens"] + account["reserved_tokens"] + tokens
                > account["limit_tokens"]
                or account["settled_cost"] + account["reserved_cost"] + cost > account["limit_cost"]
            ):
                raise GatewayError(ErrorCode.BUDGET_EXCEEDED)
            db.execute(
                "UPDATE accounts SET reserved_tokens=reserved_tokens+?, "
                "reserved_cost=reserved_cost+? WHERE org=? AND task=?",
                (tokens, cost, org, task),
            )
            db.execute(
                "INSERT INTO reservations"
                "(org,task,request,attempt,digest,tokens,cost,pricing,state) "
                "VALUES(?,?,?,?,?,?,?,?, 'RESERVED')",
                (org, task, request, attempt, digest, tokens, cost, pricing),
            )

    def dispatch(self, org: str, task: str, request: str, attempt: int) -> None:
        with self._transaction() as db:
            updated = db.execute(
                "UPDATE reservations SET state='DISPATCHED' "
                "WHERE org=? AND task=? AND request=? AND attempt=? AND state='RESERVED'",
                (org, task, request, attempt),
            )
            if updated.rowcount != 1:
                raise GatewayError(ErrorCode.BUDGET_PENDING)

    def unknown(self, org: str, task: str, request: str, attempt: int) -> None:
        with self._transaction() as db:
            updated = db.execute(
                "UPDATE reservations SET state='UNKNOWN' "
                "WHERE org=? AND task=? AND request=? AND attempt=? "
                "AND state IN ('RESERVED','DISPATCHED','UNKNOWN')",
                (org, task, request, attempt),
            )
            if updated.rowcount:
                db.execute("UPDATE accounts SET locked=1 WHERE org=? AND task=?", (org, task))

    def release(self, org: str, task: str, request: str, attempt: int) -> None:
        """Only a provably undispatched reservation can be released."""
        with self._transaction() as db:
            row = self._reservation(db, org, task, request, attempt)
            if row["state"] != "RESERVED":
                raise GatewayError(ErrorCode.BUDGET_PENDING)
            db.execute(
                "UPDATE accounts SET reserved_tokens=reserved_tokens-?, "
                "reserved_cost=reserved_cost-? WHERE org=? AND task=?",
                (row["tokens"], row["cost"], org, task),
            )
            db.execute(
                "UPDATE reservations SET state='RELEASED' "
                "WHERE org=? AND task=? AND request=? AND attempt=?",
                (org, task, request, attempt),
            )

    def abort(self, org: str, task: str, request: str, attempt: int) -> None:
        """Cleanup for the caller that successfully reserved; safe after settlement."""
        with self._transaction() as db:
            row = self._reservation(db, org, task, request, attempt)
            if row["state"] == "RESERVED":
                db.execute(
                    "UPDATE accounts SET reserved_tokens=reserved_tokens-?, "
                    "reserved_cost=reserved_cost-? WHERE org=? AND task=?",
                    (row["tokens"], row["cost"], org, task),
                )
                db.execute(
                    "UPDATE reservations SET state='RELEASED' "
                    "WHERE org=? AND task=? AND request=? AND attempt=?",
                    (org, task, request, attempt),
                )
            elif row["state"] in ("DISPATCHED", "UNKNOWN"):
                db.execute(
                    "UPDATE reservations SET state='UNKNOWN' "
                    "WHERE org=? AND task=? AND request=? AND attempt=?",
                    (org, task, request, attempt),
                )
                db.execute("UPDATE accounts SET locked=1 WHERE org=? AND task=?", (org, task))

    def settle(
        self,
        org: str,
        task: str,
        request: str,
        attempt: int,
        tokens: int,
        cost: int,
        provider_id: str,
        out_of_bounds: bool = False,
    ) -> None:
        """Trusted receipt reconciliation; idempotent, with overrun persisted before error."""
        _amount(tokens, cost)
        overrun = False
        with self._transaction() as db:
            row = self._reservation(db, org, task, request, attempt)
            if row["state"] == "SETTLED":
                if (row["actual_tokens"], row["actual_cost"], row["provider_id"]) != (
                    tokens,
                    cost,
                    provider_id,
                ):
                    raise GatewayError(ErrorCode.REQUEST_CONFLICT)
                return
            if row["state"] not in ("DISPATCHED", "UNKNOWN"):
                raise GatewayError(ErrorCode.BUDGET_PENDING)
            account = db.execute(
                "SELECT * FROM accounts WHERE org=? AND task=?", (org, task)
            ).fetchone()
            previous = account["settled_cost"]
            cents = (previous + cost + 9999) // 10000 - (previous + 9999) // 10000
            overrun = out_of_bounds or tokens > row["tokens"] or cost > row["cost"]
            db.execute(
                "UPDATE accounts SET reserved_tokens=reserved_tokens-?, "
                "reserved_cost=reserved_cost-?, settled_tokens=settled_tokens+?, "
                "settled_cost=settled_cost+?, locked=? WHERE org=? AND task=?",
                (row["tokens"], row["cost"], tokens, cost, int(overrun), org, task),
            )
            db.execute(
                "UPDATE reservations SET state='SETTLED',actual_tokens=?,actual_cost=?,"
                "provider_id=?,legacy_cents=? WHERE org=? AND task=? AND request=? AND attempt=?",
                (tokens, cost, provider_id, cents, org, task, request, attempt),
            )
        if overrun:
            raise GatewayError(ErrorCode.BUDGET_EXCEEDED)

    @staticmethod
    def _reservation(
        db: sqlite3.Connection, org: str, task: str, request: str, attempt: int
    ) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM reservations WHERE org=? AND task=? AND request=? AND attempt=?",
            (org, task, request, attempt),
        ).fetchone()
        if row is None:
            raise GatewayError(ErrorCode.INVALID_REQUEST)
        return row

    def legacy_cents(self, org: str, task: str, request: str, attempt: int) -> int:
        with self._transaction() as db:
            row = self._reservation(db, org, task, request, attempt)
            if row["state"] != "SETTLED":
                raise GatewayError(ErrorCode.BUDGET_PENDING)
            return int(row["legacy_cents"])

    def snapshot(self, org: str, task: str) -> dict[str, Any]:
        with self._transaction() as db:
            row = db.execute(
                "SELECT * FROM accounts WHERE org=? AND task=?", (org, task)
            ).fetchone()
            if row is None:
                raise GatewayError(ErrorCode.PERMISSION)
            return dict(row)
