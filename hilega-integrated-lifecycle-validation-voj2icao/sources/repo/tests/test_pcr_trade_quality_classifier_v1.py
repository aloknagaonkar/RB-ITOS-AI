from __future__ import annotations

import json
from pathlib import Path

import pytest

import market_lab.pcr_trade_quality_classifier_v1 as q


def _row(block: str, direction: str, i: int, positive: bool) -> dict:
    # Make the first feature strongly informative while keeping every feature present.
    features = {name: 0.0 for name in q.FEATURE_NAMES}
    features["confidence_score"] = 6.0 if positive else 3.0
    features["spot_momentum_5m"] = (10.0 + i * 0.01) if positive else (-10.0 - i * 0.01)
    features["confirmation_offset_minutes"] = float(i % 6)
    return {
        "block": block,
        "direction": direction,
        "session_date": f"2026-01-{(i % 20) + 1:02d}",
        "stage2_timestamp": f"2026-01-01T10:{i % 60:02d}:00",
        "confirmation_timestamp": f"2026-01-01T10:{i % 60:02d}:00",
        "features": features,
        "net_realized_return_pct": 4.5 if positive else -10.5,
        "positive_label": 1 if positive else 0,
    }


def test_training_rejects_holdout_block(monkeypatch):
    monkeypatch.setattr(q, "build_block_rows", lambda *args, **kwargs: [])
    with pytest.raises(ValueError, match="development-only"):
        q.train([("OOS_G", "m", "b", "e", "p")])


def test_training_freezes_direction_models_from_development_only(monkeypatch):
    def fake_build(name, *_args):
        rows = []
        for direction in ("BEARISH", "BULLISH"):
            for i in range(12):
                rows.append(_row(name, direction, i, i % 2 == 0))
        return rows

    monkeypatch.setattr(q, "build_block_rows", fake_build)
    blocks = [(name, "m", "b", "e", "p") for name in ("TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D")]
    result = q.train(blocks)

    assert result["status"] == "AVAILABLE"
    assert result["model_version"] == q.MODEL_VERSION
    assert result["development_blocks"] == ["TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"]
    assert result["leakage_guard"]["holdout_blocks_e_f_g_h_allowed_for_training"] is False
    assert result["leakage_guard"]["future_return_features_used"] is False
    for side in ("bearish", "bullish"):
        assert result["directions"][side]["decision_threshold"] in q.THRESHOLD_GRID
        assert result["directions"][side]["model"]["training_count"] == 60
        assert result["directions"][side]["oof"]["prediction_count"] == 60
