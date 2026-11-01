import importlib.util
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "scripts" / "validate_control_failure_move_start_proximity_v6_3.py"
spec = importlib.util.spec_from_file_location("v63", P)
m = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)


def ev(cp, order="SAME_CANDLE"):
    return {"detected_checkpoint": cp, "component_order": order}


def test_lead_lag_sign_is_signal_minus_move_start():
    assert m.lead_lag_minutes("2026-05-18T10:00:00+05:30", "10:10") == -10.0
    assert m.lead_lag_minutes("2026-05-18T10:15:00+05:30", "10:10") == 5.0


def test_nearest_candidate_prefers_pre_move_on_equal_distance():
    rows = [ev("2026-05-18T10:05:00+05:30"), ev("2026-05-18T10:15:00+05:30")]
    got = m.nearest_event(rows, "10:10", 10)
    assert got["detected_checkpoint"].endswith("10:05:00+05:30")


def test_window_excludes_candidates_outside_boundary():
    rows = [ev("2026-05-18T09:50:00+05:30"), ev("2026-05-18T10:30:00+05:30")]
    assert m.nearest_event(rows, "10:10", 15) is None


def test_windows_are_frozen_and_primary_15_is_present():
    assert m.WINDOWS == (5, 10, 15, 20, 30)
    assert 15 in m.WINDOWS
