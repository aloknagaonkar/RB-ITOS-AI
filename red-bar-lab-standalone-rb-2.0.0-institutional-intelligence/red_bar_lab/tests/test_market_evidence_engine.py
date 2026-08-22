import pandas as pd

from red_bar_lab.services.market_evidence_engine import (
    build_underlying_evidence,
    corrected_option_summary,
    score_slope,
)


def _row(side, rank, score_state="FRESH_BUYING", spread=1.0):
    return {
        "option_type": side,
        "distance_rank": rank,
        "current_price": 100.0,
        "bid": 99.5,
        "ask": 100.5,
        "spread": spread,
        "volume": 1000.0,
        "oi": 5000.0,
        "iv": 18.0,
        "oi_change_pct": 10.0,
        "participation_state": score_state,
        "vwap": 95.0,
        "option_rsi": 60.0,
        "delta": 0.5 if side == "CE" else -0.5,
    }


def test_corrected_option_summary_uses_distance_not_volume_weighting():
    rows = [_row("CE", 1), _row("CE", 5), _row("PE", 1, "NEUTRAL"), _row("PE", 5, "NEUTRAL")]
    result = corrected_option_summary(rows)
    assert result["ce_score"] > result["pe_score"]
    assert result["eligible_ce"] == 2
    assert result["eligible_pe"] == 2
    assert result["rows"][0]["distance_weight"] == 1.0


def test_corrected_option_summary_rejects_wide_spread():
    result = corrected_option_summary([_row("CE", 1, spread=5.0), _row("PE", 1)])
    assert result["eligible_ce"] == 0
    assert result["rejected"] == 1


def test_score_slope_uses_multiple_snapshots():
    history = [
        {"ce_score": 42.0, "observed_at": "2026-08-21T10:00:00+05:30"},
        {"ce_score": 50.0, "observed_at": "2026-08-21T10:01:00+05:30"},
        {"ce_score": 58.0, "observed_at": "2026-08-21T10:02:00+05:30"},
    ]
    assert score_slope(history, "CE") == 8.0


def test_underlying_evidence_detects_bullish_breakout():
    timestamps = pd.date_range("2026-08-21 03:45:00+00:00", periods=45, freq="1min")
    closes = [100.0 + index * 0.02 for index in range(40)] + [101.0, 101.4, 101.8, 102.2, 102.8]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [value - 0.1 for value in closes],
            "high": [value + 0.2 for value in closes],
            "low": [value - 0.2 for value in closes],
            "close": closes,
            "volume": [0] * len(closes),
        }
    )
    evidence = build_underlying_evidence(frame)
    assert evidence["direction"] in {"BULLISH", "NEUTRAL"}
    assert evidence["state"] != "UNAVAILABLE"


def test_underlying_excludes_forming_five_minute_candle():
    timestamps = pd.date_range("2026-08-21 03:45:00+00:00", periods=33, freq="1min")
    closes = [100.0] * 30 + [110.0, 111.0, 112.0]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [value - 0.1 for value in closes],
            "high": [value + 0.2 for value in closes],
            "low": [value - 0.2 for value in closes],
            "close": closes,
            "volume": [100] * len(closes),
        }
    )
    evidence = build_underlying_evidence(
        frame,
        as_of_timestamp=pd.Timestamp("2026-08-21 04:17:00+00:00").to_pydatetime(),
    )
    assert evidence["observed_at"] == "2026-08-21T04:10:00+00:00"


def test_underlying_confirmed_structure_requires_next_completed_hold():
    timestamps = pd.date_range("2026-08-21 03:45:00+00:00", periods=65, freq="1min")
    closes = [100.0] * 50 + [102.0] * 5 + [102.2] * 5 + [102.3] * 5
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [value - 0.4 if index >= 50 else value - 0.05 for index, value in enumerate(closes)],
            "high": [value + 0.1 for value in closes],
            # Keep the synthetic breakout candles internally valid: open must
            # lie between low and high. This creates a strong directional body
            # with the close in the upper part of the completed candle.
            "low": [value - 0.5 if index >= 50 else value - 0.1 for index, value in enumerate(closes)],
            "close": closes,
            "volume": [100] * len(closes),
        }
    )
    evidence = build_underlying_evidence(
        frame,
        as_of_timestamp=pd.Timestamp("2026-08-21 04:50:00+00:00").to_pydatetime(),
    )
    assert evidence["direction"] == "BULLISH"
    assert evidence["acceptance_state"] in {"HOLD_CONFIRMED", "HOLD_PENDING"}
