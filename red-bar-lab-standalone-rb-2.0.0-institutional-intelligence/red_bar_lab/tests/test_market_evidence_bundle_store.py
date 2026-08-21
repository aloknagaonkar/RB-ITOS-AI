import json
import sqlite3

from red_bar_lab.services.market_evidence_bundle_store import (
    persist_market_evidence_bundle,
)


def test_persist_market_evidence_bundle_is_deterministic_and_additive(tmp_path):
    database_path = tmp_path / "evidence.db"
    view = {
        "as_of_timestamp": "2026-08-21T06:30:00+00:00",
        "latest_complete_evidence_time": "2026-08-21T06:25:00+00:00",
        "underlying_timestamp": "2026-08-21T06:25:00+00:00",
        "futures_market_timestamp": "2026-08-21T06:25:00+00:00",
        "futures_collection_timestamp": "2026-08-21T06:29:00+00:00",
        "option_timestamp": "2026-08-21T06:29:30+00:00",
        "observed_direction": "BEARISH",
        "structural_state": "HOLD_CONFIRMED",
        "direction_state": "CONFIRMED_WITH_CAUTION",
        "evidence_readiness": "STALE",
        "contract_quality": "PASS",
        "trade_eligibility": "BLOCKED",
        "trade_bias": "WAIT",
        "blocking_reasons": ("OPTION_SNAPSHOT_STALE",),
        "caution_reasons": ("WEAK_FUTURES_OPPOSITION",),
    }

    first = persist_market_evidence_bundle(
        database_path,
        underlying_name="NIFTY 50",
        view=view,
    )
    second = persist_market_evidence_bundle(
        database_path,
        underlying_name="NIFTY 50",
        view=view,
    )

    assert first == second
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM market_evidence_bundles WHERE bundle_id=?",
            (first,),
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM market_evidence_bundles"
        ).fetchone()[0]
    assert count == 1
    assert row is not None
    payload = json.loads(row[-2])
    assert payload["observed_direction"] == "BEARISH"
