import csv
from datetime import datetime, timedelta
from pathlib import Path

from market_lab.pcr_reversal_analysis import analyze_pcr_reversal_csv


def _write(path: Path, stage_signs, spots):
    fields = [
        "session_date", "timestamp", "spot",
        "moving_pcr_change_5m", "moving_pcr_change_15m", "moving_pcr_change_30m",
        "forward_change_5m", "forward_change_10m", "forward_change_15m", "forward_change_30m",
    ]
    start = datetime(2026, 1, 2, 9, 15)
    rows = []
    n = len(spots)
    for i, spot in enumerate(spots):
        signs = stage_signs.get(i, (1, 1, 1))
        def fwd(m):
            j = i + m
            return spots[j] - spot if j < n else ""
        rows.append({
            "session_date": "2026-01-02",
            "timestamp": (start + timedelta(minutes=i)).isoformat(),
            "spot": spot,
            "moving_pcr_change_5m": signs[0],
            "moving_pcr_change_15m": signs[1],
            "moving_pcr_change_30m": signs[2],
            "forward_change_5m": fwd(5),
            "forward_change_10m": fwd(10),
            "forward_change_15m": fwd(15),
            "forward_change_30m": fwd(30),
        })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def test_persistent_stage_is_one_event(tmp_path):
    path = tmp_path / "e.csv"
    spots = [100 + i for i in range(20)] + [120 - 2 * (i - 20) for i in range(20, 60)]
    signs = {i: (-1, -1, 1) for i in range(20, 25)}
    _write(path, signs, spots)
    report = analyze_pcr_reversal_csv(path)
    stage2 = next(x for x in report.stages if x.stage.startswith("STAGE_2"))
    assert stage2.event_count == 1


def test_stage2_can_lead_price_turn(tmp_path):
    path = tmp_path / "e.csv"
    spots = [100 + i for i in range(23)]
    # After minute 22 price rolls over; stage2 starts at minute 20 while rolling 5m still positive.
    spots += [122, 121, 120, 119, 118, 117, 116, 115, 114, 113, 112, 111, 110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89, 88, 87, 86, 85]
    signs = {20: (-1, -1, 1), 21: (-1, -1, 1)}
    _write(path, signs, spots)
    report = analyze_pcr_reversal_csv(path)
    stage2 = next(x for x in report.stages if x.stage.startswith("STAGE_2"))
    assert stage2.prior_uptrend_event_count == 1
    assert stage2.pcr_led_price_count == 1
    assert stage2.events[0].price_turn_lead_minutes > 0


def test_stage_sequence_transition_timing(tmp_path):
    path = tmp_path / "e.csv"
    spots = [100 + i * 0.2 for i in range(80)]
    signs = {
        20: (-1, 1, 1),
        21: (-1, 1, 1),
        24: (-1, -1, 1),
        25: (-1, -1, 1),
        30: (-1, -1, -1),
        31: (-1, -1, -1),
    }
    _write(path, signs, spots)
    report = analyze_pcr_reversal_csv(path)
    t = report.transitions
    assert t.stage_1_to_2_count == 1
    assert t.stage_2_to_3_count == 1
    assert t.complete_1_to_2_to_3_count == 1
    assert t.median_stage_1_to_2_minutes == 4
    assert t.median_stage_2_to_3_minutes == 6


def test_true_reversal_label_requires_prior_up_and_sustained_down(tmp_path):
    path = tmp_path / "e.csv"
    spots = [100 + i for i in range(21)]
    spots += [119 - (i - 21) for i in range(21, 70)]
    signs = {20: (-1, -1, 1)}
    _write(path, signs, spots)
    report = analyze_pcr_reversal_csv(path)
    stage2 = next(x for x in report.stages if x.stage.startswith("STAGE_2"))
    assert stage2.events[0].response_label == "TRUE_BEARISH_REVERSAL"
