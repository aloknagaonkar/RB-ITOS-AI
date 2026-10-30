from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

P = Path(__file__).parents[1] / "scripts" / "validate_control_failure_expiry_aware_v6_2.py"
spec = spec_from_file_location("v62", P)
m = module_from_spec(spec)
sys.modules[spec.name] = m
assert spec.loader
spec.loader.exec_module(m)


def test_expiry_aware_wings_rule_is_exact():
    assert m.wings_for_sessions_left(0) == 1
    assert m.wings_for_sessions_left(1) == 2
    assert m.wings_for_sessions_left(2) == 3
    assert m.wings_for_sessions_left(3) == 4
    assert m.wings_for_sessions_left(4) == 5
    assert m.wings_for_sessions_left(7) == 5


def test_wednesday_to_next_tuesday_is_four_weekday_sessions_and_pm5():
    # Thu, Fri, Mon, Tue = 4 sessions remaining.
    n = m.weekday_sessions_to_expiry("2026-09-16", "2026-09-22")
    assert n == 4
    assert m.wings_for_sessions_left(n) == 5


def test_monday_to_tuesday_is_one_session_and_pm2():
    n = m.weekday_sessions_to_expiry("2026-09-21", "2026-09-22")
    assert n == 1
    assert m.wings_for_sessions_left(n) == 2


def test_component_orders_are_kept_separate():
    assert m.ORDERS == ("SAME_CANDLE", "FAILURE_THEN_DECAY", "DECAY_THEN_FAILURE")
