from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
    _ReferenceRuntime,
)
from market_lab.midpoint_strategy.models import MidpointFamily, MidpointShadowState
from market_lab.midpoint_strategy.runtime import MidpointFamilyBRuntime
from market_lab.midpoint_strategy.family_b_shadow import FamilyBShadowRuntime
from market_lab.midpoint_strategy.structure import ReferenceStructure


class DummySources:
    pass


def mk_ref(session, ref_type, start, end, high, low):
    return ReferenceStructure(
        session_date=session,
        reference_type=ref_type,
        start_timestamp=start,
        end_timestamp=end,
        high=high,
        low=low,
    )


def test_terminal_candle_still_classifies_opposite_b_and_arms_watch(tmp_path: Path):
    c = MidpointLiveShadowCoordinatorV1(
        market_sources=DummySources(),
        audit_path=tmp_path / "audit.jsonl",
    )
    c._reset_session(date(2025, 10, 9))
    assert c.state is not None

    green = mk_ref(
        "2025-10-09", "GREEN",
        "2025-10-09T09:20:00+05:30",
        "2025-10-09T09:24:00+05:30",
        25107.7, 25059.6,
    )
    green_rt = MidpointFamilyBRuntime(reference=green, family=MidpointFamily.E)
    green_rt.lifecycle = FamilyBShadowRuntime(
        direction="BULLISH",
        entry_timestamp=datetime.fromisoformat("2025-10-09T09:28:00+05:30"),
        entry_underlying_close=25110.6,
        family=MidpointFamily.E,
        state=MidpointShadowState.ACTIVE,
    )
    c.state.references["GREEN"] = _ReferenceRuntime(
        reference=green,
        runtime=green_rt,
        midpoint_seen=True,
        boundary_seen=True,
    )
    c.state.active_reference_type = "GREEN"

    red = mk_ref(
        "2025-10-09", "RED",
        "2025-10-09T09:30:00+05:30",
        "2025-10-09T09:34:00+05:30",
        25120.35, 25086.15,
    )
    red_rt = MidpointFamilyBRuntime(reference=red)
    c.state.references["RED"] = _ReferenceRuntime(
        reference=red,
        runtime=red_rt,
        midpoint_seen=True,
        boundary_seen=False,
    )

    for minute, raw in [
        ("09:30", -1.0),
        ("09:31", -2.0),
        ("09:32", -3.0),
        ("09:33", -4.0),
        ("09:34", -4.5),
    ]:
        c.state.observations.append(
            FamilyBObservation(
                timestamp=f"2025-10-09T{minute}:00+05:30",
                close=25090.0,
                futures_price=25000.0 + raw,
                futures_vwap=25000.0,
            )
        )

    ts = datetime.fromisoformat("2025-10-09T09:35:00+05:30")
    underlying = SimpleNamespace(
        timestamp=ts, open=25091.85, high=25091.85,
        low=25077.8, close=25078.1, volume=100.0,
    )
    c._process_minute(
        ts=ts,
        underlying=underlying,
        futures_close=24999.0,
        futures_vwap=25000.0,
        underlying_by_ts={},
    )

    assert c.state.active_reference_type is None
    assert c.state.references["GREEN"].closed is True
    assert c.state.references["RED"].boundary_seen is True
    assert red_rt.watch is not None
    assert red_rt.watch.active is True
    assert red_rt.lifecycle is None

    audit = (tmp_path / "audit.jsonl").read_text().replace(" ", "")
    assert '"event_type":"STRUCTURAL_TERMINAL"' in audit
    assert '"event_type":"BOUNDARY_CLASSIFIED"' in audit
    assert '"event_type":"B_WATCH_STARTED"' in audit


def test_terminal_candle_e_is_classified_but_entry_blocked(tmp_path: Path):
    c = MidpointLiveShadowCoordinatorV1(
        market_sources=DummySources(),
        audit_path=tmp_path / "audit.jsonl",
    )
    c._reset_session(date(2025, 9, 2))
    assert c.state is not None

    green = mk_ref(
        "2025-09-02", "GREEN",
        "2025-09-02T09:20:00+05:30",
        "2025-09-02T09:24:00+05:30",
        24653.9, 24631.35,
    )
    green_rt = MidpointFamilyBRuntime(reference=green, family=MidpointFamily.B)
    green_rt.lifecycle = FamilyBShadowRuntime(
        direction="BULLISH",
        entry_timestamp=datetime.fromisoformat("2025-09-02T09:30:00+05:30"),
        entry_underlying_close=24660.9,
        family=MidpointFamily.B,
        state=MidpointShadowState.ACTIVE,
    )
    c.state.references["GREEN"] = _ReferenceRuntime(
        reference=green,
        runtime=green_rt,
        midpoint_seen=True,
        boundary_seen=True,
    )
    c.state.active_reference_type = "GREEN"

    red = mk_ref(
        "2025-09-02", "RED",
        "2025-09-02T13:45:00+05:30",
        "2025-09-02T13:49:00+05:30",
        24662.05, 24632.8,
    )
    red_rt = MidpointFamilyBRuntime(reference=red)
    c.state.references["RED"] = _ReferenceRuntime(
        reference=red,
        runtime=red_rt,
        midpoint_seen=True,
        boundary_seen=False,
    )

    for minute in range(49, 54):
        c.state.observations.append(
            FamilyBObservation(
                timestamp=f"2025-09-02T13:{minute:02d}:00+05:30",
                close=24640.0,
                futures_price=24900.0,
                futures_vwap=25000.0,
            )
        )

    ts = datetime.fromisoformat("2025-09-02T13:54:00+05:30")
    underlying = SimpleNamespace(
        timestamp=ts, open=24644.75, high=24644.75,
        low=24623.35, close=24627.7, volume=100.0,
    )
    c._process_minute(
        ts=ts,
        underlying=underlying,
        futures_close=24900.0,
        futures_vwap=25000.0,
        underlying_by_ts={},
    )

    assert red_rt.family is MidpointFamily.E
    assert red_rt.lifecycle is None
    assert c.state.active_reference_type is None

    audit = (tmp_path / "audit.jsonl").read_text().replace(" ", "")
    assert '"event_type":"BOUNDARY_CLASSIFIED"' in audit
    assert '"result":"E"' in audit
    assert '"event_type":"E_ENTRY_BLOCKED"' in audit
    assert '"reason":"SAME_CANDLE_REVERSAL_BLOCKED"' in audit
