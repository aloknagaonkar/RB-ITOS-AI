from datetime import datetime, timezone
from types import SimpleNamespace

from red_bar_lab.services.nifty_futures_snapshot_store import (
    persist_nifty_futures_snapshot,
    read_nifty_futures_snapshots,
)


def test_persist_and_read_futures_snapshot(tmp_path):
    database_path = tmp_path / "red_bar.db"
    observed_at = datetime(2026, 8, 20, 10, 1, tzinfo=timezone.utc)

    persist_nifty_futures_snapshot(
        database_path,
        observed_at=observed_at,
        underlying_name="NIFTY 50",
        contract=SimpleNamespace(
            status="READY",
            instrument_key="NSE_FO|58072",
            trading_symbol="NIFTY FUT",
            expiry="2026-08-25",
        ),
        market=SimpleNamespace(
            status="READY",
            latest_close=24290.5,
            latest_volume=7475.0,
            latest_oi=11992825.0,
            latest_timestamp="2026-08-20T15:29:00+05:30",
        ),
        positioning=SimpleNamespace(
            status="READY",
            state="LONG_BUILDUP",
            price_change=0.8,
            price_change_pct=0.0033,
            oi_change=1040.0,
            oi_change_pct=0.0087,
            relative_volume=0.8191,
            baseline_volume=9126.0,
            baseline_samples=20,
        ),
        strength=SimpleNamespace(status="READY", strength="WEAK"),
        readiness=SimpleNamespace(
            status="READY",
            candle_status="MARKET_CLOSED",
            volume_status="APPLICABLE",
            oi_status="READY",
            blocking_reasons=(),
            advisory_reasons=("CANDLE_MARKET_CLOSED",),
        ),
    )

    rows = read_nifty_futures_snapshots(database_path)

    assert len(rows) == 1
    assert rows[0]["instrument_key"] == "NSE_FO|58072"
    assert rows[0]["positioning_state"] == "LONG_BUILDUP"
    assert rows[0]["strength"] == "WEAK"
    assert rows[0]["readiness_status"] == "READY"
    assert rows[0]["authority"] == "OBSERVATIONAL_ONLY"
    assert rows[0]["blocking_reasons"] == []
    assert rows[0]["advisory_reasons"] == ["CANDLE_MARKET_CLOSED"]


def test_read_returns_empty_when_database_does_not_exist(tmp_path):
    assert read_nifty_futures_snapshots(tmp_path / "missing.db") == []


def test_same_observation_is_idempotent(tmp_path):
    database_path = tmp_path / "red_bar.db"
    common = dict(
        observed_at="2026-08-20T10:00:00+05:30",
        underlying_name="NIFTY 50",
        contract=SimpleNamespace(status="READY"),
        market=SimpleNamespace(status="READY"),
        positioning=SimpleNamespace(status="READY", state="NEUTRAL"),
        strength=SimpleNamespace(status="READY", strength="WEAK"),
        readiness=SimpleNamespace(
            status="DEGRADED",
            candle_status="STALE",
            volume_status="MISSING",
            oi_status="MISSING",
            blocking_reasons=("CANDLE_STALE",),
            advisory_reasons=(),
        ),
    )

    persist_nifty_futures_snapshot(database_path, **common)
    persist_nifty_futures_snapshot(database_path, **common)

    assert len(read_nifty_futures_snapshots(database_path)) == 1
