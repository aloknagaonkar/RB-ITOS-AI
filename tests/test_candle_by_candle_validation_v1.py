
from market_lab.candle_by_candle_validation_v1 import build_rows

def test_candle_row_preserves_both_oi_views():
    audit = {
        "model": "OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1",
        "session_date": "2026-08-25",
        "research_strike_count": 11,
        "rows": [{
            "timestamp": "2026-08-25T10:45:00+05:30",
            "status": "PASS",
            "spot": 24138.1,
            "moving_atm": 24150.0,
            "moving_strikes": "23900,...,24400",
            "ce_delta_5m": -100,
            "pe_delta_5m": 300,
            "imbalance_5m": 400,
            "imbalance_10m": 700,
            "imbalance_15m": 900,
            "pcr_current": 0.71,
            "pcr_previous_same_strikes_5m": 0.69,
            "pcr_change_5m": 0.02,
            "pcr_previous_same_strikes_10m": 0.68,
            "pcr_change_10m": 0.03,
            "pcr_previous_same_strikes_15m": 0.67,
            "pcr_change_15m": 0.04,
            "morning_fixed_atm": 24200.0,
            "fixed_strikes": "23950,...,24450",
            "ce_session_delta": 1000,
            "pe_session_delta": 1500,
            "session_imbalance": 500,
            "session_pcr_baseline_0920": 0.90,
            "session_pcr_current": 0.95,
            "session_pcr_change_0920_to_now": 0.05,
            "futures_close": 24149.1,
            "futures_price_change_5m": 4.1,
            "futures_price_change_10m": 5.0,
            "futures_price_change_15m": 6.0,
            "futures_oi": 1_000_000,
            "futures_oi_change_5m": 10000,
            "futures_oi_status": "LONG_BUILDUP",
            "futures_oi_direction": "BULLISH",
            "bullish_oi_status_streak": 1,
            "bearish_oi_status_streak": 0,
            "vwap": 24168.7,
            "vwap_distance": -19.6,
            "vwap_side": "BELOW",
            "strategy_events": "",
        }]
    }
    rows = build_rows(audit)
    assert rows[0]["recent_imbalance_5m"] == 400
    assert rows[0]["session_imbalance_0920_to_now"] == 500
    assert rows[0]["moving_atm"] == 24150.0
    assert rows[0]["fixed_0920_atm"] == 24200.0
    assert rows[0]["pcr_5m_ago_same_strikes"] == 0.69
    assert rows[0]["pcr_10m_ago_same_strikes"] == 0.68
    assert rows[0]["pcr_15m_ago_same_strikes"] == 0.67
    assert rows[0]["session_pcr_0920"] == 0.90
    assert rows[0]["session_pcr_now"] == 0.95
    assert rows[0]["session_pcr_change_0920_to_now"] == 0.05
    assert "09:20=0.9000" in rows[0]["session_pcr_summary"]
    assert "NOW=0.9500" in rows[0]["session_pcr_summary"]
    assert "Δ=0.0500" in rows[0]["session_pcr_summary"]
