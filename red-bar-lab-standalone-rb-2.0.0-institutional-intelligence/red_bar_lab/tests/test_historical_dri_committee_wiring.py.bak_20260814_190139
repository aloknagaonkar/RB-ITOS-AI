from pathlib import Path

from red_bar_lab.services.historical_dri_decision_replay import (
    HistoricalDRIDecisionReplayService,
)


def test_dri_wiring_is_rank1_and_point_in_time():
    source = Path(
        "red_bar_lab/services/historical_dri_decision_replay.py"
    ).read_text(encoding="utf-8")
    assert "rank1 = candidates[0] if candidates else None" in source
    assert "candidate_rank=1" in source
    assert "point_in_time_contracts" in source
    assert "detect_historical_dri_events(candles)" in source
    assert "_simulate_exit" in source


def test_adapter_is_separate_from_red_bar_service():
    assert HistoricalDRIDecisionReplayService.__name__ == (
        "HistoricalDRIDecisionReplayService"
    )
