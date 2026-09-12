import csv
import json
from pathlib import Path

from market_lab.pcr_research_methodology_v2 import _confirmation_timeline, _frozen_specs, _load_positioning


def test_frozen_specs_do_not_depend_on_holdout_validation():
    spec = {
        "bearish": {"frozen_train_buckets": [
            {"feature": "fixed_pcr_change_5m", "train_cut_points": [-3, -2, -1]},
            {"feature": "fixed_pcr_change_15m", "train_cut_points": [-6, -4, -2]},
        ]},
        "bullish": {"frozen_train_buckets": [
            {"feature": "fixed_pcr_change_5m", "train_cut_points": [1, 2, 3]},
            {"feature": "fixed_pcr_change_15m", "train_cut_points": [2, 4, 6]},
        ]},
    }
    rows = _frozen_specs(spec, "BEARISH", "FROZEN_D5_D15")
    assert [r["feature"] for r in rows] == ["fixed_pcr_change_5m", "fixed_pcr_change_15m"]
    assert rows[0]["expected_monotonic"] == "INCREASING"


def test_confirmation_uses_only_frozen_t0_atm_strike(tmp_path: Path):
    p = tmp_path / "pos.csv"
    fields = ["session_date","timestamp","strike","strike_offset","combined_5m","ce_5m_state","pe_5m_state","ce_instrument_key","pe_instrument_key"]
    with p.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=fields); w.writeheader()
        # T0 ATM = 100. Another strike is already strongly bearish.
        w.writerow(dict(session_date="2026-01-01",timestamp="2026-01-01T10:00:00",strike="100",strike_offset="0",combined_5m="MIXED",ce_5m_state="NEUTRAL",pe_5m_state="NEUTRAL",ce_instrument_key="CE100",pe_instrument_key="PE100"))
        w.writerow(dict(session_date="2026-01-01",timestamp="2026-01-01T10:00:00",strike="150",strike_offset="1",combined_5m="STRONG_BEARISH",ce_5m_state="SHORT_BUILDUP",pe_5m_state="LONG_BUILDUP",ce_instrument_key="CE150",pe_instrument_key="PE150"))
        # T+1 same frozen strike becomes strongly bearish.
        w.writerow(dict(session_date="2026-01-01",timestamp="2026-01-01T10:01:00",strike="100.0",strike_offset="-1",combined_5m="STRONG_BEARISH",ce_5m_state="SHORT_BUILDUP",pe_5m_state="LONG_BUILDUP",ce_instrument_key="CE100",pe_instrument_key="PE100"))
        # Supply remaining offsets for completeness.
        for m in range(2,6):
            w.writerow(dict(session_date="2026-01-01",timestamp=f"2026-01-01T10:0{m}:00",strike="100",strike_offset="-1",combined_5m="MIXED",ce_5m_state="NEUTRAL",pe_5m_state="NEUTRAL",ce_instrument_key="CE100",pe_instrument_key="PE100"))
    by_time, by_strike = _load_positioning(p)
    atm = [r for r in by_time[("2026-01-01", __import__('datetime').datetime.fromisoformat("2026-01-01T10:00:00"))] if r["strike_offset_int"] == 0][0]
    first, status, timeline = _confirmation_timeline(by_strike, session="2026-01-01", t0=__import__('datetime').datetime.fromisoformat("2026-01-01T10:00:00"), t0_atm=atm, direction="BEARISH")
    assert status == "CONFIRMED"
    assert first == 1  # panel-any would incorrectly return T0
    assert timeline[0]["confirmed"] is False
    assert timeline[1]["confirmed"] is True
