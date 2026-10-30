from pathlib import Path


def test_ui_uses_top_level_strict_replay_ready():
    text = Path("frontend/src/historicalReplayOperations.tsx").read_text(encoding="utf-8")
    assert "strictReplayReady" in text
    assert "value.strict_replay_ready" in text
    assert "const checkpointReady = strictReplayReady!==null" in text


def test_run_button_still_gated_by_checkpoint_ready():
    text = Path("frontend/src/historicalReplayOperations.tsx").read_text(encoding="utf-8")
    assert "disabled={busy||!sessionDate||!checkpointReady}" in text
