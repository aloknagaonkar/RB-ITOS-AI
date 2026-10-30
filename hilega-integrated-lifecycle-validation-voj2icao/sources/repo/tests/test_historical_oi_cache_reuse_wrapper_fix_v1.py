import json

from market_lab.historical_oi_cache_reuse_rate_limit_v1 import _load_session_compatible


def test_load_session_compatible_wrapper(tmp_path):
    p = tmp_path / "wrapper.json"
    p.write_text(json.dumps({
        "sessions": [{
            "session_date": "2026-06-03",
            "expiry": "2026-06-09",
            "status": "AVAILABLE",
            "rows": [{"strike": 23000}]
        }]
    }))
    s = _load_session_compatible(p, "2026-06-03")
    assert s["expiry"] == "2026-06-09"
    assert len(s["rows"]) == 1


def test_load_session_compatible_legacy_single_top_level(tmp_path):
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({
        "session_date": "2026-06-03",
        "expiry": "2026-06-09",
        "status": "AVAILABLE",
        "wings": 5,
        "rows": [{"strike": 23000}]
    }))
    s = _load_session_compatible(p, "2026-06-03")
    assert s["expiry"] == "2026-06-09"
    assert s["wings"] == 5


def test_load_session_compatible_rejects_unavailable(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({
        "session_date": "2026-06-03",
        "expiry": "2026-06-09",
        "status": "UNAVAILABLE",
        "rows": []
    }))
    try:
        _load_session_compatible(p, "2026-06-03")
    except ValueError as e:
        assert "not AVAILABLE" in str(e)
    else:
        raise AssertionError("Expected ValueError")
