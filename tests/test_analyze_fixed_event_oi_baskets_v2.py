from datetime import date, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from market_lab.domain import IST

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_fixed_event_oi_baskets_v2.py"
spec = spec_from_file_location("analyze_fixed_event_oi_baskets_v2", SCRIPT)
mod = module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def series_for(key, values):
    base = datetime(2026, 9, 21, 10, 9, tzinfo=IST)
    return {base + timedelta(minutes=5*i): v for i, v in enumerate(values)}


def test_fixed_physical_basket_rolling_and_baseline_changes():
    # checkpoints 10:10,10:15,10:20. Exact source minutes 10:09,10:14,10:19.
    legs = [
        mod.Leg(23300.0, "CE", "ce1"), mod.Leg(23300.0, "PE", "pe1"),
        mod.Leg(23350.0, "CE", "ce2"), mod.Leg(23350.0, "PE", "pe2"),
        mod.Leg(23400.0, "CE", "ce3"), mod.Leg(23400.0, "PE", "pe3"),
    ]
    oi = {
        "ce1": series_for("ce1", [100, 110, 105]),
        "pe1": series_for("pe1", [100, 95, 105]),
        "ce2": series_for("ce2", [200, 220, 210]),
        "pe2": series_for("pe2", [200, 190, 220]),
        "ce3": series_for("ce3", [300, 330, 315]),
        "pe3": series_for("pe3", [300, 285, 330]),
    }
    summary, per_strike = mod.analyze_fixed_basket(
        session_date=date(2026,9,21), checkpoints=["10:10","10:15","10:20"],
        baseline_time="10:15", event_time="10:20", atm=23350.0, wings=1,
        strike_interval=50.0, legs=legs, oi_series=oi,
    )
    baseline = summary[1]
    event = summary[2]
    assert baseline["ce_delta_from_baseline"] == 0
    assert baseline["pe_delta_from_baseline"] == 0
    assert event["rolling_ce_delta"] == -30
    assert event["rolling_pe_delta"] == 85
    assert event["rolling_imbalance"] == 115
    assert event["ce_delta_from_baseline"] == -30
    assert event["pe_delta_from_baseline"] == 85
    assert event["imbalance_from_baseline"] == 115
    assert len(per_strike) == 18


def test_build_legs_requires_every_exact_contract():
    idx = {
        (23300.0,"CE"):"a", (23300.0,"PE"):"b",
        (23350.0,"CE"):"c", (23350.0,"PE"):"d",
        (23400.0,"CE"):"e",
    }
    try:
        mod.build_legs(idx=idx, atm=23350.0, wings=1, strike_interval=50.0)
    except mod.EventStudyError as exc:
        assert "EXACT_CONTRACT_MISSING_23400_PE" in str(exc)
    else:
        raise AssertionError("expected fail-closed exact contract error")


def test_exact_source_minute_is_required():
    legs = [mod.Leg(23350.0,"CE","ce"), mod.Leg(23350.0,"PE","pe")]
    # Deliberately missing 10:14 source minute needed for checkpoint 10:15.
    oi = {
        "ce": {datetime(2026,9,21,10,9,tzinfo=IST): 100},
        "pe": {datetime(2026,9,21,10,9,tzinfo=IST): 100},
    }
    try:
        mod.analyze_fixed_basket(
            session_date=date(2026,9,21), checkpoints=["10:10","10:15"],
            baseline_time="10:10", event_time="10:15", atm=23350.0, wings=0,
            strike_interval=50.0, legs=legs, oi_series=oi,
        )
    except mod.EventStudyError as exc:
        assert "EXACT_MINUTE_MISSING_10:15" in str(exc)
    else:
        raise AssertionError("expected fail-closed exact minute error")
