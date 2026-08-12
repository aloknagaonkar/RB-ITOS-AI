from types import SimpleNamespace

import pandas as pd

from red_bar_lab.intelligence.buy_sell_strength import BuySellStrengthEngine
from red_bar_lab.intelligence.contract_quality import ContractQualityEngine
from red_bar_lab.intelligence.institutional_confidence import InstitutionalConfidenceEngine


def _chain():
    return pd.DataFrame(
        [
            {"strike": 24000, "call_ltp": 105, "put_ltp": 6, "call_oi": 1500000, "put_oi": 1200000, "call_volume": 900000, "put_volume": 800000},
            {"strike": 24100, "call_ltp": 52, "put_ltp": 28, "call_oi": 1800000, "put_oi": 1700000, "call_volume": 1100000, "put_volume": 1000000},
            {"strike": 24150, "call_ltp": 38, "put_ltp": 39, "call_oi": 2100000, "put_oi": 2200000, "call_volume": 1400000, "put_volume": 1500000},
            {"strike": 24200, "call_ltp": 25, "put_ltp": 58, "call_oi": 1700000, "put_oi": 1900000, "call_volume": 1000000, "put_volume": 1200000},
            {"strike": 22000, "call_ltp": 2100, "put_ltp": 0.9, "call_oi": 400000, "put_oi": 25000, "call_volume": 100000, "put_volume": 20000},
        ]
    )


def test_contract_quality_prefers_liquid_near_atm_over_tiny_far_otm_premium():
    rows = ContractQualityEngine.evaluate(_chain())
    by_key = {(row.strike, row.option_type): row for row in rows}

    assert by_key[(24150.0, "PE")].inferred_atm == 24150.0
    assert by_key[(24150.0, "PE")].quality_score > by_key[(22000.0, "PE")].quality_score
    assert by_key[(24150.0, "PE")].eligible is True
    assert by_key[(22000.0, "PE")].eligible is False
    assert by_key[(22000.0, "PE")].weight >= 0.10


def test_buy_sell_strength_downweights_low_quality_far_otm_evidence():
    quality = {(row.strike, row.option_type): row for row in ContractQualityEngine.evaluate(_chain())}
    flow_rows = (
        SimpleNamespace(strike=24150.0, option_type="CE", confidence_pct=60.0, behaviour="LONG_BUILDUP", directional_bias="BULLISH"),
        SimpleNamespace(strike=22000.0, option_type="PE", confidence_pct=100.0, behaviour="LONG_BUILDUP", directional_bias="BEARISH"),
    )
    velocities = {
        (24150.0, "CE"): SimpleNamespace(change_5m_pct=5.0),
        (22000.0, "PE"): SimpleNamespace(change_5m_pct=30.0),
    }

    raw = BuySellStrengthEngine.evaluate(flow_rows, velocities)
    weighted = BuySellStrengthEngine.evaluate(flow_rows, velocities, quality)

    assert weighted.buying_strength_pct > raw.buying_strength_pct
    assert "Quality-weighted contribution used" in weighted.reason


def test_ici_quality_weighting_never_changes_execution_authority():
    quality = {(row.strike, row.option_type): row for row in ContractQualityEngine.evaluate(_chain())}
    strength = SimpleNamespace(net_strength=10.0, breadth_pct=60.0)
    flow = (
        SimpleNamespace(strike=24150.0, option_type="PE", directional_bias="BULLISH"),
        SimpleNamespace(strike=22000.0, option_type="PE", directional_bias="BEARISH"),
    )
    velocity = (
        SimpleNamespace(strike=24150.0, option_type="PE", change_5m_pct=5.0, state="RISING"),
        SimpleNamespace(strike=22000.0, option_type="PE", change_5m_pct=30.0, state="ACCELERATING_UP"),
    )
    premium = (
        SimpleNamespace(strike=24150.0, option_type="PE", change_5m_pct=4.0, strength_pct=55.0),
        SimpleNamespace(strike=22000.0, option_type="PE", change_5m_pct=20.0, strength_pct=100.0),
    )
    rotation = SimpleNamespace(confidence_pct=10.0)

    result = InstitutionalConfidenceEngine.evaluate(
        strength, flow, velocity, premium, rotation, quality
    )

    assert result.execution_impact == "NONE"
    assert result.components["Premium Flow"] < 100.0
    assert 0.0 <= result.score <= 100.0
