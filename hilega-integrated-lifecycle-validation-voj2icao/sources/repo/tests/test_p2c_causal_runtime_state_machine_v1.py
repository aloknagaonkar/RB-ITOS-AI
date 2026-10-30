
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_lab.domain import Contract, Quote, Snapshot
from market_lab.storage import Base, Configuration, Observation
from market_lab.paper_production_storage_v1 import ensure_paper_schema, PaperSignal
from market_lab.oi_vwap_live_feature_engine_v1 import FuturesVWAPFeature
from market_lab.oi_vwap_causal_runtime_v1 import (
    _directional_p1,
    _p2_persists,
    _vwap_aligned,
)
from market_lab.oi_vwap_live_feature_engine_v1 import OICheckpointFeature

IST = ZoneInfo("Asia/Kolkata")


def feature(
    imbalance,
    pcr_delta,
    session_imbalance,
    prev_session_imbalance,
    *,
    oid=1,
    ts="2026-09-16T10:00:00+05:30",
):
    return OICheckpointFeature(
        observation_id=oid,
        timestamp=ts,
        session_date="2026-09-16",
        spot=23250.0,
        atm=23250.0,
        ce_oi=1000,
        pe_oi=1000,
        ce_delta_5m=0,
        pe_delta_5m=imbalance,
        imbalance_5m=imbalance,
        pcr_current_5m=1.0 + pcr_delta,
        pcr_previous_5m=1.0,
        pcr_change_5m=pcr_delta,
        ce_session_delta=0,
        pe_session_delta=session_imbalance,
        session_imbalance=session_imbalance,
        previous_session_imbalance=prev_session_imbalance,
    )


def test_bullish_fresh_p1_requires_sign_flip_pcr_and_improving_session():
    previous = feature(-100, -0.01, -500, -400, oid=1)
    current = feature(200, 0.02, -100, -500, oid=2)
    direction, reason = _directional_p1(current, previous)
    assert direction == "BULLISH"
    assert reason is None


def test_bearish_fresh_p1_requires_sign_flip_pcr_and_weakening_session():
    previous = feature(100, 0.01, 500, 400, oid=1)
    current = feature(-200, -0.02, 100, 500, oid=2)
    direction, reason = _directional_p1(current, previous)
    assert direction == "BEARISH"
    assert reason is None


def test_no_fresh_p1_without_sign_transition():
    previous = feature(100, 0.01, 100, 50, oid=1)
    current = feature(200, 0.02, 200, 100, oid=2)
    direction, reason = _directional_p1(current, previous)
    assert direction is None
    assert reason == "NO_FRESH_P1"


def test_vwap_alignment_is_directional():
    assert _vwap_aligned("BULLISH", "ABOVE") is True
    assert _vwap_aligned("BULLISH", "BELOW") is False
    assert _vwap_aligned("BEARISH", "BELOW") is True
    assert _vwap_aligned("BEARISH", "ABOVE") is False


def test_p2_persistence_uses_current_direction_only():
    assert _p2_persists("BULLISH", feature(300, 0.01, 100, 50))
    assert not _p2_persists("BULLISH", feature(-300, 0.01, 100, 50))
    assert _p2_persists("BEARISH", feature(-300, -0.01, -100, -50))
    assert not _p2_persists("BEARISH", feature(300, -0.01, -100, -50))


def test_p2_does_not_auto_reverse():
    # Opposite directional checkpoint simply fails the waiting setup.
    bull_wait = feature(300, 0.02, 100, 50)
    opposite = feature(-400, -0.03, -100, 100)
    assert _p2_persists("BULLISH", opposite) is False


def test_paper_schema_still_defaults_safe(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'runtime.db'}")
    Base.metadata.create_all(engine)
    ensure_paper_schema(engine)
    with Session(engine) as session:
        from market_lab.paper_production_storage_v1 import get_paper_control
        control = get_paper_control(session)
        assert control["enabled"] is False
        assert control["live_enabled"] is False
