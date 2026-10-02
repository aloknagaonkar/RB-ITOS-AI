from datetime import date
import json
from pathlib import Path

from market_lab.historical_replay_performance_probe_v1 import snapshot_baseline


def test_snapshot_baseline(tmp_path):
    d = date(2026, 9, 18)
    src = tmp_path / "replay" / d.isoformat()
    src.mkdir(parents=True)
    (src / "replay-status.json").write_text(json.dumps({
        "status": "COMPLETE",
        "checkpoint_count": 74,
        "processed_checkpoint_count": 74,
        "missing_checkpoint_count": 0,
        "observation_count": 8,
        "state_counts": {"CLOSED": 3, "REJECTED": 5},
        "step_audit_rows": 418,
        "step_audit_chain_ok": True,
    }))
    (src / "events.jsonl").write_text('{"x":1}\n')
    (src / "health.jsonl").write_text('{"x":2}\n')
    (src / "step-audit.jsonl").write_text('{"x":3}\n')

    result = snapshot_baseline(
        d,
        replay_root=tmp_path / "replay",
        baseline_root=tmp_path / "baseline",
    )
    assert result["status_summary"]["checkpoint_count"] == 74
    assert result["status_summary"]["observation_count"] == 8
    assert result["status_summary"]["step_audit_chain_ok"] is True
    assert (tmp_path / "baseline" / d.isoformat() / "baseline-manifest.json").exists()
