from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_strike_breadth_transition_v3.py"
spec = spec_from_file_location("breadth_v3", SCRIPT)
mod = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def rows_for(time, phase, atm, strike, ce_delta, pe_delta, ce_oi=1000, pe_oi=1000):
    base = {
        "time": time,
        "phase": phase,
        "fixed_atm": str(atm),
        "strike": str(strike),
        "wings": "2",
    }
    ce = dict(base, side="CE", rolling_delta="" if ce_delta is None else str(ce_delta), oi=str(ce_oi))
    pe = dict(base, side="PE", rolling_delta="" if pe_delta is None else str(pe_delta), oi=str(pe_oi))
    return [ce, pe]


def test_breadth_and_atm_state_transition():
    rows = []
    for strike in (23300, 23350, 23400):
        rows += rows_for("10:40", "EVENT", 23350, strike, 100, -100)
    rows += rows_for("10:45", "POST_EVENT", 23350, 23300, 50, -20)
    rows += rows_for("10:45", "POST_EVENT", 23350, 23350, -100, 50)
    rows += rows_for("10:45", "POST_EVENT", 23350, 23400, -50, 100)

    summary, detail = mod.analyze(rows)
    assert summary[0]["bullish_count"] == 0
    assert summary[0]["bearish_count"] == 3
    assert summary[1]["bullish_count"] == 2
    assert summary[1]["bearish_count"] == 1
    assert summary[1]["atm_state"] == "BULLISH"
    assert summary[1]["aggregate_imbalance"] == 230
    assert len(detail) == 6


def test_imbalance_velocity_and_delta_acceleration():
    rows = []
    rows += rows_for("10:40", "EVENT", 23350, 23350, 200, -100)
    rows += rows_for("10:45", "POST_EVENT", 23350, 23350, 50, 100)
    summary, detail = mod.analyze(rows)
    first, second = detail
    assert first["imbalance"] == -300
    assert first["imbalance_velocity"] is None
    assert second["imbalance"] == 50
    assert second["imbalance_velocity"] == 350
    assert second["ce_delta_acceleration"] == -150
    assert second["pe_delta_acceleration"] == 200
    assert summary[1]["aggregate_imbalance_velocity"] == 350


def test_incomplete_first_checkpoint_is_preserved():
    rows = rows_for("10:10", "PRE_HISTORY", 23350, 23350, None, None)
    summary, detail = mod.analyze(rows)
    assert detail[0]["state"] == "INCOMPLETE"
    assert summary[0]["incomplete_count"] == 1
