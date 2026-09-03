from __future__ import annotations

import sqlite3

from red_bar_lab.storage.red_bar_v2_storage import (
    AdmissionDecision,
    DirectionEvent,
    IndicatorSnapshot,
    RedBarV2Storage,
    admission_decision_id,
    direction_event_id,
    indicator_snapshot_id,
)


def test_initialize_adds_only_red_bar_v2_tables(tmp_path):
    path = tmp_path / "red_bar.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE legacy_table(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO legacy_table(value) VALUES('keep-me')")
        conn.commit()

    storage = RedBarV2Storage(path)
    storage.initialize()
    storage.initialize()

    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        legacy_value = conn.execute("SELECT value FROM legacy_table").fetchone()[0]

    assert legacy_value == "keep-me"
    assert "market_indicator_snapshots" in tables
    assert "red_bar_v2_direction_events" in tables
    assert "candidate_admission_decisions" in tables


def test_indicator_snapshot_is_deterministic_and_idempotent(tmp_path):
    storage = RedBarV2Storage(tmp_path / "red_bar.db")
    snapshot = IndicatorSnapshot(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-20",
        timeframe="1M",
        candle_timestamp="2026-08-20T10:31:00+05:30",
        candle_open=24800.0,
        candle_high=24810.0,
        candle_low=24790.0,
        candle_close=24795.0,
        candle_volume=1000.0,
        rsi_period=14,
        rsi_value=43.2,
        vwap_value=24804.0,
        price_vs_vwap="BELOW",
        rsi_state="BEARISH",
        source="HISTORICAL_REPLAY",
    )

    first_id = storage.upsert_indicator_snapshot(snapshot)
    second_id = storage.upsert_indicator_snapshot(snapshot)
    row = storage.read_indicator_snapshot(first_id)

    assert first_id == second_id
    assert first_id == indicator_snapshot_id(
        snapshot.instrument_key,
        snapshot.timeframe,
        snapshot.candle_timestamp,
        snapshot.rsi_period,
    )
    assert row is not None
    assert row["rsi_value"] == 43.2
    assert row["vwap_value"] == 24804.0
    assert row["rsi_state"] == "BEARISH"


def test_direction_event_can_be_marked_consumed(tmp_path):
    storage = RedBarV2Storage(tmp_path / "red_bar.db")
    event = DirectionEvent(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-20",
        strategy_version="RED_BAR_V2",
        event_type="BULLISH_REVERSAL_DETECTED",
        direction="BULLISH",
        trend_strength="PROVISIONAL",
        reference_timestamp="2026-08-20T09:25:00+05:30",
        midpoint=24830.0,
        context_timeframe="5M",
        context_timestamp="2026-08-20T11:10:00+05:30",
        close_price=24818.0,
        rsi_value=57.3,
        vwap_value=24802.0,
        rsi_aligned=True,
        vwap_aligned=True,
        midpoint_aligned=False,
    )

    event_id = storage.upsert_direction_event(event)
    assert event_id == direction_event_id(
        event.instrument_key,
        event.strategy_version,
        event.event_type,
        event.direction,
        event.context_timestamp,
        event.reference_timestamp,
    )

    storage.mark_reversal_consumed(event_id)
    row = storage.read_direction_event(event_id)

    assert row is not None
    assert row["consumed"] == 1


def test_admission_decision_round_trip_preserves_conditions(tmp_path):
    storage = RedBarV2Storage(tmp_path / "red_bar.db")
    event = DirectionEvent(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-20",
        strategy_version="RED_BAR_V2",
        event_type="BULLISH_REVERSAL_DETECTED",
        direction="BULLISH",
        context_timeframe="5M",
        context_timestamp="2026-08-20T11:10:00+05:30",
        reference_timestamp="2026-08-20T09:25:00+05:30",
    )
    event_id = storage.upsert_direction_event(event)

    decision = AdmissionDecision(
        event_id=event_id,
        instrument_key=event.instrument_key,
        trading_date=event.trading_date,
        strategy_version=event.strategy_version,
        candidate_allowed=True,
        admission_code="REVERSAL_CONTEXT_ALIGNED_FLAT",
        admission_reason=(
            "Bullish RSI/VWAP reversal is aligned and no trade is active."
        ),
        direction="BULLISH",
        option_side="CE",
        entry_type="REVERSAL",
        trend_strength="PROVISIONAL",
        active_trade_count=0,
        previous_trade_status="CLOSED",
        rsi_aligned=True,
        vwap_aligned=True,
        midpoint_aligned=False,
        context_fresh=True,
        conditions={
            "rsi_aligned": True,
            "vwap_aligned": True,
            "midpoint_aligned": False,
        },
    )

    decision_id = storage.upsert_admission_decision(decision)
    row = storage.read_admission_decision(decision_id)

    assert decision_id == admission_decision_id(event_id, decision.admission_code)
    assert row is not None
    assert row["candidate_allowed"] == 1
    assert row["admission_code"] == "REVERSAL_CONTEXT_ALIGNED_FLAT"
    assert row["conditions"] == {
        "midpoint_aligned": False,
        "rsi_aligned": True,
        "vwap_aligned": True,
    }


def test_same_direction_event_does_not_duplicate(tmp_path):
    storage = RedBarV2Storage(tmp_path / "red_bar.db")
    event = DirectionEvent(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-08-20",
        strategy_version="RED_BAR_V2",
        event_type="INITIAL_BEARISH_ALIGNMENT",
        direction="BEARISH",
        context_timeframe="1M",
        context_timestamp="2026-08-20T10:31:00+05:30",
        reference_timestamp="2026-08-20T09:25:00+05:30",
    )

    first_id = storage.upsert_direction_event(event)
    second_id = storage.upsert_direction_event(event)

    with sqlite3.connect(storage.path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM red_bar_v2_direction_events WHERE event_id=?",
            (first_id,),
        ).fetchone()[0]

    assert first_id == second_id
    assert count == 1
