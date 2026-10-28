from pathlib import Path
import hashlib
import os
import shutil
import tempfile

root = Path.cwd()
adapter = root / "backend/market_lab/hilega_execution_port_v1/adapter.py"
module = adapter.with_name("terminal.py")
tests = root / "tests/test_hilega_broker_terminal_review_v1.py"

raw = adapter.read_bytes()
blob = hashlib.sha1(
    b"blob " + str(len(raw)).encode() + b"\0" + raw
).hexdigest()
if blob != "caba35550ff12224adcd3133cbd35d9423d97357":
    raise SystemExit("STOP: adapter differs from the reviewed version")
for path in (module, tests):
    if path.exists() or path.is_symlink():
        raise SystemExit("STOP: file already exists: " + str(path))

module_text = r'''"""Read-only account observations; no ownership or release authority."""
from market_lab.hilega_production_account_adapter_v1 import (
    AdapterBlocked, canonical, normalise, verify,
)


def review(capture, pin, *, as_of):
    verify(capture, pin, as_of=as_of)
    if capture.get("profile_verified_before_and_after") is not True:
        raise AdapterBlocked("PROFILE_SWEEP_VERIFICATION_REQUIRED")
    if capture.get("account_position_rows_complete") is not True:
        raise AdapterBlocked("COMPLETE_POSITION_ROWS_REQUIRED")
    if capture.get("source_atomic") is not False:
        raise AdapterBlocked("UNSUPPORTED_ATOMIC_CAPTURE_CLAIM")

    names = ("orders", "trades", "positions")
    if any(
        not isinstance(capture.get(name), list)
        or any(not isinstance(row, dict) for row in capture[name])
        for name in names
    ):
        raise AdapterBlocked("NORMALIZED_CAPTURE_SCHEMA_INVALID")

    # Reuse the account adapter's quantity, identity, timestamp and status
    # validation. Round-trip equality also rejects altered normalized fields
    # and duplicate rows silently collapsed by normalization.
    try:
        orders = [
            dict(
                order_id=o["order_id"], instrument_token=o["instrument"],
                product=o["product"], transaction_type=o["side"],
                quantity=o["quantity"], filled_quantity=o["filled"],
                pending_quantity=o["pending"], status=o["source_status"],
                order_timestamp=o["placed_at"],
            )
            for o in capture["orders"]
        ]
        trades = [
            dict(
                order_id=t["order_id"], trade_id=t["trade_id"],
                instrument_token=t["instrument"], product=t["product"],
                transaction_type=t["side"], quantity=t["quantity"],
                average_price=t["price"], exchange_timestamp=t["filled_at"],
            )
            for t in capture["trades"]
        ]
        positions = [
            dict(
                instrument_token=p["instrument"], product=p["product"],
                quantity=p["quantity"],
            )
            for p in capture["positions"]
        ]
        checked = normalise(
            {"data": orders}, {"data": trades}, {"data": positions},
            observed_at=capture["completed_at"],
        )
        if any(
            canonical(checked[name]) != canonical(capture[name])
            for name in names
        ):
            raise AdapterBlocked("NORMALIZED_CAPTURE_CONTENT_MISMATCH")
    except (KeyError, TypeError):
        raise AdapterBlocked("NORMALIZED_CAPTURE_SCHEMA_INVALID") from None

    reasons = set()
    terminal = {"FILLED", "CANCELLED", "REJECTED"}
    if any(o["status"] not in terminal for o in checked["orders"]):
        reasons.add("NON_TERMINAL_ORDERS")

    issues = checked["diagnostics"]["issues"]
    if "ORDER_TRADE_FILL_TOTAL_MISMATCH" in issues:
        reasons.add("ORDER_TRADE_FILL_TOTAL_MISMATCH")

    net = {}
    for trade in checked["trades"]:
        key = (trade["instrument"], trade["product"])
        sign = 1 if trade["side"] == "BUY" else -1
        net[key] = net.get(key, 0) + sign * trade["quantity"]
    if any(net.values()):
        reasons.add("TRADE_NET_NOT_FLAT")
    if any(p["quantity"] != 0 for p in checked["positions"]):
        reasons.add("POSITION_NOT_FLAT")

    if reasons:
        status = "RECONCILIATION_REQUIRED"
    elif checked["orders"] or checked["trades"]:
        status = "TERMINAL_FLAT_ACCOUNT_OBSERVATION"
    else:
        status = "EMPTY_ACCOUNT_OBSERVATION"

    return dict(
        model="HILEGA_BROKER_TERMINAL_REVIEW_V1",
        status=status,
        reasons=sorted(reasons),
        assessed_at=as_of,
        snapshot_id=capture.get("snapshot_id"),
        order_count=len(checked["orders"]),
        trade_count=len(checked["trades"]),
        position_row_count=len(checked["positions"]),
        source_atomic=False,
        strategy_ownership_verified=False,
        real_funds_reservation_verified=False,
        reservation_release_permission=False,
        entry_permission=False,
        production_execution_enabled=False,
        production_ready=False,
        orders_sent=False,
    )
'''

test_text = r'''from copy import deepcopy
from datetime import datetime, timedelta
import json

import pytest

from market_lab.domain import IST
from market_lab import hilega_production_account_adapter_v1 as account
from market_lab.hilega_execution_port_v1.adapter import (
    Adapter, Blocked, GateClosed, HttpTransport, Store,
)
from market_lab.hilega_execution_port_v1.terminal import review

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=IST)
PIN = {"key": "11" * 32, "scope": "UPSTOX:" + "22" * 32}


def signed(value):
    value.pop("signature", None)
    value["signature"] = account.sign(value, PIN)
    return value


def capture():
    orders, trades = [], []
    for i, side in enumerate(("BUY", "SELL")):
        at = NOW - timedelta(minutes=20 - i * 5)
        orders.append(dict(
            order_id=str(i), instrument_token="NSE_FO|TEST",
            product="I", transaction_type=side, quantity=65,
            filled_quantity=65, pending_quantity=0, status="complete",
            order_timestamp=at.isoformat(),
        ))
        trades.append(dict(
            order_id=str(i), trade_id="t" + str(i),
            instrument_token="NSE_FO|TEST", product="I",
            transaction_type=side, quantity=65, average_price=100,
            exchange_timestamp=(at + timedelta(seconds=1)).isoformat(),
        ))
    normalized = account.normalise(
        {"data": orders}, {"data": trades},
        {"data": [dict(
            instrument_token="NSE_FO|TEST", product="I", quantity=0,
        )]},
        observed_at=NOW.isoformat(),
    )
    return signed(dict(
        model=account.MODEL, evidence_mode=account.LIVE,
        generated_at=(NOW - timedelta(seconds=1)).isoformat(),
        completed_at=NOW.isoformat(), session_date="2026-10-28",
        account_scope=PIN["scope"], snapshot_id="synthetic-test",
        status="READ_ONLY_CAPTURED", account_identity_verified=True,
        profile_verified_before_and_after=True, source_atomic=False,
        orders_sent=False, entry_permission=False,
        production_execution_enabled=False, **normalized,
    ))


def test_terminal_flat_observation_has_no_execution_authority():
    value = capture()
    before = deepcopy(value)
    result = review(value, PIN, as_of=NOW.isoformat())
    assert result["status"] == "TERMINAL_FLAT_ACCOUNT_OBSERVATION"
    assert result["reasons"] == []
    for name in (
        "strategy_ownership_verified", "real_funds_reservation_verified",
        "reservation_release_permission", "entry_permission",
        "production_execution_enabled", "production_ready", "orders_sent",
    ):
        assert result[name] is False
    assert value == before


@pytest.mark.parametrize("case,reason", [
    ("position", "POSITION_NOT_FLAT"),
    ("missing_trade", "ORDER_TRADE_FILL_TOTAL_MISMATCH"),
    ("partial_cancel", "TRADE_NET_NOT_FLAT"),
    ("open", "NON_TERMINAL_ORDERS"),
])
def test_unresolved_account_retains_review(case, reason):
    value = capture()
    if case == "position":
        value["positions"][0]["quantity"] = 65
    elif case == "missing_trade":
        value["trades"].pop()
    elif case == "partial_cancel":
        value["orders"][0].update(
            status="CANCELLED", source_status="cancelled", filled=64,
        )
        value["trades"][0]["quantity"] = 64
    else:
        value["orders"][0].update(
            status="PARTIAL", source_status="open", filled=64, pending=1,
        )
        value["trades"][0]["quantity"] = 64
    result = review(signed(value), PIN, as_of=NOW.isoformat())
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert reason in result["reasons"]
    assert result["reservation_release_permission"] is False


@pytest.mark.parametrize("case", [
    "duplicate_order", "duplicate_trade", "duplicate_position",
    "status", "boolean_quantity", "incomplete_positions", "atomic_claim",
])
def test_invalid_signed_content_is_rejected(case):
    value = capture()
    if case.startswith("duplicate"):
        name = {
            "duplicate_order": "orders", "duplicate_trade": "trades",
            "duplicate_position": "positions",
        }[case]
        value[name].append(deepcopy(value[name][0]))
    elif case == "status":
        value["orders"][0]["status"] = "CANCELLED"
    elif case == "boolean_quantity":
        value["orders"][0]["quantity"] = True
    elif case == "incomplete_positions":
        value["account_position_rows_complete"] = False
    else:
        value["source_atomic"] = True
    with pytest.raises(account.AdapterBlocked):
        review(signed(value), PIN, as_of=NOW.isoformat())


def test_signature_freshness_and_scope_checks_remain_required():
    value = capture()
    value["positions"][0]["quantity"] = 1
    with pytest.raises(account.AdapterBlocked, match="SIGNATURE"):
        review(value, PIN, as_of=NOW.isoformat())
    with pytest.raises(account.AdapterBlocked, match="STALE_OR_FUTURE"):
        review(
            capture(), PIN,
            as_of=(NOW + timedelta(seconds=31)).isoformat(),
        )
    wrong_pin = {**PIN, "scope": "UPSTOX:" + "33" * 32}
    with pytest.raises(account.AdapterBlocked, match="SCOPE"):
        review(capture(), wrong_pin, as_of=NOW.isoformat())


def dump(store):
    with store.tx() as db:
        return list(db.iterdump())


def test_adapter_adds_observation_without_writes_or_adopting_orders(tmp_path):
    store = Store(tmp_path / "adapter.sqlite", PIN["scope"], "LIVE_CLOSED")
    transport = HttpTransport(
        lambda: pytest.fail("Token must not be accessed")
    )
    adapter = Adapter(store, transport)
    before = dump(store)
    result = adapter.reconcile_read_only(
        capture(), PIN, as_of=NOW.isoformat(),
    )
    assert result["status"] == "READ_ONLY_OWNERSHIP_REVIEW"
    assert result["matched_known_order_count"] == 0
    assert result["ownership_verified"] is False
    assert result["terminal_account_review"]["status"] == (
        "TERMINAL_FLAT_ACCOUNT_OBSERVATION"
    )
    with pytest.raises(GateClosed):
        transport.check()
    with pytest.raises(Blocked):
        adapter.release_reservation()
    assert dump(store) == before


def test_unacknowledged_request_is_not_an_empty_baseline(tmp_path):
    store = Store(tmp_path / "adapter.sqlite", PIN["scope"], "LIVE_CLOSED")
    with store.tx() as db:
        db.execute(
            "INSERT INTO requests VALUES(?,?,?)",
            ("pending", "synthetic", json.dumps({
                "request_id": "pending", "state": "UNKNOWN",
            })),
        )
    value = capture()
    value.update(orders=[], trades=[], positions=[])
    adapter = Adapter(store, HttpTransport(
        lambda: pytest.fail("Token must not be accessed")
    ))
    before = dump(store)
    result = adapter.reconcile_read_only(
        signed(value), PIN, as_of=NOW.isoformat(),
    )
    assert result["status"] == "READ_ONLY_OWNERSHIP_REVIEW"
    assert result["ownership_verified"] is False
    assert dump(store) == before
'''

text = raw.decode()
start = text.index("    def reconcile_read_only(")
end = text.index("    def import_acknowledgement(", start)
old = text[start:end]
new = old
changes = [
    (
        "from market_lab.hilega_production_account_adapter_v1 import verify",
        "from .terminal import review as terminal_review",
    ),
    (
        "verify(capture,pin,as_of=as_of)",
        "terminal=terminal_review(capture,pin,as_of=as_of)",
    ),
    (
        "known={r['order_id']:r for r in self.store.requests() if r.get('order_id')}",
        "rows=self.store.requests()\n"
        "        known={r['order_id']:r for r in rows if r.get('order_id')}",
    ),
    (
        "matched=0;review=False",
        "matched=0;review=any(not r.get('order_id') for r in rows)",
    ),
    (
        "ownership_verified=False,entry_permission=False",
        "terminal_account_review=terminal,"
        "ownership_verified=False,entry_permission=False",
    ),
]
for before, after in changes:
    if new.count(before) != 1:
        raise SystemExit("STOP: adapter replacement did not match")
    new = new.replace(before, after, 1)
updated = text[:start] + new + text[end:]

for path, content in (
    (module, module_text), (tests, test_text), (adapter, updated),
):
    compile(content, str(path), "exec")

backup_root = root / "backups"
backup_root.mkdir(exist_ok=True)
backup = Path(tempfile.mkdtemp(
    prefix="hilega-terminal-review-", dir=backup_root,
))
shutil.copy2(adapter, backup / "adapter.py")

for path, content in ((module, module_text), (tests, test_text)):
    with path.open("x") as stream:
        stream.write(content)

fd, temporary = tempfile.mkstemp(
    prefix=".adapter-terminal-", dir=adapter.parent,
)
try:
    with os.fdopen(fd, "w") as stream:
        stream.write(updated)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, adapter.stat().st_mode & 0o777)
    os.replace(temporary, adapter)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)

print("Created:", module)
print("Created:", tests)
print("Updated:", adapter)
print("Backup:", backup)
print("Syntax checked. Tests not executed. No activation performed.")