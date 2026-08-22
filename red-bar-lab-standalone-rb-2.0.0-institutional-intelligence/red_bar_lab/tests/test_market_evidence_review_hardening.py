from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from red_bar_lab.services.authoritative_market_evidence import (
    completed_bar_timestamps,
)
from red_bar_lab.services.market_evidence_bundle_store import (
    persist_market_evidence_bundle,
    read_latest_market_evidence_bundle,
)
from red_bar_lab.services.nifty_futures_snapshot_store import (
    persist_nifty_futures_snapshot,
    read_nifty_futures_snapshots,
)


def test_completed_bar_timestamps_preserve_observed_at_semantics():
    result = completed_bar_timestamps(
        {
            "observed_at": "2026-08-22T09:15:00+00:00",
            "bar_open_timestamp": "2026-08-22T09:15:00+00:00",
        },
        interval_minutes=5,
    )

    assert result["observed_at"] == "2026-08-22T09:15:00+00:00"
    assert result["bar_open_timestamp"] == "2026-08-22T09:15:00+00:00"
    assert result["bar_close_timestamp"] == "2026-08-22T09:20:00+00:00"


def test_futures_bar_timestamps_survive_persistence(tmp_path: Path):
    database_path = tmp_path / "evidence.sqlite"
    persist_nifty_futures_snapshot(
        database_path,
        observed_at="2026-08-22T09:21:00+00:00",
        underlying_name="NIFTY 50",
        contract={"status": "READY"},
        market={
            "status": "READY",
            "latest_timestamp": "2026-08-22T09:20:00+00:00",
            "bar_open_timestamp": "2026-08-22T09:15:00+00:00",
            "bar_close_timestamp": "2026-08-22T09:20:00+00:00",
        },
        positioning={"status": "READY", "state": "LONG_BUILDUP"},
        strength={"status": "READY", "strength": "MODERATE"},
        readiness={"status": "READY", "candle_status": "READY"},
    )

    row = read_nifty_futures_snapshots(
        database_path,
        underlying_name="NIFTY 50",
        limit=1,
    )[0]

    assert row["bar_open_timestamp"] == "2026-08-22T09:15:00+00:00"
    assert row["bar_close_timestamp"] == "2026-08-22T09:20:00+00:00"
    assert row["futures_bar_close_timestamp"] == "2026-08-22T09:20:00+00:00"


def test_bundle_identity_is_source_observation_not_collection_cycle(tmp_path: Path):
    database_path = tmp_path / "evidence.sqlite"
    base = {
        "as_of_timestamp": "2026-08-22T09:21:00+00:00",
        "underlying_bar_close_timestamp": "2026-08-22T09:20:00+00:00",
        "futures_bar_close_timestamp": "2026-08-22T09:20:00+00:00",
        "option_timestamp": "2026-08-22T09:20:30+00:00",
        "observed_direction": "BULLISH",
        "blocking_reasons": [],
        "caution_reasons": [],
    }
    first_id = persist_market_evidence_bundle(
        database_path,
        underlying_name="NIFTY 50",
        view={**base, "futures_collection_timestamp": "2026-08-22T09:21:00+00:00"},
    )
    second_id = persist_market_evidence_bundle(
        database_path,
        underlying_name="NIFTY 50",
        view={
            **base,
            "as_of_timestamp": "2026-08-22T09:22:00+00:00",
            "futures_collection_timestamp": "2026-08-22T09:22:00+00:00",
        },
    )

    latest = read_latest_market_evidence_bundle(
        database_path,
        underlying_name="NIFTY 50",
    )

    assert first_id == second_id
    assert latest is not None
    assert latest["as_of_timestamp"] == "2026-08-22T09:22:00+00:00"
    assert latest["futures_collection_timestamp"] == "2026-08-22T09:22:00+00:00"
