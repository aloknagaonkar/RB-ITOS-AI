from market_lab.oi_session_quantity_replay_template_v1 import pct, parse_session_specs

def test_pct():
    assert pct(150, 100) == 50.0
    assert pct(90, 100) == -10.0

def test_session_spec():
    got = parse_session_specs(["2026-08-25|13:45,13:50"])
    assert got == [{"date":"2026-08-25","times":["13:45","13:50"]}]
