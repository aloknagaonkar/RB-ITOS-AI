from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
    _ReferenceRuntime,
)
from market_lab.midpoint_strategy.models import MidpointFamily
from market_lab.midpoint_strategy.runtime import MidpointFamilyBRuntime
from market_lab.midpoint_strategy.structure import ReferenceStructure


class DummySources:
    pass


def make_obs(ts, close, raw):
    fv = 23000.0
    return FamilyBObservation(
        timestamp=ts,
        close=close,
        futures_price=fv + raw,
        futures_vwap=fv,
    )


def test_v56_config_enables_e_but_preserves_safety():
    cfg = MidpointShadowConfig()
    cfg.assert_safe()
    assert cfg.family_b_enabled is True
    assert cfg.family_e_enabled is True
    assert cfg.family_c_enabled is False
    assert cfg.family_d_enabled is False
    assert cfg.pm_e_enabled is False
    assert cfg.observation_only is True
    assert cfg.execution_enabled is False
    assert cfg.paper_order_enabled is False
    assert cfg.quantity is None


def test_0926_bearish_mature_boundary_enters_e(tmp_path: Path):
    c = MidpointLiveShadowCoordinatorV1(
        market_sources=DummySources(),
        audit_path=tmp_path / "audit.jsonl",
    )
    c._reset_session(date(2026, 9, 28))
    assert c.state is not None

    ref = ReferenceStructure(
        session_date="2026-09-28",
        reference_type="RED",
        start_timestamp="2026-09-28T09:20:00+05:30",
        end_timestamp="2026-09-28T09:24:00+05:30",
        high=22951.8,
        low=22914.1,
    )
    rr = _ReferenceRuntime(
        reference=ref,
        runtime=MidpointFamilyBRuntime(reference=ref),
        midpoint_seen=True,
        boundary_seen=False,
    )
    c.state.references["RED"] = rr
    c.state.observations.extend([
        make_obs("2026-09-28T09:21:00+05:30", 22930.0, -20.0),
        make_obs("2026-09-28T09:22:00+05:30", 22925.0, -21.0),
        make_obs("2026-09-28T09:23:00+05:30", 22920.0, -22.0),
        make_obs("2026-09-28T09:24:00+05:30", 22918.0, -23.0),
        make_obs("2026-09-28T09:25:00+05:30", 22914.2, -24.2),
    ])

    ts = datetime.fromisoformat("2026-09-28T09:26:00+05:30")
    underlying = SimpleNamespace(
        timestamp=ts, open=22914.0, high=22915.0,
        low=22910.0, close=22912.95, volume=100.0,
    )
    c._process_minute(
        ts=ts,
        underlying=underlying,
        futures_close=22955.1,
        futures_vwap=22979.0055311973,
        underlying_by_ts={},
    )

    assert rr.runtime.family is MidpointFamily.E
    assert rr.runtime.lifecycle is not None
    assert rr.runtime.lifecycle.family is MidpointFamily.E
    assert c.state.active_reference_type == "RED"

    audit = (tmp_path / "audit.jsonl").read_text().replace(" ", "")
    assert '"event_type":"BOUNDARY_CLASSIFIED"' in audit
    assert '"event_type":"E_ENTRY"' in audit


def test_0958_bullish_not_mature_starts_b_watch(tmp_path: Path):
    c = MidpointLiveShadowCoordinatorV1(
        market_sources=DummySources(),
        audit_path=tmp_path / "audit.jsonl",
    )
    c._reset_session(date(2026, 9, 28))
    assert c.state is not None

    ref = ReferenceStructure(
        session_date="2026-09-28",
        reference_type="GREEN",
        start_timestamp="2026-09-28T09:45:00+05:30",
        end_timestamp="2026-09-28T09:49:00+05:30",
        high=22878.6,
        low=22856.3,
    )
    rr = _ReferenceRuntime(
        reference=ref,
        runtime=MidpointFamilyBRuntime(reference=ref),
        midpoint_seen=True,
        boundary_seen=False,
    )
    c.state.references["GREEN"] = rr
    c.state.observations.extend([
        make_obs("2026-09-28T09:53:00+05:30", 22870.0, -20.0),
        make_obs("2026-09-28T09:54:00+05:30", 22872.0, -19.0),
        make_obs("2026-09-28T09:55:00+05:30", 22874.0, -18.0),
        make_obs("2026-09-28T09:56:00+05:30", 22876.0, -17.0),
        make_obs("2026-09-28T09:57:00+05:30", 22877.0, -16.5),
    ])

    ts = datetime.fromisoformat("2026-09-28T09:58:00+05:30")
    underlying = SimpleNamespace(
        timestamp=ts, open=22880.0, high=22886.0,
        low=22879.0, close=22884.25, volume=100.0,
    )
    c._process_minute(
        ts=ts,
        underlying=underlying,
        futures_close=22929.1,
        futures_vwap=22945.925180212012,
        underlying_by_ts={},
    )

    assert rr.runtime.family is MidpointFamily.B
    assert rr.runtime.watch is not None
    assert rr.runtime.lifecycle is None
    assert c.state.active_reference_type is None

    audit = (tmp_path / "audit.jsonl").read_text().replace(" ", "")
    assert '"event_type":"BOUNDARY_CLASSIFIED"' in audit
    assert '"event_type":"B_WATCH_STARTED"' in audit
