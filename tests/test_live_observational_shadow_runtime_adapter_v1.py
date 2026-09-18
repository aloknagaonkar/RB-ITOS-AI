from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_lab.live_observational_shadow_runtime_adapter_v1 import (
    CompletedFiveMinuteCheckpoint,
    CompletedOptionMinute,
    ExactNextMinuteOpen,
    ExactOptionResolution,
    LiveShadowRuntimeAdapterV1,
)

IST = ZoneInfo("Asia/Kolkata")


def dt(h, m):
    return datetime(2026, 9, 18, h, m, tzinfo=IST)


def test_full_runtime_adapter_flow(tmp_path: Path):
    adapter = LiveShadowRuntimeAdapterV1(tmp_path / "events.jsonl")

    c1 = CompletedFiveMinuteCheckpoint(
        session_date="2026-09-18",
        timestamp=dt(10, 0),
        all3_state="BULLISH_ALL_3",
        spot=25000.0,
    )
    oid = adapter.on_new_all3(c1, previous_directional_all3="BEARISH_ALL_3")
    assert oid

    # Duplicate input must not create duplicate observation.
    oid2 = adapter.on_new_all3(c1, previous_directional_all3="BEARISH_ALL_3")
    assert oid2 == oid
    assert len([x for x in adapter.store.read_all() if x["event_type"] == "OBSERVATION_DETECTED"]) == 1

    c2 = CompletedFiveMinuteCheckpoint(
        session_date="2026-09-18",
        timestamp=dt(10, 5),
        all3_state="BULLISH_ALL_3",
        spot=24995.0,
        futures_oi_state="LONG_BUILDUP",
    )
    assert adapter.on_candle2(oid, c2) == "CLASSIFIED"
    assert adapter.states()[oid].price_lag_class == "SPOT_LAG"

    assert adapter.on_exact_option_resolved(
        oid,
        ExactOptionResolution(
            timestamp=dt(10, 5),
            atm_strike=25000.0,
            option_instrument_key="NSE_FO|CE25000",
        ),
    ) == "OPTION_RESOLVED"

    assert adapter.on_exact_next_minute_open(
        oid,
        ExactNextMinuteOpen(timestamp=dt(10, 6), price=100.0),
    ) == "OPEN"

    # +6% high arms BE from next minute.
    adapter.on_option_minute(
        oid,
        CompletedOptionMinute(
            timestamp=dt(10, 7),
            open=100.0, high=106.0, low=99.0, close=105.0,
        ),
    )
    assert adapter.states()[oid].status == "BE_ARMED"

    # Next bar hits BE.
    adapter.on_option_minute(
        oid,
        CompletedOptionMinute(
            timestamp=dt(10, 8),
            open=104.0, high=105.0, low=99.0, close=100.0,
        ),
    )
    s = adapter.states()[oid]
    assert s.status == "CLOSED"
    assert s.exit_price == 100.0
    assert s.exit_reason == "STOP_TOUCH"
    assert round(s.net_return_pct, 6) == -0.5


def test_c2_misalignment_rejected(tmp_path: Path):
    adapter = LiveShadowRuntimeAdapterV1(tmp_path / "events.jsonl")
    oid = adapter.on_new_all3(
        CompletedFiveMinuteCheckpoint(
            session_date="2026-09-18",
            timestamp=dt(11, 0),
            all3_state="BEARISH_ALL_3",
            spot=25000.0,
        ),
        previous_directional_all3="BULLISH_ALL_3",
    )
    c2 = CompletedFiveMinuteCheckpoint(
        session_date="2026-09-18",
        timestamp=dt(11, 5),
        all3_state="BEARISH_ALL_3",
        spot=24990.0,
        futures_oi_state="LONG_BUILDUP",
    )
    assert adapter.on_candle2(oid, c2) == "REJECTED"
    assert adapter.states()[oid].rejection_reason == "FUTURES_MISALIGNED"


def test_missing_futures_is_incomplete(tmp_path: Path):
    adapter = LiveShadowRuntimeAdapterV1(tmp_path / "events.jsonl")
    oid = adapter.on_new_all3(
        CompletedFiveMinuteCheckpoint(
            session_date="2026-09-18",
            timestamp=dt(12, 0),
            all3_state="BULLISH_ALL_3",
            spot=25000.0,
        ),
        previous_directional_all3="BEARISH_ALL_3",
    )
    c2 = CompletedFiveMinuteCheckpoint(
        session_date="2026-09-18",
        timestamp=dt(12, 5),
        all3_state="BULLISH_ALL_3",
        spot=25001.0,
        futures_oi_state=None,
    )
    assert adapter.on_candle2(oid, c2) == "INCOMPLETE"
    assert adapter.states()[oid].status == "INCOMPLETE"
