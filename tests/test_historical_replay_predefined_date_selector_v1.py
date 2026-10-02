from pathlib import Path


def test_historical_replay_has_predefined_date_selector():
    text = Path("frontend/src/historicalReplay.tsx").read_text(encoding="utf-8")
    assert "function recentPresetDates(" in text
    assert "const presetDates=useMemo(" in text
    assert "<label>Quick date" in text
    assert 'Select a date…' in text
    assert "<label>Custom date" in text
    assert 'type="date"' in text
