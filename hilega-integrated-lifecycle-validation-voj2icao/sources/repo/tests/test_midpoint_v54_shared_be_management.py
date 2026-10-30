from datetime import datetime
from pathlib import Path

from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.family_b_shadow import FamilyBShadowManager, FamilyBShadowRuntime
from market_lab.midpoint_strategy.models import MidpointFamily, MidpointShadowState
from market_lab.midpoint_strategy.runtime import AuditableFamilyBEngine, MidpointFamilyBRuntime
from market_lab.midpoint_strategy.structure import ReferenceStructure


def ref_red():
    return ReferenceStructure(
        session_date="2026-09-28",
        reference_type="RED",
        start_timestamp="2026-09-28T09:20:00+05:30",
        end_timestamp="2026-09-28T09:24:00+05:30",
        high=22951.8,
        low=22914.1,
    )


def obs(ts, close, fp=22955.1, fv=22979.0055311973):
    return FamilyBObservation(
        timestamp=ts,
        close=close,
        futures_price=fp,
        futures_vwap=fv,
    )


def test_b_runtime_default_family_is_unchanged():
    rt = FamilyBShadowRuntime(
        direction="BEARISH",
        entry_timestamp=datetime.fromisoformat("2026-09-28T09:42:00+05:30"),
        entry_underlying_close=22912.0,
    )
    assert rt.family is MidpointFamily.B


def test_shared_manager_emits_b_for_existing_b_runtime():
    mgr = FamilyBShadowManager(MidpointShadowConfig())
    rt = FamilyBShadowRuntime(
        direction="BEARISH",
        entry_timestamp=datetime.fromisoformat("2026-09-28T09:42:00+05:30"),
        entry_underlying_close=22912.0,
    )
    sig = mgr.mark_plus20(rt, datetime.fromisoformat("2026-09-28T09:45:00+05:30"))
    assert sig.family is MidpointFamily.B


def test_shared_manager_emits_e_for_e_runtime():
    mgr = FamilyBShadowManager(MidpointShadowConfig())
    rt = FamilyBShadowRuntime(
        direction="BEARISH",
        entry_timestamp=datetime.fromisoformat("2026-09-28T09:26:00+05:30"),
        entry_underlying_close=22912.95,
        family=MidpointFamily.E,
    )
    sig = mgr.mark_plus20(rt, datetime.fromisoformat("2026-09-28T09:35:00+05:30"))
    assert sig.family is MidpointFamily.E


def test_e_entry_uses_same_lifecycle_and_is_observation_only(tmp_path: Path):
    cfg = MidpointShadowConfig()
    assert cfg.family_e_enabled is True
    assert cfg.observation_only is True
    assert cfg.execution_enabled is False
    assert cfg.paper_order_enabled is False
    assert cfg.quantity is None

    engine = AuditableFamilyBEngine(
        journal_path=tmp_path / "audit.jsonl",
        config=cfg,
    )
    rt = MidpointFamilyBRuntime(reference=ref_red())
    boundary = obs("2026-09-28T09:26:00+05:30", 22912.95)

    engine.start_e_entry(rt, boundary)

    assert rt.family is MidpointFamily.E
    assert rt.watch is None
    assert rt.lifecycle is not None
    assert rt.lifecycle.family is MidpointFamily.E
    assert rt.lifecycle.state is MidpointShadowState.ACTIVE
    assert rt.lifecycle.entry_timestamp.isoformat() == boundary.timestamp
    assert rt.lifecycle.entry_underlying_close == boundary.close

    rows = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(rows) == 1
    row = rows[0].replace(" ", "").lower()
    assert '"family":"e"' in row
    assert '"event_type":"e_entry"' in row
    assert '"order_sent":false' in row


def test_e_rejects_non_mature_bearish_boundary(tmp_path: Path):
    engine = AuditableFamilyBEngine(
        journal_path=tmp_path / "audit.jsonl",
        config=MidpointShadowConfig(),
    )
    rt = MidpointFamilyBRuntime(reference=ref_red())
    boundary = obs(
        "2026-09-28T09:26:00+05:30",
        22912.95,
        fp=22977.0,
        fv=22979.0,
    )
    try:
        engine.start_e_entry(rt, boundary)
    except ValueError as exc:
        assert "mature directional VWAP" in str(exc)
    else:
        raise AssertionError("expected Family E maturity rejection")
