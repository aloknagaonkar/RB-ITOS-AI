from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
import sys
from pathlib import Path

P = Path(__file__).parents[1] / "scripts" / "validate_control_failure_frozen_36_v6.py"
spec = spec_from_file_location("v6", P)
v6 = module_from_spec(spec)
sys.modules[spec.name] = v6
assert spec.loader
spec.loader.exec_module(v6)


def test_frozen_population_is_exact_18_plus_18():
    assert len(v6.BULLISH_DATES) == 18
    assert len(v6.BEARISH_DATES) == 18
    assert len(v6.ALL_DATES) == 36
    assert not (set(v6.BULLISH_DATES) & set(v6.BEARISH_DATES))


def test_d1_rule_is_explicit_not_inferred_for_other_dte():
    assert v6.dte("2026-05-18", "2026-05-19") == 1
    assert v6.dte("2026-05-19", "2026-05-19") == 0


def test_matrix_keeps_known_direction_and_first_matching_event():
    events = [
        {"session_date":"2026-05-18","direction":"BEARISH","detected_checkpoint":"2026-05-18T09:50:00+05:30","component_order":"SAME_CANDLE","atm_state":"BULLISH","bullish_strikes":"5","bearish_strikes":"0","imbalance":"1","imbalance_velocity":"-1","imbalance_acceleration":"-1","move_5m":"-5","move_10m":"-8","move_15m":"-10","move_30m":"-15"},
        {"session_date":"2026-05-18","direction":"BULLISH","detected_checkpoint":"2026-05-18T10:00:00+05:30","component_order":"FAILURE_THEN_DECAY","atm_state":"BEARISH","bullish_strikes":"0","bearish_strikes":"5","imbalance":"-3","imbalance_velocity":"2","imbalance_acceleration":"4","move_5m":"10","move_10m":"20","move_15m":"25","move_30m":"30"},
    ]
    expiry = {d: None for d in v6.ALL_DATES}
    expiry["2026-05-18"] = "2026-05-19"
    rows = v6.make_matrix(events, expiry, {"2026-05-18":"10:10"})
    r = next(x for x in rows if x.session_date == "2026-05-18")
    assert r.known_direction == "BULLISH"
    assert r.first_same_direction_checkpoint.endswith("10:00:00+05:30")
    assert r.opposite_direction_count == 1
    assert r.dte == 1
    assert r.pm2_rule_status == "STRICT_D1_PM2"
    assert r.lead_lag_minutes == -10.0
