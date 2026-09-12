import json
from pathlib import Path

from market_lab.pcr_reversal_compare import (
    STAGE_2,
    compare_reversal_report_files,
)


def _report(path: Path, source: str, mean15: float, median15: float, lead_pct: float, lead_minutes: float):
    events = [
        {
            "session_date": "2026-01-01",
            "stage": STAGE_2,
            "event_time": "2026-01-01T10:00:00+05:30",
            "spot": 100.0,
            "prior_change_5m": 1.0,
            "prior_change_15m": 2.0,
            "prior_change_30m": 3.0,
            "forward_change_5m": -1.0,
            "forward_change_10m": -2.0,
            "forward_change_15m": mean15,
            "forward_change_30m": -4.0,
            "price_turn_lead_minutes": int(lead_minutes),
            "price_state_at_event": "UPTREND",
            "response_label": "TRUE_BEARISH_REVERSAL",
        },
        {
            "session_date": "2026-01-02",
            "stage": STAGE_2,
            "event_time": "2026-01-02T10:00:00+05:30",
            "spot": 101.0,
            "prior_change_5m": 1.0,
            "prior_change_15m": 2.0,
            "prior_change_30m": 3.0,
            "forward_change_5m": 1.0,
            "forward_change_10m": 1.0,
            "forward_change_15m": median15,
            "forward_change_30m": 2.0,
            "price_turn_lead_minutes": None,
            "price_state_at_event": "UPTREND",
            "response_label": "FALSE_WARNING",
        },
    ]
    payload = {
        "status": "AVAILABLE",
        "source": source,
        "row_count": 7500,
        "session_count": 20,
        "methodology": [],
        "limitations": [],
        "stages": [{
            "stage": STAGE_2,
            "event_count": 2,
            "session_count": 2,
            "prior_uptrend_event_count": 2,
            "price_already_bearish_count": 0,
            "pcr_led_price_count": 1,
            "no_price_turn_within_15m_count": 1,
            "pcr_led_price_pct": lead_pct,
            "mean_lead_minutes": lead_minutes,
            "median_lead_minutes": lead_minutes,
            "response_counts": {"TRUE_BEARISH_REVERSAL": 1, "FALSE_WARNING": 1},
            "mean_forward_5m": 0,
            "mean_forward_10m": 0,
            "mean_forward_15m": mean15,
            "mean_forward_30m": 0,
            "median_forward_15m": median15,
            "bearish_pct_15m": 60.0,
            "events": events,
        }],
        "transitions": {
            "stage_1_event_count": 0,
            "stage_1_to_2_count": 0,
            "stage_2_to_3_count": 0,
            "complete_1_to_2_to_3_count": 0,
            "mean_stage_1_to_2_minutes": None,
            "median_stage_1_to_2_minutes": None,
            "mean_stage_2_to_3_minutes": None,
            "median_stage_2_to_3_minutes": None,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_five_block_consistency(tmp_path):
    paths=[]
    for i in range(5):
        p=tmp_path/f"b{i}.json"
        _report(p, f"block-{i}", -2.0, -1.0, 70.0, 4.0)
        paths.append(p)
    report=compare_reversal_report_files(*paths)
    assert report.total_session_count == 100
    assert report.total_row_count == 37500
    assert report.bearish_direction_block_count == 5
    assert report.lead_support_block_count == 5
    assert report.robustness_status == "CONSISTENT_5_OF_5"
    assert report.combined.event_count == 10
    assert report.combined.pcr_led_price_count == 5
    assert report.combined.pcr_led_price_pct == 50.0


def test_one_direction_failure_is_mostly_consistent(tmp_path):
    paths=[]
    for i in range(5):
        p=tmp_path/f"b{i}.json"
        if i == 4:
            _report(p, f"block-{i}", 1.0, 1.0, 70.0, 4.0)
        else:
            _report(p, f"block-{i}", -2.0, -1.0, 70.0, 4.0)
        paths.append(p)
    report=compare_reversal_report_files(*paths)
    assert report.bearish_direction_block_count == 4
    assert report.lead_support_block_count == 5
    assert report.robustness_status == "MOSTLY_CONSISTENT"


def test_missing_stage2_raises(tmp_path):
    paths=[]
    for i in range(5):
        p=tmp_path/f"b{i}.json"
        _report(p, f"block-{i}", -2.0, -1.0, 70.0, 4.0)
        paths.append(p)
    bad=json.loads(paths[-1].read_text())
    bad["stages"]=[]
    paths[-1].write_text(json.dumps(bad))
    try:
        compare_reversal_report_files(*paths)
    except ValueError as exc:
        assert "Stage 2 missing" in str(exc)
    else:
        raise AssertionError("expected ValueError")
