from datetime import datetime, timezone

import pandas as pd

from red_bar_lab.services.market_evidence_engine import (
    build_underlying_evidence,
    corrected_option_summary,
    score_slope,
)


def _row(side, rank, strike, atm=100.0, score_state="FRESH_BUYING", bid=99.5, ask=100.5):
    return {
        "option_type": side,
        "distance_rank": rank,
        "strike": strike,
        "atm_strike": atm,
        "current_price": 100.0,
        "bid": bid,
        "ask": ask,
        "volume": 1000.0,
        "oi": 5000.0,
        "oi_change_pct": 10.0,
        "participation_state": score_state,
        "vwap": 95.0,
        "option_rsi": 60.0,
        "delta": 0.5 if side == "CE" else -0.5,
    }


def test_corrected_option_summary_uses_symmetric_absolute_distance_weights():
    rows = [
        _row("CE", 1, 100.0),
        _row("CE", 2, 50.0),
        _row("CE", 3, 150.0),
        _row("PE", 1, 100.0, score_state="NEUTRAL"),
        _row("PE", 2, 50.0, score_state="NEUTRAL"),
        _row("PE", 3, 150.0, score_state="NEUTRAL"),
    ]
    result = corrected_option_summary(rows)
    ce = [row for row in result["rows"] if row["option_type"] == "CE"]
    assert ce[0]["distance_weight"] == 1.0
    assert ce[1]["distance_weight"] == 0.9
    assert ce[2]["distance_weight"] == 0.9
    assert result["ce_score"] > result["pe_score"]


def test_corrected_option_summary_requires_two_sided_quote():
    result = corrected_option_summary([
        _row("CE", 1, 100.0, bid=None, ask=None),
        _row("PE", 1, 100.0),
    ])
    assert result["eligible_ce"] == 0
    assert result["rows"][0]["contract_eligibility"] == "QUOTE_UNAVAILABLE"


def test_corrected_option_summary_uses_midpoint_spread():
    result = corrected_option_summary([
        _row("CE", 1, 100.0, bid=90.0, ask=110.0),
        _row("PE", 1, 100.0),
    ])
    assert result["eligible_ce"] == 0
    assert result["rows"][0]["contract_eligibility"] == "WIDE_SPREAD"


def test_score_slope_is_per_elapsed_minute():
    history = [
        {"ce_score": 42.0, "observed_at": "2026-08-21T06:00:00+00:00"},
        {"ce_score": 50.0, "observed_at": "2026-08-21T06:02:00+00:00"},
        {"ce_score": 58.0, "observed_at": "2026-08-21T06:04:00+00:00"},
    ]
    assert score_slope(history, "CE") == 4.0


def _minute_frame(periods=55):
    timestamps = pd.date_range("2026-08-21 03:45:00+00:00", periods=periods, freq="1min")
    closes = [100.0] * periods
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [value - 0.05 for value in closes],
            "high": [value + 0.10 for value in closes],
            "low": [value - 0.10 for value in closes],
            "close": closes,
            "volume": [100] * periods,
        }
    )


def test_underlying_evidence_excludes_forming_five_minute_bucket():
    frame = _minute_frame()
    # Forming 04:35 bucket contains a large spike, but as-of 04:37 it is incomplete.
    frame.loc[frame["timestamp"] >= pd.Timestamp("2026-08-21 04:35:00+00:00"), ["open", "high", "low", "close"]] = [100.0, 110.0, 99.0, 109.0]
    evidence = build_underlying_evidence(
        frame,
        as_of_timestamp=datetime(2026, 8, 21, 4, 37, tzinfo=timezone.utc),
    )
    assert evidence["observed_at"].startswith("2026-08-21T04:30:00")
    assert evidence["state"] != "BULLISH_STRUCTURE"


def test_underlying_confirmed_structure_requires_next_completed_hold():
    timestamps = pd.date_range("2026-08-21 03:45:00+00:00", periods=65, freq="1min")
    closes = [100.0] * 50 + [102.0] * 5 + [102.2] * 5 + [102.3] * 5
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [value - 0.4 if index >= 50 else value - 0.05 for index, value in enumerate(closes)],
            "high": [value + 0.1 for value in closes],
            "low": [value - 0.1 for value in closes],
            "close": closes,
            "volume": [100] * len(closes),
        }
    )
    evidence = build_underlying_evidence(
        frame,
        as_of_timestamp=datetime(2026, 8, 21, 4, 50, tzinfo=timezone.utc),
    )
    assert evidence["direction"] == "BULLISH"
    assert evidence["acceptance_state"] in {"HOLD_CONFIRMED", "HOLD_PENDING"}
