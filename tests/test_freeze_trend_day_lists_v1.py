from pathlib import Path
import json
import subprocess
import sys

def test_freeze_lists(tmp_path):
    classification = tmp_path / "classification.json"
    classification.write_text(json.dumps({
        "research_version": "DAY_TREND_CLASSIFICATION_90D_V1",
        "scope": {},
        "methodology": {},
        "sessions": [
            {"session_date": "2026-01-01", "day_class": "BULLISH_TREND_DAY"},
            {"session_date": "2026-01-02", "day_class": "MIXED_DAY"},
            {"session_date": "2026-01-03", "day_class": "BEARISH_TREND_DAY"},
        ]
    }))

    bull = tmp_path / "bull.txt"
    bear = tmp_path / "bear.txt"
    manifest = tmp_path / "manifest.json"

    subprocess.run([
        sys.executable,
        "-m", "market_lab.freeze_trend_day_lists_v1",
        "--classification", str(classification),
        "--bullish-output", str(bull),
        "--bearish-output", str(bear),
        "--manifest-output", str(manifest),
    ], check=True)

    assert bull.read_text().strip() == "2026-01-01"
    assert bear.read_text().strip() == "2026-01-03"

    m = json.loads(manifest.read_text())
    assert m["bullish_count"] == 1
    assert m["bearish_count"] == 1
