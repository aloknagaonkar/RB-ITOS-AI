from __future__ import annotations

import pandas as pd

from red_bar_lab.ui.option_chain_directional_evidence import (
    OptionDirectionPolicy,
    build_option_chain_directional_evidence,
)


class _Database:
    def __init__(self, rows):
        self.rows = rows

    def read_option_chain_history(self, *args, **kwargs):
        return list(self.rows)


def _readiness():
    return {
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "signal_id": "SIG-1",
        "bundle_id": "BUNDLE-1",
        "requested_side": "PE",
        "snapshot_timestamp": "2026-08-17T10:01:00+05:30",
        "atm_strike": 25000,
    }


def _rows():
    return [
        {
            "collector_mode": "ONLINE",
            "snapshot_timestamp": "2026-08-17T10:00:00+05:30",
            "chain_artifact_path": "previous.csv",
        },
        {
            "collector_mode": "ONLINE",
            "snapshot_timestamp": "2026-08-17T10:01:00+05:30",
            "chain_artifact_path": "current.csv",
        },
        {
            "collector_mode": "ONLINE",
            "snapshot_timestamp": "2026-08-17T10:02:00+05:30",
            "chain_artifact_path": "future.csv",
        },
    ]


def _loader(frames):
    return lambda path: frames[str(path)].copy()


def _frame(call_values, put_values):
    return pd.DataFrame(
        {
            "strike": [24900, 24950, 25000, 25050, 25100],
            "call_oi": call_values,
            "put_oi": put_values,
        }
    )


def test_put_addition_and_call_unwinding_are_bullish():
    frames = {
        "previous.csv": _frame([100, 100, 100, 100, 100], [100, 100, 100, 100, 100]),
        "current.csv": _frame([90, 90, 90, 90, 90], [120, 120, 120, 120, 120]),
        "future.csv": _frame([1000] * 5, [1] * 5),
    }
    result = build_option_chain_directional_evidence(
        _readiness(), database=_Database(_rows()), instrument_key="NIFTY",
        artifact_loader=_loader(frames),
    )

    assert result["direction"] == "BULLISH"
    assert result["confidence"] == "STRONG"
    assert result["bullish_score"] == 1.0
    assert all(row["put_behaviour"] == "ADDITION" for row in result["rows"])
    assert all(row["call_behaviour"] == "UNWINDING" for row in result["rows"])
    assert result["current_snapshot_timestamp"] == "2026-08-17T10:01:00+05:30"


def test_call_addition_and_put_unwinding_are_bearish():
    frames = {
        "previous.csv": _frame([100] * 5, [100] * 5),
        "current.csv": _frame([125] * 5, [80] * 5),
        "future.csv": _frame([1] * 5, [1000] * 5),
    }
    result = build_option_chain_directional_evidence(
        _readiness(), database=_Database(_rows()), instrument_key="NIFTY",
        artifact_loader=_loader(frames),
    )

    assert result["direction"] == "BEARISH"
    assert result["bearish_score"] == 1.0
    assert all("CALL_OI_ADDITION" in row["evidence"] for row in result["rows"])
    assert all("PUT_OI_UNWINDING" in row["evidence"] for row in result["rows"])


def test_similar_bullish_and_bearish_contributions_are_mixed():
    frames = {
        "previous.csv": _frame([100] * 5, [100] * 5),
        "current.csv": _frame([120] * 5, [120] * 5),
        "future.csv": _frame([1] * 5, [1] * 5),
    }
    result = build_option_chain_directional_evidence(
        _readiness(), database=_Database(_rows()), instrument_key="NIFTY",
        artifact_loader=_loader(frames),
    )

    assert result["direction"] == "MIXED"
    assert result["bullish_score"] == 0.5
    assert result["bearish_score"] == 0.5


def test_small_changes_are_neutral_under_materiality_policy():
    frames = {
        "previous.csv": _frame([1000] * 5, [1000] * 5),
        "current.csv": _frame([1001] * 5, [999] * 5),
        "future.csv": _frame([1] * 5, [1] * 5),
    }
    policy = OptionDirectionPolicy(
        minimum_absolute_oi_change=10,
        minimum_percentage_oi_change=1.0,
    )
    result = build_option_chain_directional_evidence(
        _readiness(), database=_Database(_rows()), instrument_key="NIFTY",
        policy=policy, artifact_loader=_loader(frames),
    )

    assert result["direction"] == "NEUTRAL"
    assert result["bullish_score"] == 0.0
    assert result["bearish_score"] == 0.0


def test_missing_previous_snapshot_is_unavailable():
    rows = [_rows()[1], _rows()[2]]
    frames = {
        "current.csv": _frame([100] * 5, [100] * 5),
        "future.csv": _frame([100] * 5, [100] * 5),
    }
    result = build_option_chain_directional_evidence(
        _readiness(), database=_Database(rows), instrument_key="NIFTY",
        artifact_loader=_loader(frames),
    )

    assert result["direction"] == "UNAVAILABLE"
    assert "No earlier ONLINE" in result["dominant_reason"]


def test_directional_evidence_remains_read_only():
    frames = {
        "previous.csv": _frame([100] * 5, [100] * 5),
        "current.csv": _frame([90] * 5, [120] * 5),
        "future.csv": _frame([100] * 5, [100] * 5),
    }
    result = build_option_chain_directional_evidence(
        _readiness(), database=_Database(_rows()), instrument_key="NIFTY",
        artifact_loader=_loader(frames),
    )
    assert result["policy_action"] == "OBSERVE_ONLY"
    assert result["selection_unchanged"] is True
    assert result["persisted"] is False
    assert result["executed"] is False

    import red_bar_lab.ui.option_chain_directional_evidence as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "update_position" not in source
