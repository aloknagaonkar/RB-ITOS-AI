from red_bar_lab.services.nifty_futures_positioning import (
    INSUFFICIENT_DATA,
    LONG_BUILDUP,
    NEUTRAL,
    NiftyFuturesPositioning,
)
from red_bar_lab.services.nifty_futures_positioning_strength import (
    INSUFFICIENT,
    MODERATE,
    STRONG,
    WEAK,
    assess_nifty_futures_positioning_strength,
    futures_positioning_strength_log_values,
)


def _positioning(
    *,
    status="READY",
    state=LONG_BUILDUP,
    price_change_pct=0.05,
    oi_change_pct=0.06,
    relative_volume=1.3,
):
    return NiftyFuturesPositioning(
        status=status,
        reason="test",
        state=state,
        price_change_pct=price_change_pct,
        oi_change_pct=oi_change_pct,
        relative_volume=relative_volume,
    )


def test_strong_requires_threshold_changes_and_strong_relative_volume():
    result = assess_nifty_futures_positioning_strength(_positioning())

    assert result.status == "READY"
    assert result.strength == STRONG


def test_moderate_accepts_baseline_level_participation():
    result = assess_nifty_futures_positioning_strength(
        _positioning(relative_volume=0.9)
    )

    assert result.strength == MODERATE


def test_weak_when_relative_volume_is_below_moderate_threshold():
    result = assess_nifty_futures_positioning_strength(
        _positioning(relative_volume=0.79)
    )

    assert result.strength == WEAK


def test_weak_when_price_or_oi_change_is_too_small():
    price_weak = assess_nifty_futures_positioning_strength(
        _positioning(price_change_pct=0.019, relative_volume=2.0)
    )
    oi_weak = assess_nifty_futures_positioning_strength(
        _positioning(oi_change_pct=0.019, relative_volume=2.0)
    )

    assert price_weak.strength == WEAK
    assert oi_weak.strength == WEAK


def test_neutral_state_has_no_directional_strength():
    result = assess_nifty_futures_positioning_strength(
        _positioning(state=NEUTRAL, relative_volume=2.0)
    )

    assert result.status == "READY"
    assert result.strength == WEAK


def test_missing_relative_volume_is_insufficient():
    result = assess_nifty_futures_positioning_strength(
        _positioning(relative_volume=None)
    )

    assert result.status == INSUFFICIENT_DATA
    assert result.strength == INSUFFICIENT


def test_incomplete_positioning_is_insufficient():
    result = assess_nifty_futures_positioning_strength(
        _positioning(status=INSUFFICIENT_DATA, price_change_pct=None)
    )

    assert result.status == INSUFFICIENT_DATA
    assert result.strength == INSUFFICIENT


def test_custom_thresholds_are_applied_deterministically():
    result = assess_nifty_futures_positioning_strength(
        _positioning(price_change_pct=0.06, oi_change_pct=0.06, relative_volume=1.1),
        price_threshold_pct=0.05,
        oi_threshold_pct=0.05,
        moderate_relative_volume=1.0,
        strong_relative_volume=1.5,
    )

    assert result.strength == MODERATE


def test_log_values_are_stable():
    result = assess_nifty_futures_positioning_strength(_positioning())

    assert futures_positioning_strength_log_values(result) == (
        "READY",
        "Directional price and OI change are confirmed by strong relative volume.",
        "STRONG",
        "LONG_BUILDUP",
        "0.0500",
        "0.0600",
        "1.3000",
    )
