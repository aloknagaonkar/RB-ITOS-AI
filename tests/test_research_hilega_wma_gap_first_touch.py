import csv
from pathlib import Path

from scripts.research_hilega_wma_gap_first_touch import first_touch, run


def trace(direction="BULLISH", strength=".8"):
    if direction == "BULLISH":
        reference = (50, 44, 40)
        current = (52, 47, 40)
    else:
        reference = (50, 56, 60)
        current = (48, 53, 60)
    return [{
        "trade_id": "one", "session_date": "2026-10-05",
        "direction": direction, "minute_timestamp": "2026-10-05T10:01:00+05:30",
        "within_confirmation_window": "True", "directional_wma_change": strength,
        "reference_rsi9": reference[0], "reference_ema3_rsi": reference[1],
        "reference_wma21_rsi": reference[2], "provisional_rsi9": current[0],
        "provisional_ema3_rsi": current[1], "provisional_wma21_rsi": current[2],
        "full_directional_alignment": "True", "observed_close": "102",
    }]


def write(path: Path, records: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader(); writer.writerows(records)


def test_first_touch_uses_completed_signal_bar_as_causal_baseline():
    result = first_touch(trace(), .75)
    assert result is not None
    assert result["comparison_source"] == "COMPLETED_SIGNAL_BAR_REFERENCE"
    assert result["previous_directional_gap"] == 4
    assert result["current_directional_gap"] == 7
    assert result["directional_gap_delta"] == 3
    assert result["directional_ema_delta"] == 3


def test_first_touch_keeps_075_and_100_as_separate_policies():
    assert first_touch(trace(strength=".8"), .75) is not None
    assert first_touch(trace(strength=".8"), 1.0) is None


def test_bearish_gap_and_ema_are_direction_normalized():
    result = first_touch(trace(direction="BEARISH"), .75)
    assert result is not None
    assert result["previous_directional_gap"] == 4
    assert result["current_directional_gap"] == 7
    assert result["directional_gap_delta"] == 3
    assert result["directional_ema_delta"] == 3


def test_report_separates_frozen_and_forward_evidence(tmp_path):
    frozen = tmp_path / "frozen"; forward = tmp_path / "forward"
    trade = {
        "trade_id": "one", "session_date": "2026-10-05", "direction": "BULLISH",
        "entry_timestamp": "2026-10-05T10:00:00+05:30", "entry_price": "100",
        "exit_timestamp": "2026-10-05T10:20:00+05:30", "exit_price": "110",
        "canonical_points": "10", "candidate_points": "8",
        "canonical_reached_plus20": "False",
    }
    write(forward / "trade-results.csv", [trade])
    write(forward / "candidate-timeline.csv", trace())
    report = run(frozen, forward, tmp_path / "out")
    assert report["trades"] == 1
    rows = [row for row in report["headline"] if row["cohort"] == "FORWARD"]
    assert any(row["signals"] == 1 and row["policy"] == "FIRST_TOUCH_GE_0_75" for row in rows)
