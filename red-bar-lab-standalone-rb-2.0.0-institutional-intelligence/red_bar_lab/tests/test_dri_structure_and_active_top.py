from types import SimpleNamespace

from red_bar_lab.execution.directional_regime_native_signal import (
    bundle_to_native_signal,
)
from red_bar_lab.execution.opportunity_engine import (
    OpportunityIntelligenceEngine,
)
from red_bar_lab.ui.active_trade_views import (
    _active_ranking_from_queue,
)


def candidate():
    return SimpleNamespace(
        total_score=100.0,
        spread_score=15.0,
        liquidity_score=20.0,
        volume_score=15.0,
        oi_score=10.0,
        vwap_score=10.0,
        ema_score=10.0,
        momentum_score=10.0,
        contract=SimpleNamespace(option_type="PE"),
    )


def bearish_bundle():
    return {
        "bundle_id": "BND-1",
        "direction": "BEARISH",
        "current_regime": "BEARISH",
        "detected_at": "2026-08-14T09:00:00+00:00",
        "fresh_until": "2026-08-14T09:15:00+00:00",
        "primary_setup_type": "BEARISH_EMA_LOSS",
        "trigger_level": 24367.55,
        "invalidation_level": 24375.0,
        "red_bar_alignment": "NOT_AVAILABLE",
    }


def test_bearish_dri_geometry_uses_invalidation_as_high():
    signal = bundle_to_native_signal(
        bearish_bundle(),
        now="2026-08-14T09:05:00+00:00",
    )
    assert signal["confirmation_high"] == 24375.0
    assert signal["confirmation_low"] == 24367.55


def test_dri_not_available_red_bar_does_not_block():
    signal = bundle_to_native_signal(
        bearish_bundle(),
        now="2026-08-14T09:05:00+00:00",
    )
    result = OpportunityIntelligenceEngine(
        minimum_opportunity_score=0.0,
    ).evaluate(
        signal=signal,
        candidate=candidate(),
        spot_price=24370.0,
        signal_age_seconds=60.0,
        opposite_red_bar_confirmed=True,
    )
    assert result.structure_valid is True
    assert result.opposite_red_bar is False
    assert "STRUCTURE_INVALID" not in result.reason
    assert "OPPOSITE_RED_BAR" not in result.reason


def test_dri_structure_blocks_only_beyond_invalidation():
    signal = bundle_to_native_signal(
        bearish_bundle(),
        now="2026-08-14T09:05:00+00:00",
    )
    result = OpportunityIntelligenceEngine(
        minimum_opportunity_score=0.0,
    ).evaluate(
        signal=signal,
        candidate=candidate(),
        spot_price=24376.0,
        signal_age_seconds=60.0,
        opposite_red_bar_confirmed=False,
    )
    assert result.structure_valid is False
    assert "STRUCTURE_INVALID" in result.reason


def test_active_top_requires_active_queue_and_deduplicates():
    ranking = [
        {
            "signal_id": "DRI-1",
            "candidate_id": "C1",
            "candidate_symbol": "NIFTY 24350 PE",
            "eligible": True,
            "selection_score": 80.0,
            "candidate_score": 100.0,
        },
        {
            "signal_id": "DRI-1",
            "candidate_id": "C1",
            "candidate_symbol": "NIFTY 24350 PE",
            "eligible": True,
            "selection_score": 79.0,
            "candidate_score": 100.0,
        },
        {
            "signal_id": "OLD",
            "candidate_id": "OLD-C",
            "candidate_symbol": "NIFTY 24400 PE",
            "eligible": True,
            "selection_score": 100.0,
            "candidate_score": 100.0,
        },
    ]
    queue = [{
        "signal_id": "DRI-1",
        "candidate_id": "C1",
        "candidate_symbol": "NIFTY 24350 PE",
        "status": "APPROVED",
    }]
    rows = _active_ranking_from_queue(ranking, queue)
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == "C1"
    assert rows[0]["selection_score"] == 80.0


def test_active_top_empty_without_active_queue():
    assert _active_ranking_from_queue(
        [{"eligible": True, "candidate_symbol": "OLD"}],
        [],
    ) == []
