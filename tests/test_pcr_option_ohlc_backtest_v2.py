import csv
import json
from pathlib import Path

from market_lab.pcr_option_ohlc_backtest_v2 import analyze


def test_backtest_uses_t0_instrument_not_confirmation_atm(tmp_path: Path):
    methodology = tmp_path / "m.json"
    methodology.write_text(json.dumps({
        "status":"AVAILABLE","methodology_version":"PCR_RESEARCH_METHODOLOGY_V2","profile":"FROZEN_D5_D15",
        "leakage_guard":{"current_holdout_validation_input_used":False,"panel_any_confirmation_allowed":False},
        "directions":{"bearish":{"events":[{
            "session_date":"2026-01-01","timestamp":"2026-01-01T10:00:00","outcome":"TRUE_BEARISH_REVERSAL",
            "confidence_profile":"FROZEN_D5_D15","confidence_tier":"HIGH","confirmation_status":"CONFIRMED",
            "first_confirmation_offset_minutes":1,"t0_atm_strike":"100","t0_pe_instrument_key":"PE100"
        }]},"bullish":{"events":[]}}
    }), encoding="utf-8")
    ohlc = tmp_path / "o.csv"
    fields=["session_date","instrument_key","timestamp","open","high","low","close"]
    with ohlc.open("w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=fields); w.writeheader()
        # confirmation at 10:01 => entry at 10:02 on exact T0 PE100
        for minute in range(2,18):
            w.writerow(dict(session_date="2026-01-01",instrument_key="PE100",timestamp=f"2026-01-01T10:{minute:02d}:00",open="100",high="106",low="99",close="105"))
    result=analyze(methodology,ohlc)
    trade=result["trades"][0]
    assert trade["instrument_key"]=="PE100"
    assert trade["entry_premium"]==100.0
    assert trade["contract_selection_rule"]=="EXACT_T0_ATM_INSTRUMENT_NO_SUBSTITUTION"
