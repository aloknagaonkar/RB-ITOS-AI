from pathlib import Path

def test_installer_contains_required_wiring():
    installer = Path("apply_historical_dri_replay_ui_wiring.py").read_text(encoding="utf-8")
    assert '"Replay Sources"' in installer
    assert '"RED_BAR", "DRI_EARLY", "DRI_CONFIRMED"' in installer
    assert "detect_historical_dri_events" in installer
    assert "consolidate_replay_rows" in installer
    assert "Rank-1 Opportunity Summary" in installer

def test_installer_preserves_existing_red_bar_service():
    installer = Path("apply_historical_dri_replay_ui_wiring.py").read_text(encoding="utf-8")
    assert '"RED_BAR" in replay_sources' in installer
    assert "HistoricalDecisionReplayService" in installer
    assert "replay_service.run_day(instrument_key, replay_date)" in installer
    assert "Existing Red Bar replay details and engines remain unchanged." in installer
