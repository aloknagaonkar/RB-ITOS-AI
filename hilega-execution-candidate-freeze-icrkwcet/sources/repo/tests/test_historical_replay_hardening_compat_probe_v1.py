from pathlib import Path

from market_lab.historical_replay_hardening_compat_probe_v1 import build_report


def test_probe_builds_report(monkeypatch, tmp_path):
    import market_lab.historical_replay_hardening_compat_probe_v1 as probe

    monkeypatch.setattr(probe, "OUTPUT", tmp_path / "report.json")
    report = build_report()

    assert report["model"] == "HISTORICAL_REPLAY_HARDENING_COMPAT_PROBE_V1"
    assert "market_lab.historical_replay_operations_worker_v1" in report["modules"]
    assert "frontend/src/historicalReplay.tsx" in report["frontend"]
    assert probe.OUTPUT.exists()
