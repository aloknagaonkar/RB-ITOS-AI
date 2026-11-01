import importlib.util
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("v68", ROOT / "scripts" / "validate_control_failure_context_discrimination_v6_8.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def test_context_time_is_strictly_pretrigger(monkeypatch):
    seen = []
    trigger = datetime(2026, 1, 1, 10, 5, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    ctx = trigger - timedelta(minutes=1)
    fake_idx = {ctx: {}}
    monkeypatch.setattr(m, "index_rows", lambda s: fake_idx)
    monkeypatch.setattr(m, "atm_spot", lambda g, t: (100.0, 20000.0))
    def fake_exact(idx, ts, strikes):
        seen.append(ts); return (100.0, 120.0, 20000.0)
    monkeypatch.setattr(m, "exact_totals", fake_exact)
    monkeypatch.setattr(m, "one_minute_breadth", lambda *a: (1, 1, 1, "MIXED"))
    m.build_pretrigger_context({"strike_interval": 50}, trigger, 1)
    assert seen and max(seen) <= ctx
    assert trigger not in seen


def test_pcr_is_pe_over_ce_and_zero_ce_is_missing():
    assert m.pcr(120, 100) == 1.2
    assert m.pcr(120, 0) is None


def test_population_comparison_keeps_near_and_non_move_separate():
    rows = [
        {"variant":"E","direction":"BULLISH","population":"NEAR_MOVE","spot_trend_5m":10},
        {"variant":"E","direction":"BULLISH","population":"NON_MOVE","spot_trend_5m":-2},
    ]
    r = m.compare_numeric(rows, "E", "BULLISH", "spot_trend_5m")
    assert r["near_n"] == 1 and r["non_move_n"] == 1
    assert r["near_median"] == 10 and r["non_move_median"] == -2


def test_time_bucket_is_frozen_and_causal():
    tz = timezone(timedelta(hours=5, minutes=30))
    assert m.time_bucket(datetime(2026,1,1,9,59,tzinfo=tz)) == "OPEN_0915_1029"
    assert m.time_bucket(datetime(2026,1,1,10,30,tzinfo=tz)) == "MORNING_1030_1159"
    assert m.time_bucket(datetime(2026,1,1,12,0,tzinfo=tz)) == "MIDDAY_1200_1359"
    assert m.time_bucket(datetime(2026,1,1,14,0,tzinfo=tz)) == "LATE_1400_CLOSE"
