from pathlib import Path
import importlib.util
import sys

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
P = SCRIPTS / "validate_control_failure_full_day_intrabar_v6_7.py"
spec = importlib.util.spec_from_file_location("v67", P)
m = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(m)


class R:
    def __init__(self, fail, direction="BULLISH", spot=0.0):
        self.direction_failure = fail
        self.known_direction = direction
        self.spot_delta_1m = spot


def test_variant_a_triggers_on_first_failure():
    rows = [R(False), R(True), R(False), R(False), R(False)]
    assert m.trigger_minute(rows, "A") == 2


def test_variant_b_and_c_are_causal_at_second_failure():
    rows = [R(True), R(False), R(True), R(False), R(False)]
    assert m.trigger_minute(rows, "B") == 3
    assert m.trigger_minute(rows, "C") == 3


def test_variant_c_rejects_late_first_failure():
    rows = [R(False), R(False), R(True), R(True), R(False)]
    assert m.trigger_minute(rows, "B") == 4
    assert m.trigger_minute(rows, "C") is None


def test_variant_e_waits_until_two_minute_continuation_is_observable():
    # First failure minute 1, second failure minute 2; next two minutes after
    # first failure are minute 2 (+1) and minute 3 (+2), so E can only trigger m3.
    rows = [R(True, spot=1.0), R(True, spot=1.0), R(False, spot=2.0), R(False, spot=-1.0), R(False, spot=0.0)]
    assert m.trigger_minute(rows, "D") == 3
    assert m.trigger_minute(rows, "E") == 3
