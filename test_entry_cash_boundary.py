"""Actual Source cash boundaries; synthetic evidence and temporary DBs only."""
from copy import deepcopy
from decimal import Decimal
import json

import pytest

from test_hilega_application_preparation_v1 import env, process, counts
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_account_adapter_v1 import sign
from market_lab.hilega_preparation_runtime_v1.cash_reservation import verify_row


def set_cash(e, paise):
    assert PIN["scope"].startswith("FIXTURE:")
    value = str(Decimal(paise) / 100)
    changed = []

    def visit(node):
        if isinstance(node, dict):
            if node.get("field") == (
                "data.available_to_trade.cash_available_to_trade.total"
            ):
                node["cash_available_to_trade"] = value
                changed.append(1)
            for item in node.values():
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    data = e["data"]
    visit(data)
    assert changed, "Synthetic cash field not found"
    cash = data["cash_capture"]
    cash.pop("signature", None)
    cash["signature"] = sign(cash, PIN)
    data.pop("signature", None)
    data["signature"] = sign(data, PIN)


def reservations(e):
    with e["store"].db() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            ("preparation_cash_reservations",),
        ).fetchone()
        if not exists:
            return []
        return [json.loads(r[0]) for r in db.execute(
            "SELECT data FROM preparation_cash_reservations")]


def assert_no_transport(e):
    with e["adapter_store"].tx() as db:
        for table in ("attempts", "receipts"):
            assert db.execute(
                "SELECT COUNT(*) FROM " + table).fetchone()[0] == 0


@pytest.mark.parametrize("cash_paise,accepted", [
    (1320000, True),
    (1320001, True),
    (1319999, False),
    (0, False),
])
def test_actual_source_half_cash_boundary(bound_env, cash_paise, accepted):
    e = bound_env
    set_cash(e, cash_paise)
    process(e)
    assert_no_transport(e)

    if accepted:
        assert counts(e) == (1, 1, 1, 0, 0, 0)
        row, = reservations(e)
        verify_row(row, PIN)
        request, = e["adapter_store"].requests()
        assert row["id"] == request["request_id"]
        assert row["held_cents"] == 660000
        assert row["cash_cap_cents"] == cash_paise // 2
        assert row["held_cents"] <= row["cash_cap_cents"]
        assert row["broker_cash_locked"] is False
        assert row["production_execution_enabled"] is False
        assert row["reservation_release_permission"] is False

        original = deepcopy(row)
        e["source"].run_source_once(e["path"])
        assert reservations(e) == [original]
        assert len(e["adapter_store"].requests()) == 1
    else:
        assert counts(e) == (0, 0, 0, 0, 0, 0)
        assert reservations(e) == []
        assert e["adapter_store"].requests() == []
        with e["store"].db() as db:
            event = json.loads(db.execute(
                "SELECT data FROM preparation_events "
                "ORDER BY seq DESC LIMIT 1"
            ).fetchone()[0])
        expected = (
            "NO_CASH_CAPACITY" if cash_paise == 0
            else "HALF_CASH_CAP_EXCEEDED"
        )
        assert expected in event["reasons"]

    assert e["store"].control()["mode"] == "PAUSED"


@pytest.mark.parametrize("point", [
    "AFTER_ADAPTER_REQUEST_INSERT",
    "BEFORE_COMMIT",
])
def test_exact_boundary_rollback(bound_env, point):
    e = bound_env
    set_cash(e, 1320000)

    class Interrupted(BaseException):
        pass

    def interrupt(stage):
        if stage == point:
            raise Interrupted()

    e["source"].checkpoint = interrupt
    with pytest.raises(Interrupted):
        process(e)

    assert counts(e) == (0, 0, 0, 0, 0, 0)
    assert reservations(e) == []
    assert e["adapter_store"].requests() == []
    assert_no_transport(e)