import json
from pathlib import Path

from market_lab.pcr_deep_compare import compare_pcr_deep_json


def _report(path: Path, source: str, low, high, reversal):
    def condition(name, values):
        mean, median, bullish, bearish, rows, sessions = values
        return {
            "condition": name,
            "row_count": rows,
            "session_count": sessions,
            "forwards": {
                "forward_change_15m": {
                    "count": rows,
                    "session_count": sessions,
                    "mean": mean,
                    "median": median,
                    "bullish_pct": bullish,
                    "bearish_pct": bearish,
                }
            },
        }
    payload = {
        "source": source,
        "row_count": 100,
        "session_count": 20,
        "panels": [{
            "panel": "moving",
            "level_plus_turn": [
                condition("PCR_LT_0_70_AND_5M_RISING", low),
                condition("PCR_GT_1_25_AND_5M_FALLING", high),
            ],
            "early_flip_candidates": [
                condition("BEARISH_5M_15M_FLIP_WHILE_30M_RISING", reversal),
            ],
        }],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_compare_reports_marks_consistent_candidates(tmp_path):
    train = tmp_path / "train.json"
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    bullish = (2.0, 1.0, 60.0, 40.0, 30, 10)
    bearish = (-2.0, -1.0, 40.0, 60.0, 25, 9)
    for path, name in ((train, "train.csv"), (a, "a.csv"), (b, "b.csv")):
        _report(path, name, bullish, bearish, bearish)
    report = compare_pcr_deep_json(train, a, b)
    assert report.total_session_count == 60
    assert all(item.validation_status == "CONSISTENT" for item in report.candidates)


def test_compare_reports_marks_mixed_when_one_block_reverses(tmp_path):
    train = tmp_path / "train.json"
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    bullish = (2.0, 1.0, 60.0, 40.0, 30, 10)
    bearish = (-2.0, -1.0, 40.0, 60.0, 25, 9)
    _report(train, "train.csv", bullish, bearish, bearish)
    _report(a, "a.csv", bullish, bearish, bearish)
    _report(b, "b.csv", (-1.0, -0.5, 40.0, 60.0, 20, 8), bearish, bearish)
    report = compare_pcr_deep_json(train, a, b)
    low = next(item for item in report.candidates if item.condition == "PCR_LT_0_70_AND_5M_RISING")
    assert low.validation_status == "MIXED"
    assert low.consistent_direction_count == 2


def test_compare_does_not_require_large_sample_to_change_definition(tmp_path):
    train = tmp_path / "train.json"
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    bullish = (1.0, 0.5, 55.0, 45.0, 1, 1)
    bearish = (-1.0, -0.5, 45.0, 55.0, 1, 1)
    for path, name in ((train, "train.csv"), (a, "a.csv"), (b, "b.csv")):
        _report(path, name, bullish, bearish, bearish)
    report = compare_pcr_deep_json(train, a, b)
    assert report.candidates[0].condition == "PCR_LT_0_70_AND_5M_RISING"
    assert report.candidates[0].validation_status == "CONSISTENT"
