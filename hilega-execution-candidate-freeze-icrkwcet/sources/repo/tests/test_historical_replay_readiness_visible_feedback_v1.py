from pathlib import Path


def test_readiness_has_persistent_visible_feedback():
    text = Path("frontend/src/historicalReplayOperations.tsx").read_text(encoding="utf-8")
    assert "lastCheckedAt" in text
    assert "Readiness checked for {sessionDate}" in text
    assert "Checking readiness for {sessionDate}…" in text
    assert "Replay prerequisites are ready." in text
    assert "Replay prerequisites are not ready." in text
