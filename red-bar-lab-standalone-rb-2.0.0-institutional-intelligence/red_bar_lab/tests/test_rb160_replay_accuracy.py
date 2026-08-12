from datetime import date
from types import SimpleNamespace

import pandas as pd

from red_bar_lab.services.replay_accuracy import ReplayAccuracyService


class Hist:
    def read_day(self, instrument_key, trading_date, interval_minutes=1):
        ts = pd.date_range(f"{trading_date} 09:15", periods=10, freq="1min", tz="Asia/Kolkata")
        return pd.DataFrame({"timestamp": ts, "close": range(10)})


class Sync:
    def _live_snapshots(self, instrument_key, trading_date):
        # Deliberately miss 09:18-09:20 and 09:23.
        minutes = ("09:15", "09:16", "09:17", "09:21", "09:22", "09:24")
        return [(pd.Timestamp(f"{trading_date} {m}", tz="Asia/Kolkata"), {}, pd.DataFrame({"strike":[100]})) for m in minutes]


class Row:
    def __init__(self, confidence, outcome, execution, ret, blocker="NONE"):
        self.primary_confidence_pct = confidence
        self.outcome_result = outcome
        self.execution = execution
        self.option_return_pct = ret
        self.expectancy_pct = 5.0
        self.blocker = blocker
        self.candidate_symbol = "NIFTY TEST"
        if execution == "WOULD_TAKE":
            self.verdict = "CORRECT_TAKE" if outcome == "WIN" else "FALSE_POSITIVE"
        else:
            self.verdict = "MISSED_OPPORTUNITY" if outcome == "WIN" else "CORRECT_SKIP"


def test_rb160_reports_temporal_gaps_and_longest_run():
    day = date(2026, 8, 11)
    replay = SimpleNamespace(
        trading_date=day,
        rows=(Row(72,"WIN","WOULD_TAKE",10),),
        data_fidelity="LIVE_CAPTURE_PARTIAL",
        data_source="LIVE_MARKET_CAPTURE",
    )
    report = ReplayAccuracyService(Sync(), Hist()).build("NIFTY", replay)
    assert report.expected_minutes == 10
    assert report.captured_minutes == 6
    assert report.missing_minutes == 4
    assert report.longest_gap_minutes == 3
    assert "09:18–09:20" in report.missing_ranges


def test_rb160_calibration_is_advisory_and_sample_gated():
    day = date(2026, 8, 11)
    rows = tuple(Row(62 + (i % 20), "WIN" if i % 3 else "LOSS", "WOULD_WAIT", 5 if i % 3 else -5) for i in range(12))
    replay = SimpleNamespace(
        trading_date=day,
        rows=rows,
        data_fidelity="LIVE_CAPTURE_PARITY_HIGH",
        data_source="LIVE_MARKET_CAPTURE",
    )
    report = ReplayAccuracyService(Sync(), Hist(), minimum_calibration_samples=30).build("NIFTY", replay)
    assert report.recommendation_status == "INSUFFICIENT_SAMPLE"
    assert report.recommended_threshold_pct is None
    assert any("Keep live threshold unchanged" in item for item in report.recommendations)
    assert {s.threshold_pct for s in report.threshold_scenarios} == {60.0,65.0,70.0,75.0,80.0}
