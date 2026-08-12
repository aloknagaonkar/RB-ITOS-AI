import pandas as pd

from red_bar_lab.intelligence.buy_sell_strength import BuySellStrengthEngine
from red_bar_lab.intelligence.institutional_confidence import InstitutionalConfidenceEngine
from red_bar_lab.intelligence.institutional_flow import InstitutionalOptionFlowEngine
from red_bar_lab.intelligence.oi_velocity import OIVelocityEngine
from red_bar_lab.intelligence.premium_flow import PremiumFlowEngine
from red_bar_lab.intelligence.strike_rotation import StrikeRotationEngine


def _chain(call_ltp, call_oi, put_ltp, put_oi, strike=25000):
    return pd.DataFrame([
        {
            "strike": strike,
            "call_ltp": call_ltp,
            "call_oi": call_oi,
            "call_volume": 120000,
            "put_ltp": put_ltp,
            "put_oi": put_oi,
            "put_volume": 110000,
        }
    ])


def test_oi_velocity_uses_point_in_time_windows():
    base = pd.Timestamp("2026-08-12T09:15:00+05:30")
    snapshots = [
        (base, _chain(100, 100000, 100, 100000)),
        (base + pd.Timedelta(minutes=5), _chain(105, 110000, 95, 105000)),
        (base + pd.Timedelta(minutes=15), _chain(115, 130000, 90, 120000)),
    ]
    ce = next(r for r in OIVelocityEngine.evaluate(snapshots) if r.option_type == "CE")
    assert round(ce.change_15m_pct, 1) == 30.0
    assert ce.state in {"RISING", "ACCELERATING_UP"}


def test_premium_flow_detects_expansion():
    base = pd.Timestamp("2026-08-12T09:15:00+05:30")
    snapshots = [
        (base, _chain(100, 100000, 100, 100000)),
        (base + pd.Timedelta(minutes=5), _chain(110, 110000, 95, 105000)),
        (base + pd.Timedelta(minutes=6), _chain(114, 112000, 94, 106000)),
    ]
    ce = next(r for r in PremiumFlowEngine.evaluate(snapshots) if r.option_type == "CE")
    assert ce.change_5m_pct > 0
    assert ce.state.startswith("EXPANSION")


def test_rotation_detects_upward_oi_migration():
    previous = pd.DataFrame([
        {"strike": 25000, "call_oi": 200000, "put_oi": 200000},
        {"strike": 25100, "call_oi": 100000, "put_oi": 100000},
    ])
    current = pd.DataFrame([
        {"strike": 25000, "call_oi": 100000, "put_oi": 100000},
        {"strike": 25100, "call_oi": 250000, "put_oi": 250000},
    ])
    result = StrikeRotationEngine.evaluate(current, previous)
    assert result.state == "UPWARD_ROTATION"
    assert result.call_shift_points > 0
    assert result.put_shift_points > 0


def test_strength_and_ici_remain_advisory():
    previous = _chain(100, 100000, 100, 100000)
    current = _chain(112, 120000, 90, 125000)
    flow = InstitutionalOptionFlowEngine.evaluate_frames(current, previous)
    strength = BuySellStrengthEngine.evaluate(flow.rows)
    rotation = StrikeRotationEngine.evaluate(current, previous)
    ici = InstitutionalConfidenceEngine.evaluate(strength, flow.rows, (), (), rotation)

    assert 0 <= strength.buying_strength_pct <= 100
    assert 0 <= strength.selling_strength_pct <= 100
    assert -100 <= strength.net_strength <= 100
    assert 0 <= ici.score <= 100
    assert ici.execution_impact == "NONE"


def test_no_directional_flow_keeps_ici_neutral():
    strength = BuySellStrengthEngine.evaluate(())
    rotation = StrikeRotationEngine.evaluate(pd.DataFrame(), pd.DataFrame())
    ici = InstitutionalConfidenceEngine.evaluate(strength, (), (), (), rotation)
    assert ici.direction == "NEUTRAL"
    assert ici.execution_impact == "NONE"
