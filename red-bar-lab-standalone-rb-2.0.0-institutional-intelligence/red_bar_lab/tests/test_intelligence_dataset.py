import pytest
from red_bar_lab.intelligence.dataset import (
    ENTRY_FEATURE_COLUMNS,
    FORBIDDEN_PREDICTION_COLUMNS,
    build_training_rows,
    label_frame,
    prediction_feature_frame,
    validate_no_lookahead_features,
)


def _signals():
    return [{
        "signal_id":"RB-AI",
        "trading_date":"2026-08-07",
        "level_type":"NEXT_RED_CANDLE",
        "level_value":100.0,
        "direction":"BEARISH",
        "cross_timestamp":"2026-08-07T10:05:00+05:30",
        "confirmation_timestamp":"2026-08-07T10:10:00+05:30",
        "underlying_entry":99.0,
        "cross_open":100.5,"cross_high":101.0,
        "cross_low":98.0,"cross_close":99.5,
        "confirmation_open":99.5,"confirmation_high":100.0,
        "confirmation_low":98.5,"confirmation_close":99.0,
        "confirmation_delay_minutes":5,
    }]


def _trades():
    rows = []
    for i in range(10):
        rows.append({
            "signal_id":"RB-AI","status":"CLOSED",
            "exit_model":"FIXED_TARGET" if i < 4 else (
                "RISK_REWARD" if i < 7 else (
                    "TRAILING_STOP" if i < 9 else "BREAK_EVEN_1R"
                )
            ),
            "model_parameter":str(i),
            "points":float(i+1),
            "exit_timestamp":f"2026-08-07T10:{20+i:02d}:00+05:30",
            "exit_price":98.0-i,
            "session_mfe_points":50.0,
            "session_mae_points":3.0,
        })
    rows.append({
        "signal_id":"RB-AI","status":"CLOSED",
        "exit_model":"EOD_HOLD","model_parameter":"EOD",
        "points":30.0,
        "exit_timestamp":"2026-08-07T15:30:00+05:30",
        "exit_price":69.0,
        "session_mfe_points":60.0,
        "session_mae_points":3.0,
    })
    return rows


def test_dataset_separates_features_and_labels():
    rows = build_training_rows(_signals(), _trades())
    assert len(rows) == 1
    features = prediction_feature_frame(rows)
    labels = label_frame(rows)
    assert set(features.columns) == set(ENTRY_FEATURE_COLUMNS)
    assert "mfe_points" not in features.columns
    assert "best_actionable_points" not in features.columns
    assert labels.iloc[0]["mfe_points"] == 50.0
    assert labels.iloc[0]["best_actionable_points"] == 10.0
    assert labels.iloc[0]["benchmark_final_points"] == 30.0


def test_lookahead_guard():
    with pytest.raises(ValueError):
        validate_no_lookahead_features(["entry_price", "mfe_points"])


def test_forbidden_set():
    assert "mfe_points" in FORBIDDEN_PREDICTION_COLUMNS
    assert "live_points" in FORBIDDEN_PREDICTION_COLUMNS



def test_market_context_fields_are_entry_features():
    assert "gap_pct" in ENTRY_FEATURE_COLUMNS
    assert "atr14_5m" in ENTRY_FEATURE_COLUMNS
    assert "trend_5m" in ENTRY_FEATURE_COLUMNS
    assert "realized_volatility_30m_pct" in ENTRY_FEATURE_COLUMNS



def test_rb072_volume_structure_fields_are_entry_features():
    assert "relative_volume_20m" in ENTRY_FEATURE_COLUMNS
    assert "price_volume_state" in ENTRY_FEATURE_COLUMNS
    assert "compression_ratio_20m" in ENTRY_FEATURE_COLUMNS
    assert "structure_state" in ENTRY_FEATURE_COLUMNS
    assert "bullish_structure_score" in ENTRY_FEATURE_COLUMNS



def test_rb074_options_are_intelligence_entry_features():
    assert "options_entry_aligned" in ENTRY_FEATURE_COLUMNS
    assert "pcr_oi" in ENTRY_FEATURE_COLUMNS
    assert "atm_strike" in ENTRY_FEATURE_COLUMNS
    assert "atm_call_delta" in ENTRY_FEATURE_COLUMNS
    assert "atm_put_iv" in ENTRY_FEATURE_COLUMNS
