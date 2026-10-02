from __future__ import annotations

import json

import market_lab.pcr_trade_quality_classifier_v1 as q
import market_lab.pcr_trade_quality_score_v1 as s


def _model(direction: str):
    medians = {name: 0.0 for name in q.FEATURE_NAMES}
    means = {name: 0.0 for name in q.FEATURE_NAMES}
    stds = {name: 1.0 for name in q.FEATURE_NAMES}
    weights = {name: 0.0 for name in q.FEATURE_NAMES}
    weights["confidence_score"] = 1.0
    return {
        "direction": direction,
        "decision_threshold": 0.6,
        "model": {
            "feature_names": list(q.FEATURE_NAMES),
            "medians": medians,
            "means": means,
            "stds": stds,
            "weights": weights,
            "bias": -4.0,
            "training_count": 100,
            "positive_count": 50,
            "negative_count": 50,
        },
    }


def _row(direction: str, score: float, ret: float):
    features = {name: 0.0 for name in q.FEATURE_NAMES}
    features["confidence_score"] = score
    return {
        "block": "OOS_H",
        "direction": direction,
        "session_date": "2026-01-01",
        "stage2_timestamp": "2026-01-01T10:00:00",
        "confirmation_timestamp": "2026-01-01T10:01:00",
        "features": features,
        "net_realized_return_pct": ret,
        "positive_label": 1 if ret > 0 else 0,
    }


def test_scoring_never_retrains_or_recalibrates(tmp_path, monkeypatch):
    model_doc = {
        "status": "AVAILABLE",
        "model_version": q.MODEL_VERSION,
        "model_status": "FROZEN_AFTER_DEVELOPMENT_FOR_UNTOUCHED_OOS_H",
        "confidence_profile": q.CONFIDENCE_PROFILE,
        "entry_rule": q.ENTRY_RULE,
        "contract_selection_rule": q.CONTRACT_RULE,
        "development_blocks": ["TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D"],
        "directions": {"bearish": _model("BEARISH"), "bullish": _model("BULLISH")},
    }
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model_doc), encoding="utf-8")

    monkeypatch.setattr(s, "build_block_rows", lambda *_a, **_k: [
        _row("BEARISH", 6.0, 4.5),
        _row("BEARISH", 1.0, -10.5),
        _row("BULLISH", 6.0, 4.5),
    ])
    result = s.score(path, "m", "b", "e", "p", block_name="OOS_H")

    assert result["block_role"] == "HOLDOUT_DIAGNOSTIC_OR_VALIDATION"
    assert result["leakage_guard"]["model_retrained_on_scored_block"] is False
    assert result["leakage_guard"]["threshold_recalibrated_on_scored_block"] is False
    assert result["combined"]["allowed_count"] == 2
    assert result["combined"]["rejected_count"] == 1
