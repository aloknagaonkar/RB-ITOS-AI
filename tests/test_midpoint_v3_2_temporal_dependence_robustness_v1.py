import math
import pytest

from market_lab.midpoint_v3_2_temporal_dependence_robustness_v1 import (
    FROZEN_POLICY_ID,
    analyze,
    moving_block_bootstrap,
    prepare_rows,
    worst_regime_stress,
)


def _row(block, ts, ret, policy_id=FROZEN_POLICY_ID):
    return {
        "policy_id": policy_id,
        "block": block,
        "session_date": ts[:10],
        "entry_timestamp": ts,
        "net_return_pct": ret,
    }


def _payload():
    rows = []
    # Two TRAIN trades.
    rows.extend(
        [
            _row("TRAIN", "2026-08-10T09:30:00+05:30", -5.5),
            _row("TRAIN", "2026-09-01T09:31:00+05:30", 8.0),
        ]
    )
    # Ensure every OOS block exists, across multiple months.
    rows.extend(
        [
            _row("OOS_A", "2026-04-01T09:30:00+05:30", 2.0),
            _row("OOS_A", "2026-04-02T09:31:00+05:30", -1.0),
            _row("OOS_B", "2026-05-01T09:30:00+05:30", 3.0),
            _row("OOS_B", "2026-05-02T09:31:00+05:30", -1.0),
            _row("OOS_C", "2026-06-01T09:30:00+05:30", 4.0),
            _row("OOS_C", "2026-06-02T09:31:00+05:30", -1.0),
            _row("OOS_D", "2026-07-01T09:30:00+05:30", 5.0),
            _row("OOS_D", "2026-07-02T09:31:00+05:30", -1.0),
        ]
    )
    return {"rows": rows}


def test_prepare_rows_sorts_exact_entry_timestamp():
    payload = {
        "rows": [
            _row("TRAIN", "2026-08-12T10:00:00+05:30", 1.0),
            _row("TRAIN", "2026-08-12T09:29:00+05:30", -1.0),
        ]
    }
    rows = prepare_rows(payload)
    assert rows[0]["entry_timestamp"].endswith("09:29:00+05:30")
    assert rows[1]["entry_timestamp"].endswith("10:00:00+05:30")


def test_prepare_rows_rejects_forbidden_oos_h():
    payload = {
        "rows": [
            _row("TRAIN", "2026-08-12T09:29:00+05:30", 1.0),
            _row("OOS_H", "2026-01-01T09:30:00+05:30", 2.0),
        ]
    }
    with pytest.raises(ValueError, match="forbidden OOS block"):
        prepare_rows(payload)


def test_moving_block_bootstrap_is_deterministic():
    rows = prepare_rows(_payload())
    oos = [row for row in rows if row["block"] != "TRAIN"]
    a = moving_block_bootstrap(oos, block_length=3, iterations=200, seed=42)
    b = moving_block_bootstrap(oos, block_length=3, iterations=200, seed=42)
    assert a == b
    assert a["bootstrap_samples"] == 200


def test_worst_regime_stress_reweights_worst_month():
    rows = prepare_rows(_payload())
    oos = [row for row in rows if row["block"] != "TRAIN"]
    result = worst_regime_stress(oos, adverse_multiplier=2.0)
    assert result["status"] == "AVAILABLE"
    assert result["adverse_multiplier"] == 2.0
    assert result["worst_calendar_month"] in {"2026-04", "2026-05", "2026-06", "2026-07"}


def test_analyze_preserves_governance_and_blocks_h():
    result = analyze(_payload(), iterations=200, seed=42)
    assert result["status"] == "AVAILABLE"
    assert result["promotion_status"] == "NOT_PROMOTED"
    assert result["leakage_guard"]["entry_state_machine_modified"] is False
    assert result["leakage_guard"]["exit_policy_modified"] is False
    assert result["leakage_guard"]["oos_h_used"] is False
    assert set(result["moving_block_bootstrap_oos_a_d"]) == {"3", "5", "10"}


def test_analyze_requires_all_four_oos_blocks():
    payload = _payload()
    payload["rows"] = [r for r in payload["rows"] if r["block"] != "OOS_D"]
    with pytest.raises(ValueError, match="expected exactly OOS_A-D"):
        analyze(payload, iterations=50, seed=1)
