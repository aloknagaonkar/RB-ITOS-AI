import json
from pathlib import Path

from market_lab.historical_oi_enrichment_batch_v1 import discover_existing_builds

def test_discovery_uses_available_build_with_expiry(tmp_path):
    d=tmp_path/"2026-09-09"
    d.mkdir()
    (d/"positioning.json").write_text(json.dumps({
        "sessions":[{
            "session_date":"2026-09-09",
            "expiry":"2026-09-15",
            "status":"AVAILABLE",
            "wings":5,
            "row_count":4125
        }]
    }))
    rows=discover_existing_builds(tmp_path)
    assert rows==[{
        "session_date":"2026-09-09",
        "expiry":"2026-09-15",
        "source":str(d/"positioning.json"),
        "wings":5,
        "row_count":4125,
    }]

def test_discovery_rejects_unavailable(tmp_path):
    d=tmp_path/"2026-09-10"
    d.mkdir()
    (d/"positioning.json").write_text(json.dumps({
        "sessions":[{
            "session_date":"2026-09-10",
            "expiry":"2026-09-15",
            "status":"UNAVAILABLE"
        }]
    }))
    assert discover_existing_builds(tmp_path)==[]

def test_discovery_prefers_auto_alias(tmp_path):
    d=tmp_path/"2026-09-09"
    d.mkdir()
    good={"sessions":[{"session_date":"2026-09-09","expiry":"2026-09-15","status":"AVAILABLE","wings":6}]}
    (d/"positioning-auto.json").write_text(json.dumps(good))
    (d/"positioning.json").write_text(json.dumps(good))
    rows=discover_existing_builds(tmp_path)
    assert rows[0]["source"].endswith("positioning-auto.json")
