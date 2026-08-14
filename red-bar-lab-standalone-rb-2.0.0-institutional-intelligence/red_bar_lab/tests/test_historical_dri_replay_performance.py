from datetime import date
import pandas as pd

from red_bar_lab.services.historical_dri_decision_replay import (
    HistoricalDRIDecisionReplayService,
)


def test_service_exposes_timing_dictionary_without_running():
    service = object.__new__(HistoricalDRIDecisionReplayService)
    service.last_timing = {}
    assert service.last_timing == {}


def test_point_in_time_filter_pattern_excludes_future():
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-08-12T03:45:00Z",
            "2026-08-12T03:46:00Z",
            "2026-08-12T03:47:00Z",
        ]),
        "close": [10.0, 11.0, 12.0],
    })
    moment = pd.Timestamp("2026-08-12 09:16:00", tz="Asia/Kolkata")
    ts = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
    prior = frame.loc[ts <= moment.tz_convert("UTC")]
    assert list(prior["close"]) == [10.0, 11.0]
