from market_lab.historical_replay_compat_probe_v1 import build_report


def test_probe_builds_report():
    report = build_report()
    assert report["model"] == "HISTORICAL_REPLAY_COMPAT_PROBE_V1"
    assert "market_lab.live_shadow_production_wiring_v1" in report["modules"]


def test_probe_reports_coordinator_source_or_error():
    entry = build_report()["modules"]["market_lab.live_shadow_production_wiring_v1"]
    assert "error" in entry or "coordinator_source" in entry
