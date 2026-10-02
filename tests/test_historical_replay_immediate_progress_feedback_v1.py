from pathlib import Path


def test_immediate_progress_feedback_present():
    text = Path("frontend/src/historicalReplayOperations.tsx").read_text(encoding="utf-8")
    assert "pendingAction" in text
    assert "Checking readiness…" in text
    assert "STARTING" in text
    assert "Validating strict readiness and starting replay worker…" in text
    assert "Starting historical data download worker…" in text


def test_server_job_progress_still_present():
    text = Path("frontend/src/historicalReplayOperations.tsx").read_text(encoding="utf-8")
    assert "['QUEUED','RUNNING'].includes(job.status)" in text
    assert "hr-ops-progress" in text
