from datetime import datetime, timedelta

from market_lab.historical_positioning import (
    CombinedStrikeObservation,
    PositioningConfig,
    PositioningState,
    SidePoint,
    build_positioning_index,
    build_strike_positioning,
    classify_side,
)


def test_side_classifier_matches_live_semantics():
    c = PositioningConfig()
    assert classify_side(premium_change_pct=1, oi_change_pct=2, config=c) == PositioningState.LONG_BUILDUP
    assert classify_side(premium_change_pct=-1, oi_change_pct=2, config=c) == PositioningState.SHORT_BUILDUP
    assert classify_side(premium_change_pct=-1, oi_change_pct=-2, config=c) == PositioningState.LONG_UNWINDING
    assert classify_side(premium_change_pct=1, oi_change_pct=-2, config=c) == PositioningState.SHORT_COVERING


def test_strong_bearish_same_strike():
    t0 = datetime(2026, 9, 8, 10, 0)
    t1 = t0 + timedelta(minutes=5)
    points = [
        SidePoint(t0, "CE1", 24000, "CE", 100, 1000),
        SidePoint(t1, "CE1", 24000, "CE", 90, 1200),
        SidePoint(t0, "PE1", 24000, "PE", 100, 1000),
        SidePoint(t1, "PE1", 24000, "PE", 115, 1300),
    ]
    idx = build_positioning_index(points)
    out = build_strike_positioning(
        ce_current=points[1], pe_current=points[3], horizon_minutes=5, index=idx, config=PositioningConfig()
    )
    assert out.ce.state == PositioningState.SHORT_BUILDUP
    assert out.pe.state == PositioningState.LONG_BUILDUP
    assert out.combined == CombinedStrikeObservation.STRONG_BEARISH


def test_strong_bullish_same_strike():
    t0 = datetime(2026, 9, 8, 10, 0)
    t1 = t0 + timedelta(minutes=5)
    points = [
        SidePoint(t0, "CE1", 24000, "CE", 100, 1000),
        SidePoint(t1, "CE1", 24000, "CE", 115, 1300),
        SidePoint(t0, "PE1", 24000, "PE", 100, 1000),
        SidePoint(t1, "PE1", 24000, "PE", 90, 1200),
    ]
    idx = build_positioning_index(points)
    out = build_strike_positioning(
        ce_current=points[1], pe_current=points[3], horizon_minutes=5, index=idx, config=PositioningConfig()
    )
    assert out.ce.state == PositioningState.LONG_BUILDUP
    assert out.pe.state == PositioningState.SHORT_BUILDUP
    assert out.combined == CombinedStrikeObservation.STRONG_BULLISH


def test_missing_exact_baseline_is_unavailable_not_zero():
    t1 = datetime(2026, 9, 8, 10, 5)
    ce = SidePoint(t1, "CE1", 24000, "CE", 100, 1000)
    pe = SidePoint(t1, "PE1", 24000, "PE", 100, 1000)
    out = build_strike_positioning(
        ce_current=ce, pe_current=pe, horizon_minutes=5, index=build_positioning_index([ce, pe]), config=PositioningConfig()
    )
    assert out.ce.state == PositioningState.UNAVAILABLE
    assert out.pe.state == PositioningState.UNAVAILABLE
    assert out.combined == CombinedStrikeObservation.UNAVAILABLE
