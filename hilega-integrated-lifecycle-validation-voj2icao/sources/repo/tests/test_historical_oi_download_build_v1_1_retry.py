from pathlib import Path
from market_lab.historical_oi_build_job_v1 import (
    DEFAULT_ATTEMPTS,
    DEFAULT_RETRY_DELAYS_SECONDS,
    _complete,
)

def test_retry_defaults():
    assert DEFAULT_ATTEMPTS == 3
    assert DEFAULT_RETRY_DELAYS_SECONDS == (15, 60)

def test_complete_requires_available_and_csv():
    assert _complete({
        "returncode":0,
        "provider_status":"AVAILABLE",
        "positioning_csv_exists":True,
    })
    assert not _complete({
        "returncode":0,
        "provider_status":"PARTIAL",
        "positioning_csv_exists":True,
    })
    assert not _complete({
        "returncode":0,
        "provider_status":"AVAILABLE",
        "positioning_csv_exists":False,
    })

def test_ui_shows_retry_state():
    text=Path("frontend/src/historicalOiBuildPanel.tsx").read_text()
    assert "RETRYING" in text
    assert "Attempt history" in text
    assert "Next retry" in text
