import pandas as pd

from red_bar_lab.intelligence.shadow import ShadowIntelligenceEngine
from red_bar_lab.storage.database import RedBarDatabase
from red_bar_lab.config import RedBarSettings


def _chain():
    return pd.DataFrame([
        {
            "call_oi_change": 1000.0,
            "put_oi_change": 8000.0,
        },
        {
            "call_oi_change": 500.0,
            "put_oi_change": 4000.0,
        },
    ])


def _candidate():
    return {
        "Type": "CE",
        "Delta": 0.48,
        "Gamma": 0.002,
        "IV": 16.0,
        "Theta": -4.0,
        "Vega": 8.0,
    }


def _features():
    return {
        "market_context": {
            "trend_5m": "BULLISH",
        },
        "volume_structure": {
            "bullish_structure_score": 8.0,
            "bearish_structure_score": 3.0,
            "structure_state": "BULLISH_STRUCTURE",
            "relative_volume_20m": 1.8,
            "volume_trend_5m": "RISING",
        },
    }


def test_shadow_engine_is_observation_only_and_can_agree():
    result = ShadowIntelligenceEngine().evaluate(
        current_decision="BUY CE",
        direction="BULLISH",
        spot_price=24620.0,
        pcr_oi=1.22,
        call_wall=24600.0,
        put_wall=24500.0,
        max_pain=24600.0,
        chain_rows=_chain(),
        best_candidate=_candidate(),
        market_features=_features(),
        open_orders=[],
    )
    assert result.shadow_decision == "BUY CE"
    assert result.agreement == "YES"
    assert result.portfolio_conflict is False
    assert all(
        item.execution_impact == "NONE"
        for item in result.modules
    )


def test_shadow_portfolio_conflict_suggests_reverse_but_does_not_execute():
    result = ShadowIntelligenceEngine().evaluate(
        current_decision="BUY CE",
        direction="BULLISH",
        spot_price=24620.0,
        pcr_oi=1.22,
        call_wall=24600.0,
        put_wall=24500.0,
        max_pain=24600.0,
        chain_rows=_chain(),
        best_candidate=_candidate(),
        market_features=_features(),
        open_orders=[
            {
                "status": "OPEN",
                "option_type": "PE",
            }
        ],
    )
    assert result.portfolio_conflict is True
    assert result.portfolio_action == "REVERSE"
    portfolio = next(
        item for item in result.modules
        if item.module == "Portfolio"
    )
    assert portfolio.recommendation == "REVERSE"
    assert portfolio.execution_impact == "NONE"


def test_shadow_evaluation_persists(tmp_path):
    settings = RedBarSettings(
        artifacts_root=tmp_path / "artifacts",
    )
    db = RedBarDatabase(settings.database_path)
    db.initialize()
    db.insert_shadow_intelligence_evaluation(
        {
            "signal_id": "RB-TEST",
            "trading_date": "2026-08-10",
            "current_decision": "BUY CE",
            "shadow_decision": "WAIT",
            "shadow_confidence": 61.0,
            "agreement": "PARTIAL",
            "portfolio_conflict": False,
            "portfolio_action": "ALLOW",
            "modules": [
                {
                    "module": "PCR",
                    "status": "NEUTRAL",
                    "execution_impact": "NONE",
                }
            ],
            "evaluated_at": "2026-08-10T12:00:00+05:30",
        }
    )
    rows = db.read_shadow_intelligence_evaluations(
        signal_id="RB-TEST"
    )
    assert len(rows) == 1
    assert rows[0]["execution_impact"] == "NONE"
    assert rows[0]["modules"][0]["module"] == "PCR"


def test_current_execution_engine_uses_persisted_shadow_evidence_without_importing_shadow_engine():
    from pathlib import Path
    path = (
        Path(__file__).resolve().parents[1]
        / "execution"
        / "automation.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "ShadowIntelligenceEngine" not in text
    assert "read_shadow_intelligence_evaluations" in text
    assert "InstitutionalExecutionCommittee" in text
