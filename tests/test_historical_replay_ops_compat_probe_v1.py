from market_lab.historical_replay_ops_compat_probe_v1 import build_report


def test_probe_builds_report():
    report = build_report()
    assert report["model"] == "HISTORICAL_REPLAY_OPS_COMPAT_PROBE_V1"
    assert "market_lab.historical_replay_data_api_v1" in report["modules"]
    assert "market_lab.historical_replay_day_v1_1" in report["modules"]


def test_probe_reports_routes_or_module_error():
    report = build_report()
    item = report["modules"]["market_lab.historical_replay_data_api_v1"]
    assert "error" in item or "router_routes" in item
