import csv
from pathlib import Path

from market_lab.hilega_wma_gap_historical_v1 import (
    build_wma_gap_session,
    recorded_live_metrics,
)


def write(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_daily_metrics_and_inspection_steps(tmp_path):
    day = "2026-10-01"
    common = {
        "session_date": day, "route": "ROUTE_A", "entry_price": "100",
        "exit_price": "110", "mfe_points": "25", "mae_points": "-5",
    }
    write(tmp_path / "trade-results.csv", [
        {**common, "trade_id": "one", "direction": "BULLISH",
         "entry_timestamp": f"{day}T10:00:00+05:30",
         "exit_timestamp": f"{day}T10:20:00+05:30",
         "canonical_points": "10", "candidate_decision": "ENTRY",
         "candidate_entry_timestamp": f"{day}T10:06:00+05:30",
         "candidate_points": "8"},
        {**common, "trade_id": "two", "direction": "BEARISH",
         "entry_timestamp": f"{day}T11:00:00+05:30",
         "exit_timestamp": f"{day}T11:20:00+05:30",
         "canonical_points": "-10", "candidate_decision": "NO_ENTRY",
         "candidate_entry_timestamp": "", "candidate_points": ""},
    ])
    write(tmp_path / "confirmation-attempts.csv", [{
        "trade_id": "one", "session_date": day, "direction": "BULLISH",
        "confirmation_timestamp": f"{day}T10:06:00+05:30",
        "confirmation_close": "102", "armed_wma_strength": "0.8",
        "confirmation_wma_strength": "0.9", "threshold_maintained": "True",
        "confirmation_directional_gap": "2.1", "directional_gap_delta": ".2",
        "directional_gap_positive": "True", "directional_gap_expanding": "True",
        "passed": "True", "failure_reasons": "",
    }])

    result = build_wma_gap_session(day, tmp_path)
    summary = {row["strategy_id"]: row for row in result["performance_summary"]}
    assert summary["HILEGA_V1_REPLAY"]["net_points"] == 0
    assert summary["HILEGA_WMA_GAP_V2_REPLAY"]["net_points"] == 8
    assert result["comparison"] == {
        "candidate_net_delta_vs_v1": 8,
        "losses_avoided": 1,
        "winners_denied": 0,
    }
    entry = next(row for row in result["reports"]
                 if row["strategy"]["directional_action"] == "WMA_GAP_ENTRY")
    labels = [step["label"] for step in entry["conditions"]["strategy_steps"]]
    assert labels == [
        "Canonical Hilega signal", "WMA21 arm", "WMA21 persistence",
        "Directional gap positive", "Directional gap expanding",
    ]
    assert all(step["status"] == "PASS" for step in entry["conditions"]["strategy_steps"])


def test_denied_trade_is_not_counted_as_zero_point_trade(tmp_path):
    day = "2026-10-02"
    write(tmp_path / "trade-results.csv", [{
        "trade_id": "one", "session_date": day, "direction": "BULLISH",
        "route": "OPENING", "entry_timestamp": f"{day}T09:25:00+05:30",
        "entry_price": "100", "exit_timestamp": f"{day}T09:40:00+05:30",
        "exit_price": "90", "canonical_points": "-10", "mfe_points": "2",
        "mae_points": "-10", "candidate_decision": "NO_ENTRY",
        "candidate_entry_timestamp": "", "candidate_points": "",
    }])
    write(tmp_path / "confirmation-attempts.csv", [{
        "trade_id": "one", "session_date": day, "direction": "BULLISH",
        "confirmation_timestamp": f"{day}T09:30:00+05:30",
        "confirmation_close": "99", "armed_wma_strength": ".8",
        "confirmation_wma_strength": ".6", "threshold_maintained": "False",
        "confirmation_directional_gap": "1", "directional_gap_delta": "-.2",
        "directional_gap_positive": "True", "directional_gap_expanding": "False",
        "passed": "False", "failure_reasons": "WMA_THRESHOLD_NOT_MAINTAINED",
    }])
    result = build_wma_gap_session(day, tmp_path)
    candidate = result["performance_summary"][2]
    assert candidate["entries"] == 0
    assert candidate["denied"] == 1
    assert candidate["completed"] == 0
    assert candidate["breakeven_trades"] == 0


def test_recorded_live_metrics_pair_directional_points():
    reports = [{"checkpoint": "2026-10-01T10:00:00+05:30", "transitions": [
        {"event_time": "2026-10-01T10:00:00+05:30",
         "event_type": "BEARISH_ENTRY", "price": 100},
    ]}, {"checkpoint": "2026-10-01T10:20:00+05:30", "transitions": [
        {"event_time": "2026-10-01T10:20:00+05:30",
         "event_type": "BEARISH_STRUCTURAL_EXIT", "price": 80},
    ]}]
    result = recorded_live_metrics(reports)
    assert result["available"] is True
    assert result["net_points"] == 20
