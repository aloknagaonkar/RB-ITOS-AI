from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_control_failure_forward_path_v6_12.py"
spec = importlib.util.spec_from_file_location("v612", SCRIPT)
v612 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(v612)


def test_exact_directional_path_mirrors_bull_and_bear():
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    idx = {t0: 100.0}
    for i in range(1, 31):
        idx[t0 + timedelta(minutes=i)] = 100.0 + i
    bull = v612.exact_directional_path(idx, t0, "BULLISH", 30)
    bear = v612.exact_directional_path(idx, t0, "BEARISH", 30)
    assert bull[0] == 1.0 and bull[-1] == 30.0
    assert bear[0] == -1.0 and bear[-1] == -30.0


def test_path_metrics_time_to_mfe_and_adverse_before_mfe_are_causal_path_facts():
    path = [-3.0, -1.0, 2.0, 5.0, 4.0] + [4.0] * 25
    m = v612.path_metrics(path)
    assert m["mfe_30m_path"] == 5.0
    assert m["time_to_mfe_min"] == 4
    assert m["adverse_before_mfe"] == -3.0
    assert m["giveback_mfe_to_30m"] == 1.0


def test_fold_rank_cut_is_session_local_not_global():
    rows = [
        {"variant": "A", "session_date": "2026-01-01", "score": "10"},
        {"variant": "A", "session_date": "2026-01-01", "score": "1"},
        {"variant": "A", "session_date": "2026-01-02", "score": "100"},
        {"variant": "A", "session_date": "2026-01-02", "score": "99"},
    ]
    v612.assign_fold_rank_percentiles(rows)
    top = [r for r in rows if r["in_top10_fold"]]
    assert len(top) == 2
    assert {r["session_date"] for r in top} == {"2026-01-01", "2026-01-02"}


def test_missing_forward_minute_fails_instead_of_interpolating():
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    idx = {t0: 100.0}
    for i in range(1, 31):
        if i == 7:
            continue
        idx[t0 + timedelta(minutes=i)] = 100.0 + i
    try:
        v612.exact_directional_path(idx, t0, "BULLISH", 30)
        assert False, "expected exact-path failure"
    except ValueError as exc:
        assert "missing exact forward minute" in str(exc)
