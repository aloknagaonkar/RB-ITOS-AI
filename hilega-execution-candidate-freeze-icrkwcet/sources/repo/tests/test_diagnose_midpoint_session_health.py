from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.diagnose_midpoint_session_health import analyse, unique_entries


IST = ZoneInfo("Asia/Kolkata")


def event(kind, minute, *, price=100.0, direction="BEARISH", family="B"):
    return {
        "event_id": f"{kind}-{minute}",
        "session_date": "2026-09-30",
        "event_timestamp": f"2026-09-30T{minute}:00+05:30",
        "event_type": kind,
        "direction": direction,
        "family": family,
        "underlying_price": price,
        "evidence": {},
    }


def market():
    first = datetime(2026, 9, 30, 9, 15, tzinfo=IST)
    rows = []
    pv = volume = 0.0
    for offset in range(360):
        timestamp = first + timedelta(minutes=offset)
        close = 120.0 - 0.5 * offset
        future = close + 20.0
        minute_volume = 1000.0 + offset
        pv += future * minute_volume
        volume += minute_volume
        rows.append(
            {
                "timestamp": timestamp,
                "underlying_open": close + 0.2,
                "underlying_high": close + 0.5,
                "underlying_low": close - 0.5,
                "underlying_close": close,
                "futures_open": future + 0.2,
                "futures_high": future + 0.5,
                "futures_low": future - 0.5,
                "futures_close": future,
                "futures_volume": minute_volume,
                "futures_vwap": pv / volume,
            }
        )
    return rows


def test_unique_entries_collapses_c_and_rearm_aliases():
    rows = [
        event("C_ENTRY", "09:49", price=103.0, family="C"),
        event("B_REARM_ENTRY", "09:49", price=103.0, family="B"),
    ]
    result = unique_entries(rows)
    assert len(result) == 1
    assert result[0]["entry_aliases"] == ["B_REARM_ENTRY", "C_ENTRY"]


def test_analysis_is_sequential_and_reports_all_health_checkpoints():
    events = [
        event("B_ENTRY", "09:49", price=103.0),
        event("STRUCTURAL_TERMINAL", "10:05", price=95.0),
    ]
    result = analyse(date(2026, 9, 30), events, market())
    assert len(result) == 1
    trade = result[0]
    assert set(trade["checkpoints"]) == {"PREENTRY", "ENTRY", "T3", "T5"}
    assert trade["checkpoints"]["ENTRY"]["warmup_bars"] == 35
    assert trade["checkpoints"]["T5"]["warmup_bars"] == 40
    assert trade["interpretation"] == "INITIAL_RISK_RESEARCH_CANDIDATE"
    assert trade["actual_exit_points"] == 8.0


def test_proved_trade_is_never_described_as_entry_avoidance():
    proof = event("PLUS20_PROOF", "09:55", price=97.0)
    events = [event("B_ENTRY", "09:49", price=103.0), proof]
    result = analyse(date(2026, 9, 30), events, market())
    assert result[0]["interpretation"] == "MANAGE_PROVED_TRADE_NOT_ENTRY_AVOIDANCE"
