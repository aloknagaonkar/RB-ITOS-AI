from datetime import datetime, timedelta, timezone
from pathlib import Path

from market_lab.midpoint_strategy.audit import (
    AuditEvent,
    JsonlAuditJournal,
    deterministic_event_id,
)
from market_lab.midpoint_strategy.family_b_detector import (
    FamilyBDelayedDetector,
    FamilyBObservation,
)
from market_lab.midpoint_strategy.structure import ReferenceStructure


def test_deterministic_event_id():
    args = dict(
        session_date="2026-09-29",
        family="B",
        event_timestamp="2026-09-29T09:42:00+05:30",
        event_type="B_ENTRY",
        direction="BEARISH",
    )
    assert deterministic_event_id(**args) == deterministic_event_id(**args)


def test_journal_is_idempotent(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    j = JsonlAuditJournal(p)
    e = AuditEvent(
        event_id="abc",
        session_date="2026-09-29",
        strategy="MIDPOINT_STRATEGY",
        version="shadow-v1",
        family="B",
        event_timestamp="2026-09-29T09:42:00+05:30",
        event_type="B_ENTRY",
    )
    assert j.append(e) is True
    assert j.append(e) is False
    assert len(j.read_all()) == 1


def test_b_delayed_confirmation():
    det = FamilyBDelayedDetector()
    base = datetime(2026, 9, 29, 9, 20, tzinfo=timezone.utc)

    def o(m, close, fp, vw):
        return FamilyBObservation(
            timestamp=(base + timedelta(minutes=m)).isoformat(),
            close=close,
            futures_price=fp,
            futures_vwap=vw,
        )

    ref = ReferenceStructure(
        session_date="2026-09-29",
        reference_type="RED",
        start_timestamp=o(0,0,0,0).timestamp,
        end_timestamp=o(4,0,0,0).timestamp,
        high=24198.25,
        low=24173.70,
    )

    hist = [
        o(14, 24180, 24181, 24184),
        o(18, 24170, 24172, 24176),
    ]
    boundary = o(19, 24168, 24169, 24173)
    hist.append(boundary)

    watch = det.start_watch(ref, boundary, hist)
    assert watch.active is True

    current = o(22, 24162.9, 24163, 24171)
    hist.append(current)
    d = det.evaluate(watch, current, hist)

    assert d.result == "ENTRY"
    assert d.reason == "B_DELAYED_FULL_CANDIDATE_A"
