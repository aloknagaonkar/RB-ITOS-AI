
"""Read-only historical acknowledgement/current fill comparison.
Never establishes strategy ownership, P&L, reservation or execution authority.
"""
import hashlib
import json
import os
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

PINS = {
    "backend/market_lab/hilega_execution_port_v1/receipt_review.py":
        "ac97a3f5f0df3b7d79ddcbe4719b169e83aebd2568dfb18c175e0994d8c6a418",
    "backend/market_lab/hilega_production_account_adapter_v1.py":
        "9484899b374701c211adf22b67ea5fc84d0cdb978defe061ce8250cb7313b140",
}

def need(ok, reason):
    if not ok:
        raise ValueError(reason)

def regular(path):
    need(path.is_file() and not path.is_symlink(), "REGULAR_FILE_REQUIRED")

def compare(links, snapshot):
    """Numeric reference comparison only; historical links remain historical."""
    orders = {}
    for row in snapshot["orders"]:
        oid = row["order_id"]
        need(oid not in orders, "DUPLICATE_ORDER_ID")
        orders[oid] = row

    totals = {}
    seen = set()
    for row in snapshot["trades"]:
        key = (row["order_id"], row["trade_id"])
        need(key not in seen, "DUPLICATE_TRADE_ID")
        seen.add(key)
        order = orders.get(row["order_id"])
        need(order is not None, "TRADE_ORDER_MISSING")
        need(all(row[k] == order[k] for k in
                 ("instrument", "product", "side")), "TRADE_IDENTITY_MISMATCH")
        need(type(row["quantity"]) is int and row["quantity"] > 0,
             "TRADE_QUANTITY_INVALID")
        totals[row["order_id"]] = totals.get(row["order_id"], 0) + row["quantity"]

    for oid, order in orders.items():
        need(type(order["filled"]) is int and order["filled"] >= 0,
             "FILLED_QUANTITY_INVALID")
        need(totals.get(oid, 0) == order["filled"],
             "ORDER_TRADE_FILL_TOTAL_MISMATCH")

    matched = missing = 0
    matched_ids = set()
    for link in links:
        order = orders.get(link["order_id"])
        if order is None:
            missing += 1
            continue
        need(all(order[k] == link[k] for k in
                 ("instrument", "product", "side", "quantity")),
             "HISTORICAL_ACK_CURRENT_ORDER_MISMATCH")
        matched += 1
        matched_ids.add(link["order_id"])

    return {
        "historical_acknowledgement_count": len(links),
        "current_order_reference_matches": matched,
        "historical_orders_absent_from_current_snapshot": missing,
        "current_orders_without_historical_reference":
            len(set(orders) - matched_ids),
        "current_order_count": len(orders),
        "current_trade_count": len(snapshot["trades"]),
        "nonzero_position_count": sum(
            row["quantity"] != 0 for row in snapshot["positions"]
        ),
        "nonterminal_order_count": sum(
            row["status"] in {"OPEN", "PARTIAL"} for row in orders.values()
        ),
    }

def main():
    need(sys.argv[1:] == ["--capture-account"],
         "EXPLICIT_CAPTURE_ACCOUNT_FLAG_REQUIRED")
    for name, expected in PINS.items():
        path = ROOT / name
        regular(path)
        need(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
             "SOURCE_HASH_CHANGED")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend") + ":" + str(ROOT)
    result = subprocess.run(
        [str(ROOT / ".venv/bin/python"),
         str(ROOT / "check-preparation-paused.py")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    need(result.returncode == 0, "PAUSED_CHECK_COMMAND_FAILED")
    checked = json.loads(result.stdout)
    need(
        checked.get("status") == "PAUSED_SAFE_SOURCE_FRESH"
        and checked.get("controller_mode") == "PAUSED"
        and checked.get("execution_route") == "PREPARATION_ONLY"
        and checked.get("production_ready") is False,
        "FRESH_PAUSED_PREPARATION_REQUIRED",
    )

    from market_lab.hilega_execution_port_v1.receipt_review import _check
    from market_lab.hilega_production_account_adapter_v1 import (
        Client, capture, read_pin, verify,
    )
    from dotenv import dotenv_values

    pin = read_pin(Path.home() / "hilega-private/upstox-account-pin.json")
    dbpath = ROOT / "data/research/hilega-broker-adapter-closed/adapter.sqlite"
    regular(dbpath)
    with dbpath.open("rb") as stream:
        header = stream.read(100)
    need(header[:16] == b"SQLite format 3\x00"
         and header[18:20] == b"\x01\x01", "DELETE_JOURNAL_DATABASE_REQUIRED")
    for suffix in ("-wal", "-shm", "-journal"):
        need(not Path(str(dbpath) + suffix).exists(), "DATABASE_SIDECAR_PRESENT")

    # No Store construction: existing database is opened read-only.
    with closing(sqlite3.connect(
        dbpath.resolve().as_uri() + "?mode=ro", uri=True, timeout=10
    )) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        meta = json.loads(db.execute(
            "SELECT data FROM meta WHERE id=1"
        ).fetchone()[0])
        need(meta == {"scope": pin["scope"], "mode": "LIVE_CLOSED"},
             "ADAPTER_SCOPE_OR_MODE_MISMATCH")
        requests = db.execute(
            "SELECT id,fingerprint,data FROM requests ORDER BY rowid"
        ).fetchall()
        attempts = db.execute(
            "SELECT id,request_id,operation,data FROM attempts"
        ).fetchall()
        receipts = dict(db.execute("SELECT id,data FROM receipts").fetchall())
        db.rollback()
    historical = _check("LIVE_CLOSED", requests, attempts, receipts)

    settings = dotenv_values(ROOT / ".env")
    def setting(name):
        shell, file = os.getenv(name), settings.get(name)
        need(not (shell and file and shell != file), "TOKEN_CONFIGURATION_CONFLICT")
        return shell or file
    primary = setting("HILEGA_PRODUCTION_BROKER_READ_TOKEN")
    secondary = setting("UPSTOX_ACCESS_TOKEN")
    token = (primary or secondary or "").strip()
    need(bool(token), "READ_TOKEN_MISSING")

    snapshot = capture(Client(token), pin)
    verify(snapshot, pin, as_of=datetime.now(timezone.utc).isoformat())
    need(snapshot.get("profile_verified_before_and_after") is True
         and snapshot.get("account_position_rows_complete") is True,
         "COMPLETE_PINNED_ACCOUNT_CAPTURE_REQUIRED")
    summary = compare(historical["bindings"], snapshot)
    summary.update(
        model="HILEGA_ACCOUNT_FILL_REFERENCE_REVIEW_V1",
        status="REVIEW_COMPLETE_PRODUCTION_STILL_BLOCKED",
        scope="HISTORICAL_REFERENCES_AND_CURRENT_READ_ONLY_CAPTURE",
        account_identity_and_local_signature_verified=True,
        historical_receipt_status=historical["status"],
        unbound_request_count=historical["unbound_request_count"],
        broker_reads_performed=True,
        source_atomic=False,
        application_hold_link_verified=False,
        strategy_ownership_verified=False,
        fees_complete=False,
        realized_net_pnl=None,
        open_net_pnl=None,
        database_modified=False,
        controller_changed=False,
        entry_permission=False,
        reservation_release_permission=False,
        orders_sent=False,
        production_execution_enabled=False,
        production_ready=False,
    )
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print raw provider responses, credentials or account rows.
        print(json.dumps({
            "status": "STOPPED_FOR_REVIEW",
            "error_type": type(exc).__name__,
            "production_execution_enabled": False,
            "production_ready": False,
        }))
        raise SystemExit(1)
