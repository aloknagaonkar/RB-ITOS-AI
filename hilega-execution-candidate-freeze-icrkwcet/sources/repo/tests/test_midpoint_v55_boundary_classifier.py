from market_lab.midpoint_strategy.boundary_classifier import (
    MidpointBoundaryClassifierV55,
    OTHER_FRESH_A,
)
from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.structure import ReferenceStructure


def red_ref():
    return ReferenceStructure(
        session_date="2026-09-28",
        reference_type="RED",
        start_timestamp="2026-09-28T09:20:00+05:30",
        end_timestamp="2026-09-28T09:24:00+05:30",
        high=22951.8,
        low=22914.1,
    )


def green_ref():
    return ReferenceStructure(
        session_date="2026-09-28",
        reference_type="GREEN",
        start_timestamp="2026-09-28T09:45:00+05:30",
        end_timestamp="2026-09-28T09:49:00+05:30",
        high=22878.6,
        low=22856.3,
    )


def obs(ts, close, raw_diff):
    fv = 23000.0
    return FamilyBObservation(
        timestamp=ts,
        close=close,
        futures_price=fv + raw_diff,
        futures_vwap=fv,
    )


def test_bearish_mature_false_a_selects_e():
    c = MidpointBoundaryClassifierV55()
    ref = red_ref()
    history = [
        obs("2026-09-28T09:21:00+05:30", 22930.0, -20.0),
        obs("2026-09-28T09:22:00+05:30", 22925.0, -21.0),
        obs("2026-09-28T09:23:00+05:30", 22920.0, -22.0),
        obs("2026-09-28T09:24:00+05:30", 22918.0, -23.0),
        obs("2026-09-28T09:25:00+05:30", 22914.2, -24.2),
    ]
    boundary = obs("2026-09-28T09:26:00+05:30", 22912.95, -23.91)
    d = c.classify(reference=ref, boundary_observation=boundary, history=history + [boundary])
    assert d.owner == "E"
    assert d.reason == "MATURE_DIRECTIONAL_VWAP_AT_BOUNDARY"
    assert d.candidate_a_at_boundary is False


def test_bullish_not_mature_false_a_selects_b():
    c = MidpointBoundaryClassifierV55()
    ref = green_ref()
    history = [
        obs("2026-09-28T09:53:00+05:30", 22870.0, -20.0),
        obs("2026-09-28T09:54:00+05:30", 22872.0, -19.0),
        obs("2026-09-28T09:55:00+05:30", 22874.0, -18.0),
        obs("2026-09-28T09:56:00+05:30", 22876.0, -17.0),
        obs("2026-09-28T09:57:00+05:30", 22877.0, -16.5),
    ]
    boundary = obs("2026-09-28T09:58:00+05:30", 22884.25, -16.83)
    d = c.classify(reference=ref, boundary_observation=boundary, history=history + [boundary])
    assert d.owner == "B"
    assert d.reason == "DELAYED_CONFIRMATION_WATCH"
    assert d.candidate_a_at_boundary is False


def test_fresh_a_at_boundary_is_other_not_b_or_e():
    c = MidpointBoundaryClassifierV55()
    ref = red_ref()
    history = [
        obs("2026-09-28T09:22:00+05:30", 22930.0, 2.0),
        obs("2026-09-28T09:23:00+05:30", 22925.0, 0.0),
        obs("2026-09-28T09:24:00+05:30", 22920.0, -2.0),
        obs("2026-09-28T09:25:00+05:30", 22914.2, -4.0),
    ]
    boundary = obs("2026-09-28T09:26:00+05:30", 22912.95, -8.0)
    d = c.classify(reference=ref, boundary_observation=boundary, history=history + [boundary])
    assert d.owner == OTHER_FRESH_A
    assert d.candidate_a_at_boundary is True


def test_requires_boundary_break():
    c = MidpointBoundaryClassifierV55()
    ref = red_ref()
    boundary = obs("2026-09-28T09:26:00+05:30", 22920.0, -20.0)
    try:
        c.classify(reference=ref, boundary_observation=boundary, history=[boundary])
    except ValueError as exc:
        assert "boundary break" in str(exc)
    else:
        raise AssertionError("expected boundary-break validation")
