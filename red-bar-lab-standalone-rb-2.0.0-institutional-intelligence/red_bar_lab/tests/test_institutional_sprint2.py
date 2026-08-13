from __future__ import annotations

import pandas as pd

from red_bar_lab.intelligence.buy_sell_strength import BuySellStrengthEngine
from red_bar_lab.intelligence.institutional_confidence import InstitutionalConfidenceEngine
from red_bar_lab.intelligence.institutional_sprint2 import InstitutionalSprint2Service
from red_bar_lab.intelligence.oi_velocity import OIVelocityEngine
from red_bar_lab.intelligence.premium_flow import PremiumFlowEngine
from red_bar_lab.intelligence.strike_rotation import StrikeRotationEngine


def _chain(call_oi, put_oi, call_ltp, put_ltp):
    return pd.DataFrame(
        {
            "strike": [24900.0, 25000.0, 25100.0],
            "call_oi": call_oi,
            "put_oi": put_oi,
            "call_ltp": call_ltp,
            "put_ltp": put_ltp,
        }
    )


def _snapshots():
    return [
        (pd.Timestamp("2026-08-12 10:00:00"), _chain([100, 200, 300], [300, 200, 100], [120, 80, 50], [45, 75, 115])),
        (pd.Timestamp("2026-08-12 10:10:00"), _chain([120, 230, 340], [330, 240, 120], [130, 88, 54], [48, 82, 123])),
        (pd.Timestamp("2026-08-12 10:14:00"), _chain([135, 250, 370], [350, 265, 135], [136, 94, 58], [51, 87, 130])),
        (pd.Timestamp("2026-08-12 10:15:00"), _chain([150, 270, 400], [370, 290, 150], [142, 100, 62], [54, 92, 138])),
    ]


def test_oi_velocity_uses_persisted_time_windows():
    rows = OIVelocityEngine.evaluate(_snapshots(), strikes=[25000.0])
    assert len(rows) == 2
    ce = next(row for row in rows if row.option_type == "CE")
    assert ce.change_1m_pct == 8.0
    assert ce.change_5m_pct == 17.391
    assert ce.change_15m_pct == 35.0
    assert ce.state in {"RISING", "ACCELERATING_UP"}


def test_premium_flow_detects_expansion_from_snapshot_history():
    rows = PremiumFlowEngine.evaluate(_snapshots())
    ce = next(row for row in rows if row.strike == 25000.0 and row.option_type == "CE")
    assert ce.change_1m_pct == 6.383
    assert ce.change_5m_pct == 13.636
    assert ce.change_15m_pct == 25.0
    assert ce.state in {"EXPANSION", "EXPANSION_ACCELERATING"}
    assert ce.strength_pct > 0


def test_strike_rotation_reports_direction_and_confidence():
    previous = _chain([100, 200, 300], [300, 200, 100], [1, 1, 1], [1, 1, 1])
    current = _chain([50, 150, 500], [100, 200, 400], [1, 1, 1], [1, 1, 1])
    result = StrikeRotationEngine.evaluate(current, previous)
    assert result.call_shift_points is not None
    assert result.put_shift_points is not None
    assert result.confidence_pct > 0
    assert result.state in {"UPWARD_ROTATION", "DIVERGENT_ROTATION"}


def test_empty_strength_and_confidence_are_safe_and_advisory_only():
    strength = BuySellStrengthEngine.evaluate(())
    rotation = StrikeRotationEngine.evaluate(pd.DataFrame(), pd.DataFrame())
    confidence = InstitutionalConfidenceEngine.evaluate(strength, (), (), (), rotation)
    assert strength.buying_strength_pct == 0.0
    assert strength.selling_strength_pct == 0.0
    assert strength.neutral_strength_pct == 100.0
    assert confidence.direction == "NEUTRAL"
    assert confidence.execution_impact == "NONE"
    assert confidence.score == 0.0


def test_confidence_never_receives_execution_authority():
    class Strength:
        net_strength = 40.0
        breadth_pct = 80.0

    class Flow:
        directional_bias = "BULLISH"

    class Velocity:
        change_5m_pct = 5.0
        state = "ACCELERATING_UP"

    class Premium:
        change_5m_pct = 4.0
        strength_pct = 75.0

    class Rotation:
        confidence_pct = 60.0

    confidence = InstitutionalConfidenceEngine.evaluate(
        Strength(), (Flow(),), (Velocity(),), (Premium(),), Rotation()
    )
    assert confidence.direction == "BULLISH"
    assert confidence.score > 0
    assert confidence.execution_impact == "NONE"


def test_sprint2_loads_only_required_point_in_time_artifacts():
    class Database:
        def read_option_chain_history(self, *args, **kwargs):
            return [
                {
                    "collector_mode": "ONLINE",
                    "snapshot_timestamp": pd.Timestamp("2026-08-12 10:00:00")
                    + pd.Timedelta(minutes=minute),
                    "chain_artifact_path": f"snap-{minute}.csv",
                }
                for minute in range(31)
            ]

    service = InstitutionalSprint2Service(Database())
    reads = []

    def fake_artifact(path_value):
        reads.append(str(path_value))
        return _chain(
            [100, 200, 300],
            [300, 200, 100],
            [120, 80, 50],
            [45, 75, 115],
        )

    service._artifact = fake_artifact
    snapshots = service._snapshots("NIFTY", "2026-08-12")

    timestamps = [timestamp for timestamp, _, _ in snapshots]
    assert timestamps == [
        pd.Timestamp("2026-08-12 10:15:00"),
        pd.Timestamp("2026-08-12 10:25:00"),
        pd.Timestamp("2026-08-12 10:29:00"),
        pd.Timestamp("2026-08-12 10:30:00"),
    ]
    assert set(reads) == {
        "snap-15.csv",
        "snap-25.csv",
        "snap-29.csv",
        "snap-30.csv",
    }
    assert len(reads) == 4
