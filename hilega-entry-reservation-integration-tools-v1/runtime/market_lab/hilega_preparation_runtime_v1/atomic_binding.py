"""Atomic disabled request/hold references; no execution or release authority."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re

from .evidence import FLAGS, digest, need, readonly
from .limit_candidate import build_candidate, fresh_plan
from .cash_reservation import reserve_local
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE
from market_lab.hilega_execution_port_v1.adapter import (
    validated_request, encode,
)


def enabled():
    value = os.getenv("HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "0")
    need(value in {"0", "1"}, "ATOMIC_BINDING_MODE_INVALID")
    return value == "1"


class AdapterReader:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, parameters=()):
        need(sql.lstrip().startswith("SELECT"), "ADAPTER_READER_SELECT_ONLY")
        translated, count = re.subn(
            r"\bFROM\s+(meta|requests|attempts|receipts)\b",
            lambda match: "FROM broker." + match.group(1),
            sql,
        )
        need(count == 1, "ADAPTER_READER_QUERY_UNSUPPORTED")
        return self.db.execute(translated, parameters)


@contextmanager
def source_transaction(store, adapter_path):
    if not enabled():
        with readonly(adapter_path) as adapter, store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            yield adapter, db
        return

    path = Path(adapter_path)
    need(path.is_file() and not path.is_symlink(),
         "REGULAR_EXISTING_ADAPTER_REQUIRED")
    need(store.path.is_file() and not store.path.is_symlink(),
         "REGULAR_APPLICATION_DATABASE_REQUIRED")
    need(not path.samefile(store.path), "DISTINCT_DATABASES_REQUIRED")
    need(path.stat().st_dev == store.path.stat().st_dev,
         "SAME_FILESYSTEM_REQUIRED")

    with store.db() as db:
        need(not db.in_transaction, "UNEXPECTED_EXISTING_TRANSACTION")
        need(db.execute("PRAGMA main.journal_mode").fetchone()[0] == "delete",
             "APPLICATION_DELETE_JOURNAL_REQUIRED")
        db.execute("ATTACH DATABASE ? AS broker", (str(path.resolve()),))
        need(db.execute("PRAGMA broker.journal_mode").fetchone()[0] == "delete",
             "ADAPTER_DELETE_JOURNAL_REQUIRED")
        for schema in ("main", "broker"):
            db.execute("PRAGMA " + schema + ".synchronous=FULL")
            need(db.execute(
                "PRAGMA " + schema + ".synchronous"
            ).fetchone()[0] >= 2, "FULL_DURABILITY_REQUIRED")
        db.execute("BEGIN IMMEDIATE")
        yield AdapterReader(db), db
        # Store.db commits or rolls back the entire attached transaction.


def bind_disabled_request(db, plan, hold, outbox, bundle, pin, *, now):
    if not enabled():
        return False
    need(
        json.loads(db.execute(
            "SELECT data FROM broker.meta WHERE id=1"
        ).fetchone()[0]) == {"scope": pin["scope"], "mode": "LIVE_CLOSED"},
        "BOUND_ADAPTER_SCOPE_MISMATCH",
    )
    candidate = outbox["disabled_request_candidate"]
    expected = build_candidate(
        plan, hold, outbox, bundle, pin, now=now,
        session_date=plan["signal_at"][:10],
        fee_buffer_cents=candidate["fee_buffer_cents"], profile=PROFILE,
    )
    need(candidate == expected, "DISABLED_CANDIDATE_CHANGED")
    current = fresh_plan(bundle, pin, plan["direction"], now, PROFILE)

    total = 0
    for key, raw in db.execute(
        "SELECT id,data FROM preparation_shadow_holds"
    ):
        existing = json.loads(raw)
        owner = db.execute(
            "SELECT data FROM preparation_plans WHERE id=?", (key,),
        ).fetchone()
        need(owner is not None
             and json.loads(owner[0])["account_scope"] == pin["scope"],
             "UNKNOWN_HOLD_OWNER")
        amount = existing["held_cents"]
        need(type(amount) is int and amount > 0, "INVALID_HELD_AMOUNT")
        total += amount
    need(
        total <= current["half_cash_cap_cents"]
        and candidate["budget_cents"] <= hold["held_cents"],
        "TOTAL_HOLDS_EXCEED_CASH_CAP",
    )

    row, fingerprint = validated_request(
        candidate["draft"],
        signal_id=plan["id"], signal_at=plan["signal_at"],
        direction=plan["direction"],
        reservation_reference=hold["id"], as_of=now.isoformat(),
    )
    need(row["request_id"] == plan["id"] == hold["id"] == outbox["id"],
         "REQUEST_HOLD_ID_MISMATCH")
    need(row["draft"]["body"]["transaction_type"] == "BUY"
         and row["draft"]["body"]["quantity"] == plan["quantity"]
         and row["draft"]["body"]["instrument_token"] == plan["instrument"],
         "REQUEST_HOLD_CONTRACT_MISMATCH")
    need(not db.execute("SELECT 1 FROM broker.requests LIMIT 1").fetchone()
         and not db.execute("SELECT 1 FROM broker.attempts LIMIT 1").fetchone()
         and not db.execute("SELECT 1 FROM broker.receipts LIMIT 1").fetchone(),
         "EXISTING_ADAPTER_ACTIVITY_REQUIRES_REVIEW")

    db.execute(
        "CREATE TABLE IF NOT EXISTS preparation_request_bindings("
        "id TEXT PRIMARY KEY,data TEXT NOT NULL)"
    )
    reserve_local(
        db, plan, hold, outbox, pin, current, fingerprint, now=now,
    )
    db.execute(
        "INSERT INTO broker.requests VALUES(?,?,?)",
        (row["request_id"], fingerprint, encode(row)),
    )
    db.execute(
        "INSERT INTO broker.events(data) VALUES(?)",
        (encode(dict(
            type="REQUEST_PREPARED", request_id=row["request_id"],
            body_fingerprint=row["draft"]["fingerprint"],
            origin="APPLICATION_ATOMIC_DISABLED_BINDING",
        )),),
    )
    binding = dict(
        FLAGS,
        model="HILEGA_ATOMIC_DISABLED_REQUEST_BINDING_V1",
        id=plan["id"], account_scope=pin["scope"],
        request_fingerprint=fingerprint,
        plan_fingerprint=digest(plan),
        hold_fingerprint=digest(hold),
        outbox_fingerprint=digest(outbox),
        held_cents=hold["held_cents"],
        cash_cap_cents=current["half_cash_cap_cents"],
        bundle_fingerprint=digest(bundle),
        local_budget_reference_bound=True,
        broker_cash_locked=False,
        status="PREPARED_DISABLED_HOLD_RETAINED",
    )
    db.execute(
        "INSERT INTO preparation_request_bindings VALUES(?,?)",
        (plan["id"], encode(binding)),
    )
    return True
