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
        "2026-09-18", dt(10,0), "BULLISH_ALL_3", 25000.0
    )
    oid = adapter.on_new_all3(c1, "BEARISH_ALL_3")
    assert oid

    oid2 = adapter.on_new_all3(c1, "BEARISH_ALL_3")
    assert oid2 == oid
    assert len([
        x for x in adapter.store.read_all()
        if x["event_type"] == "OBSERVATION_DETECTED"
    ]) == 1

    c2 = CompletedFiveMinuteCheckpoint(
        "2026-09-18", dt(10,5), "BULLISH_ALL_3", 24995.0, "LONG_BUILDUP"
    )
    assert adapter.on_candle2(oid, c2) == "CLASSIFIED"
    assert adapter.states()[oid].price_lag_class == "SPOT_LAG"

    assert adapter.on_exact_option_resolved(
        oid,
        ExactOptionResolution(dt(10,5), 25000.0, "NSE_FO|CE25000"),
    ) == "OPTION_RESOLVED"

    assert adapter.on_exact_next_minute_open(
        oid,
        ExactNextMinuteOpen(dt(10,6), 100.0),
    ) == "OPEN"

    adapter.on_option_minute(
        oid, CompletedOptionMinute(dt(10,7), 100,106,99,105)
    )
    assert adapter.states()[oid].status == "BE_ARMED"

    adapter.on_option_minute(
        oid, CompletedOptionMinute(dt(10,8), 104,105,99,100)
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
            "2026-09-18", dt(11,0), "BEARISH_ALL_3", 25000.0
        ),
        "BULLISH_ALL_3",
    )
    c2 = CompletedFiveMinuteCheckpoint(
        "2026-09-18", dt(11,5), "BEARISH_ALL_3", 24990.0, "LONG_BUILDUP"
    )
    assert adapter.on_candle2(oid, c2) == "REJECTED"
    assert adapter.states()[oid].rejection_reason == "FUTURES_MISALIGNED"


def test_missing_futures_is_incomplete(tmp_path: Path):
    adapter = LiveShadowRuntimeAdapterV1(tmp_path / "events.jsonl")
    oid = adapter.on_new_all3(
        CompletedFiveMinuteCheckpoint(
            "2026-09-18", dt(12,0), "BULLISH_ALL_3", 25000.0
        ),
        "BEARISH_ALL_3",
    )
    c2 = CompletedFiveMinuteCheckpoint(
        "2026-09-18", dt(12,5), "BULLISH_ALL_3", 25001.0, None
    )
    assert adapter.on_candle2(oid, c2) == "INCOMPLETE"
    assert adapter.states()[oid].status == "INCOMPLETE"
