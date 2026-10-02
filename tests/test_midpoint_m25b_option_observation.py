from datetime import date, datetime, timedelta

from market_lab.live_option_minute_source_v1 import CompletedOptionMinute
from market_lab.midpoint_strategy.option_observation import create_tape, project_tape


def test_bearish_exact_pe_and_no_future_leakage():
    day = "2026-09-29"
    entry = {"event_type": "E_ENTRY", "event_id": "entry", "session_date": day,
             "event_timestamp": day + "T09:26:00+05:30", "underlying_price": 22652.4,
             "direction": "BEARISH"}
    terminal = {"event_type": "STRUCTURAL_TERMINAL", "event_id": "exit",
                "event_timestamp": day + "T11:13:00+05:30"}
    contracts = [{"expiry": day, "strike_price": strike, "instrument_type": "PE",
                  "instrument_key": f"PE:{strike}"}
                 for strike in (22550, 22600, 22650, 22700, 22750)]
    def minutes(key):
        start = datetime.fromisoformat(day + "T09:27:00+05:30")
        end = datetime.fromisoformat(day + "T11:14:00+05:30")
        rows = []
        t = start
        while t <= end:
            n = int((t-start).total_seconds()/60)
            p = 100 + n
            rows.append(CompletedOptionMinute(key, t, p, p+2, p-2, p+1))
            t += timedelta(minutes=1)
        return rows
    tape = create_tape(entry, terminal, expiry=date.fromisoformat(day),
                       contracts=contracts, option_minutes=minutes)
    assert len(tape["legs"]) == 5
    assert {x["side"] for x in tape["legs"]} == {"PE"}
    before = project_tape(tape, day + "T09:26:00+05:30")
    assert before["status"] == "ENTRY_PENDING" and before["legs"] == []
    interim = project_tape(tape, day + "T10:00:00+05:30")
    assert interim["status"] == "AVAILABLE"
    assert interim["exit_boundary"] is None
    assert interim["legs"][0]["latest_timestamp"] == day + "T09:59:00+05:30"
    assert interim["legs"][0]["latest_premium"] == 133
    assert interim["legs"][0]["status"] == "ACTIVE"
    pending = project_tape(tape, day + "T11:13:00+05:30")
    assert pending["legs"][0]["exit_premium"] is None
    closed = project_tape(tape, day + "T11:14:00+05:30")
    assert closed["legs"][0]["status"] == "CLOSED"
    assert closed["legs"][0]["exit_premium"] == 207


def test_missing_exact_contract_and_minute_remain_unavailable():
    day = "2026-09-29"
    entry = {"event_type": "B_ENTRY", "event_id": "bull", "session_date": day,
             "event_timestamp": day + "T09:26:00+05:30", "underlying_price": 22652.4,
             "direction": "BULLISH"}
    contracts = [{"expiry": day, "strike_price": 22650, "instrument_type": "CE",
                  "instrument_key": "CE:22650"}]
    tape = create_tape(entry, None, expiry=date.fromisoformat(day), contracts=contracts,
                       option_minutes=lambda key: [])
    result = project_tape(tape, day + "T09:30:00+05:30")
    assert result["status"] == "UNAVAILABLE"
    assert len(result["legs"]) == 1
    assert result["legs"][0]["entry_premium"] is None
    assert result["legs"][0]["issue"] == "EXACT_ENTRY_MINUTE_UNAVAILABLE"
