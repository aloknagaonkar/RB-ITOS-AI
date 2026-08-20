from datetime import datetime

import pandas as pd

from red_bar_lab.options.context import summarize_option_chain


def _chain():
    return pd.DataFrame([
        {
            "expiry": "2026-08-13",
            "spot": 100.0,
            "strike": 95.0,
            "call_oi": 100.0,
            "put_oi": 500.0,
            "call_oi_change": 10.0,
            "put_oi_change": 50.0,
            "call_iv": 12.0,
            "put_iv": 14.0,
            "call_delta": 0.80,
            "put_delta": -0.20,
            "call_gamma": 0.01,
            "put_gamma": 0.01,
            "call_theta": -1.0,
            "put_theta": -1.2,
            "call_vega": 3.0,
            "put_vega": 3.2,
        },
        {
            "expiry": "2026-08-13",
            "spot": 100.0,
            "strike": 100.0,
            "call_oi": 1000.0,
            "put_oi": 900.0,
            "call_oi_change": 100.0,
            "put_oi_change": 120.0,
            "call_iv": 15.0,
            "put_iv": 16.0,
            "call_delta": 0.50,
            "put_delta": -0.50,
            "call_gamma": 0.02,
            "put_gamma": 0.02,
            "call_theta": -2.0,
            "put_theta": -2.2,
            "call_vega": 4.0,
            "put_vega": 4.1,
        },
        {
            "expiry": "2026-08-13",
            "spot": 100.0,
            "strike": 105.0,
            "call_oi": 600.0,
            "put_oi": 100.0,
            "call_oi_change": 60.0,
            "put_oi_change": 5.0,
            "call_iv": 13.0,
            "put_iv": 15.0,
            "call_delta": 0.20,
            "put_delta": -0.80,
            "call_gamma": 0.01,
            "put_gamma": 0.01,
            "call_theta": -1.1,
            "put_theta": -1.3,
            "call_vega": 3.1,
            "put_vega": 3.3,
        },
    ])


def _signal():
    return {
        "signal_id": "RB-OPT",
        "trading_date": "2026-08-07",
        "confirmation_timestamp": "2026-08-07T10:00:00+05:30",
    }


def test_option_context_summary_computes_oi_pcr_atm_and_greeks():
    row = summarize_option_chain(
        signal=_signal(),
        instrument_key="NSE_INDEX|Nifty 50",
        expiry="2026-08-13",
        chain=_chain(),
        snapshot_timestamp=datetime.fromisoformat(
            "2026-08-07T10:01:00+05:30"
        ),
        alignment_tolerance_seconds=120,
    )

    assert row["entry_aligned"] == 1
    assert row["atm_strike"] == 100.0
    assert row["total_call_oi"] == 1700.0
    assert row["total_put_oi"] == 1500.0
    assert round(row["pcr_oi"], 4) == round(1500 / 1700, 4)
    assert row["call_wall_strike"] == 100.0
    assert row["put_wall_strike"] == 100.0
    assert row["atm_call_delta"] == 0.50
    assert row["atm_put_delta"] == -0.50
    assert row["max_pain_strike"] in {95.0, 100.0, 105.0}


def test_late_option_snapshot_is_not_entry_aligned():
    row = summarize_option_chain(
        signal=_signal(),
        instrument_key="NSE_INDEX|Nifty 50",
        expiry="2026-08-13",
        chain=_chain(),
        snapshot_timestamp=datetime.fromisoformat(
            "2026-08-07T10:10:00+05:30"
        ),
        alignment_tolerance_seconds=120,
    )
    assert row["entry_aligned"] == 0
    assert row["option_snapshot_delay_seconds"] == 600.0


def test_option_context_uses_confirmation_date_when_signal_date_missing():
    signal = _signal()
    signal["trading_date"] = None

    row = summarize_option_chain(
        signal=signal,
        instrument_key="NSE_INDEX|Nifty 50",
        expiry="2026-08-13",
        chain=_chain(),
        snapshot_timestamp=datetime.fromisoformat(
            "2026-08-07T10:01:00+05:30"
        ),
    )

    assert row["trading_date"] == "2026-08-07"
