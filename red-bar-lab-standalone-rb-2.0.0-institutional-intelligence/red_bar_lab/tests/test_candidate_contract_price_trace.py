from __future__ import annotations

import pandas as pd

from red_bar_lab.services.candidate_contract_price_trace import (
    build_all_candidate_contract_price_trace,
)


class FakeMarket:
    def nfo_options(self, *, underlying_name, as_of):
        return pd.DataFrame([
            {"tradingsymbol": "NIFTY24300PE", "instrument_token": 101, "instrument_type": "PE", "strike": 24300, "expiry": as_of},
            {"tradingsymbol": "NIFTY24250PE", "instrument_token": 102, "instrument_type": "PE", "strike": 24250, "expiry": as_of},
        ])

    def historical_candles(self, *, instrument_token, interval, date_from, date_to, include_oi):
        base = 100.0 if instrument_token == 101 else 80.0
        return pd.DataFrame([
            {"timestamp": "2026-08-12T09:40:00+05:30", "close": base},
            {"timestamp": "2026-08-12T10:00:00+05:30", "close": base + 20.0},
            {"timestamp": "2026-08-12T10:30:00+05:30", "close": base + 35.0},
        ])


def test_traces_every_candidate_and_keeps_same_contract():
    signal = {
        "signal_id": "SIG1",
        "confirmation_timestamp": "2026-08-12T09:40:00+05:30",
        "direction": "BEARISH",
    }
    scan_rows = [
        {"scan_id": "SCAN1", "signal_id": "SIG1", "candidate_symbol": "NIFTY24300PE", "evaluated_at": "2026-08-12T10:30:00+05:30", "reward_remaining_pct": 0, "move_consumed_pct": 100, "decision": "SKIP", "reason": "REWARD_CONSUMED"},
        {"scan_id": "SCAN1", "signal_id": "SIG1", "candidate_symbol": "NIFTY24250PE", "evaluated_at": "2026-08-12T10:30:00+05:30", "reward_remaining_pct": 0, "move_consumed_pct": 100, "decision": "SKIP", "reason": "REWARD_CONSUMED"},
    ]
    all_rows = [
        {**scan_rows[0], "evaluated_at": "2026-08-12T10:00:00+05:30"},
        {**scan_rows[1], "evaluated_at": "2026-08-12T10:00:00+05:30"},
        *scan_rows,
    ]
    rows = build_all_candidate_contract_price_trace(
        market=FakeMarket(),
        underlying_name="NIFTY 50",
        trading_date="2026-08-12",
        signal=signal,
        scan_rows=scan_rows,
        all_day_rows=all_rows,
    )
    assert len(rows) == 2
    by_symbol = {row["candidate_symbol"]: row for row in rows}
    assert by_symbol["NIFTY24300PE"]["signal_price"] == 100.0
    assert by_symbol["NIFTY24300PE"]["first_consumed_price"] == 120.0
    assert by_symbol["NIFTY24300PE"]["evaluation_price"] == 135.0
    assert by_symbol["NIFTY24300PE"]["signal_to_consumed_change_pct"] == 20.0
    assert by_symbol["NIFTY24250PE"]["signal_price"] == 80.0
    assert by_symbol["NIFTY24250PE"]["evaluation_price"] == 115.0


def test_unresolved_contract_is_reported_without_breaking_other_candidates():
    signal = {"signal_id": "SIG1", "confirmation_timestamp": "2026-08-12T09:40:00+05:30"}
    rows = build_all_candidate_contract_price_trace(
        market=FakeMarket(),
        underlying_name="NIFTY 50",
        trading_date="2026-08-12",
        signal=signal,
        scan_rows=[{"signal_id": "SIG1", "candidate_symbol": "UNKNOWN", "evaluated_at": "2026-08-12T10:30:00+05:30"}],
        all_day_rows=[],
    )
    assert rows[0]["status"] == "CONTRACT_NOT_RESOLVED"
