from market_lab.midpoint_failure_diagnostics_v2_2 import (
    correct_directional_momentum,
    exact_oi_transition,
    prepare_rows,
)

def row(direction, cp, momentum, progress, acceptance, ce, pe):
    return {
        "block": "TRAIN",
        "session_date": "2026-01-01",
        "setup_type": "RED_TEST" if direction == "BEARISH" else "GREEN_TEST",
        "primary_outcome": "X",
        "outcome_label": "CONTINUATION",
        "direction": direction,
        "checkpoint_minutes": cp,
        "price_features": {
            "momentum_5m": momentum,
            "progress_points": progress,
            "acceptance_pct": acceptance,
        },
        "oi": {"ce_state": ce, "pe_state": pe, "support_level": "STRONG"},
    }

def test_bearish_momentum_double_inversion_is_undone():
    r = row("BEARISH", 1, -20.0, 2.0, 100.0, "SHORT_BUILDUP", "LONG_BUILDUP")
    assert correct_directional_momentum(r) == 20.0

def test_bullish_momentum_is_not_flipped():
    r = row("BULLISH", 1, 20.0, 2.0, 100.0, "LONG_BUILDUP", "SHORT_BUILDUP")
    assert correct_directional_momentum(r) == 20.0

def test_exact_transition_contains_all_four_state_names_when_present():
    a = row("BEARISH", 1, -20, 5, 100, "SHORT_BUILDUP", "LONG_BUILDUP")
    b = row("BEARISH", 3, -5, -2, 50, "SHORT_COVERING", "LONG_UNWINDING")
    x = exact_oi_transition(a, b)
    assert x == (
        "CE:SHORT_BUILDUP->SHORT_COVERING;"
        "PE:LONG_BUILDUP->LONG_UNWINDING"
    )

def test_prepare_rows_derives_giveback_and_progress_decay():
    rows = [
        row("BEARISH", 0, -10, 1, 100, "SHORT_BUILDUP", "LONG_BUILDUP"),
        row("BEARISH", 1, -15, 6, 100, "SHORT_BUILDUP", "LONG_BUILDUP"),
        row("BEARISH", 3, -2, -3, 50, "SHORT_COVERING", "LONG_UNWINDING"),
    ]
    out = prepare_rows(rows)
    t3 = [r for r in out if r["checkpoint_minutes"] == 3][0]
    pf = t3["price_features"]
    assert pf["giveback_from_best_checkpoint_points"] == 9.0
    assert pf["progress_change_from_previous_checkpoint"] == -9.0
    assert pf["acceptance_change_from_previous_checkpoint"] == -50.0
    assert "SHORT_COVERING" in t3["exact_oi_transition_t1_to_t3"]
    assert pf["momentum_5m_directional"] == 2.0
