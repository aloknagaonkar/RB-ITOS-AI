import csv
from pathlib import Path

from market_lab.hilega_wma_gap_historical_v1 import (
    build_wma_gap_session,
    recorded_live_metrics,
)


def test_performance_summary_contains_all_three_strategies(tmp_path):
    day = "2026-10-04"
    write(tmp_path / "trade-results.csv", [{
        "trade_id": "one", "session_date": day, "direction": "BULLISH",
        "route": "ROUTE_A", "entry_timestamp": f"{day}T10:00:00+05:30",
        "entry_price": "100", "exit_timestamp": f"{day}T10:20:00+05:30",
        "exit_price": "110", "canonical_points": "10", "mfe_points": "12",
        "mae_points": "-2", "candidate_decision": "ENTRY",
        "candidate_entry_timestamp": f"{day}T10:05:00+05:30",
        "candidate_points": "8",
    }])
    write(tmp_path / "confirmation-attempts.csv", [{
        "trade_id": "one", "session_date": day, "direction": "BULLISH",
        "confirmation_timestamp": f"{day}T10:05:00+05:30",
        "confirmation_close": "102", "armed_wma_strength": ".8",
        "confirmation_wma_strength": ".9", "threshold_maintained": "True",
        "confirmation_directional_gap": "2", "directional_gap_delta": ".2",
        "directional_gap_positive": "True", "directional_gap_expanding": "True",
        "passed": "True", "failure_reasons": "",
    }])
    result = build_wma_gap_session(day, tmp_path)
    assert [row["strategy_id"] for row in result["performance_summary"]] == [
        "LIVE_RECORDED_V1", "HILEGA_V1_REPLAY", "HILEGA_WMA_GAP_V2_REPLAY",
    ]


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


def test_complete_timeline_populates_every_condition_and_indicator(tmp_path):
    day = "2026-10-03"
    write(tmp_path / "trade-results.csv", [{
        "trade_id": "one", "session_date": day, "direction": "BULLISH",
        "route": "ROUTE_B", "entry_timestamp": f"{day}T10:00:00+05:30",
        "entry_price": "100", "exit_timestamp": f"{day}T10:20:00+05:30",
        "exit_price": "115", "canonical_points": "15", "mfe_points": "25",
        "mae_points": "-3", "candidate_decision": "ENTRY",
        "candidate_entry_timestamp": f"{day}T10:06:00+05:30",
        "candidate_points": "13",
    }])
    write(tmp_path / "confirmation-attempts.csv", [{
        "trade_id": "one", "session_date": day, "direction": "BULLISH",
        "confirmation_timestamp": f"{day}T10:06:00+05:30",
        "confirmation_close": "102", "armed_wma_strength": ".8",
        "confirmation_wma_strength": ".9", "threshold_maintained": "True",
        "confirmation_directional_gap": "2", "directional_gap_delta": ".2",
        "directional_gap_positive": "True", "directional_gap_expanding": "True",
        "passed": "True", "failure_reasons": "",
    }])
    write(tmp_path / "candidate-timeline.csv", [
        {"trade_id": "one", "session_date": day, "direction": "BULLISH",
         "minute_timestamp": f"{day}T10:05:00+05:30", "minutes_observed": "1",
         "within_confirmation_window": "True", "provisional_rsi9": "55",
         "provisional_ema3_rsi": "53", "provisional_wma21_rsi": "52",
         "directional_wma_change": ".8", "confirmation_tier": "CONFIRMED",
         "full_directional_alignment": "True", "observed_open": "100",
         "observed_high": "102", "observed_low": "99", "observed_close": "101",
         "observed_volume": "1000", "points_from_original_entry": "1"},
        {"trade_id": "one", "session_date": day, "direction": "BULLISH",
         "minute_timestamp": f"{day}T10:06:00+05:30", "minutes_observed": "2",
         "within_confirmation_window": "True", "provisional_rsi9": "57",
         "provisional_ema3_rsi": "55", "provisional_wma21_rsi": "52.5",
         "directional_wma_change": ".9", "confirmation_tier": "CONFIRMED",
         "full_directional_alignment": "True", "observed_open": "101",
         "observed_high": "103", "observed_low": "100", "observed_close": "102",
         "observed_volume": "1100", "points_from_original_entry": "2"},
    ])
    result = build_wma_gap_session(day, tmp_path)
    entry = next(row for row in result["reports"]
                 if row["strategy"]["directional_action"] == "WMA_GAP_ENTRY")
    assert entry["bar"] == {
        "open": 101.0, "high": 103.0, "low": 100.0,
        "close": 102.0, "volume": 1100.0,
    }
    assert entry["indicators"]["rsi9"] == 57.0
    assert entry["indicators"]["ema3_rsi"] == 55.0
    assert entry["indicators"]["wma21_rsi"] == 52.5
    statuses = {step["label"]: step["status"]
                for step in entry["conditions"]["strategy_steps"]}
    assert statuses["Later one-minute persistence"] == "PASS"
    assert statuses["EMA3-WMA21 gap expansion"] == "PASS"
    assert statuses["EMA3 continuation"] == "PASS"
