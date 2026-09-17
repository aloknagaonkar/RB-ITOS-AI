
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
            "ce_oi": 10_000,
            "pe_oi": 12_000,
            "ce_oi_previous_same_strikes_5m": 10_100,
            "pe_oi_previous_same_strikes_5m": 11_700,
            "ce_delta_5m": -100,
            "pe_delta_5m": 300,
            "imbalance_5m": 400,
            "ce_oi_previous_same_strikes_10m": 10_300,
            "pe_oi_previous_same_strikes_10m": 11_600,
            "ce_delta_10m": -300,
            "pe_delta_10m": 400,
            "imbalance_10m": 700,
            "ce_oi_previous_same_strikes_15m": 10_500,
            "pe_oi_previous_same_strikes_15m": 11_400,
            "ce_delta_15m": -500,
            "pe_delta_15m": 600,
            "imbalance_15m": 1100,
            "pcr_current": 0.71,
            "pcr_previous_same_strikes_5m": 0.69,
            "pcr_change_5m": 0.02,
            "pcr_previous_same_strikes_10m": 0.68,
            "pcr_change_10m": 0.03,
            "pcr_previous_same_strikes_15m": 0.67,
            "pcr_change_15m": 0.04,
            "morning_fixed_atm": 24200.0,
            "fixed_strikes": "23950,...,24450",
            "fixed_ce_oi_baseline_0920": 20_000,
            "fixed_pe_oi_baseline_0920": 18_000,
            "fixed_ce_oi": 21_000,
            "fixed_pe_oi": 19_500,
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
    assert rows[0]["current_ce_oi"] == 10_000
    assert rows[0]["current_pe_oi"] == 12_000
    assert rows[0]["ce_oi_5m_ago_same_strikes"] == 10_100
    assert rows[0]["pe_oi_10m_ago_same_strikes"] == 11_600
    assert rows[0]["ce_oi_15m_ago_same_strikes"] == 10_500
    assert rows[0]["recent_imbalance_5m"] == 400
    assert rows[0]["fixed_ce_oi_0920"] == 20_000
    assert rows[0]["fixed_pe_oi_0920"] == 18_000
    assert rows[0]["fixed_ce_oi_now"] == 21_000
    assert rows[0]["fixed_pe_oi_now"] == 19_500
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


def test_horizon_summary_contains_oi_and_pcr_before_and_now():
    audit = {
        "model": "OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1",
        "rows": [{
            "status": "PASS",
            "timestamp": "2026-08-25T10:45:00+05:30",
            "ce_oi": 110_000_000,
            "pe_oi": 120_000_000,
            "ce_oi_previous_same_strikes_5m": 100_000_000,
            "pe_oi_previous_same_strikes_5m": 105_000_000,
            "ce_delta_5m": 10_000_000,
            "pe_delta_5m": 15_000_000,
            "imbalance_5m": 5_000_000,
            "pcr_current": 1.09,
            "pcr_previous_same_strikes_5m": 1.05,
            "pcr_change_5m": 0.04,
            "fixed_ce_oi_baseline_0920": 90_000_000,
            "fixed_pe_oi_baseline_0920": 80_000_000,
            "fixed_ce_oi": 130_000_000,
            "fixed_pe_oi": 125_000_000,
            "ce_session_delta": 40_000_000,
            "pe_session_delta": 45_000_000,
            "session_imbalance": 5_000_000,
            "session_pcr_baseline_0920": 0.8889,
            "session_pcr_current": 0.9615,
            "session_pcr_change_0920_to_now": 0.0726,
        }]
    }
    row = build_rows(audit)[0]
    assert "REF CE=100.000M PE=105.000M" in row["oi_5m_summary"]
    assert "NOW CE=110.000M PE=120.000M" in row["oi_5m_summary"]
    assert "PCR REF=1.0500 NOW=1.0900 Δ=0.0400" in row["oi_5m_summary"]
    assert "09:20 CE=90.000M PE=80.000M" in row["session_full_summary"]
    assert "NOW CE=130.000M PE=125.000M" in row["session_full_summary"]
