"""Staged signal-audit tests; synthetic inputs and temporary databases only."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

import test_hilega_application_preparation_v1 as application
from test_hilega_application_preparation_v1 import (
    env, process, append, BULL, command, counts,
)
from test_hilega_atomic_disabled_binding_v1 import bound_env
from market_lab.hilega_production_simulator_bridge_v1 import accepted


CANDIDATE = Path("hilega-signal-audit-stage-7dp0zywb/source.py")
INSTALLED = Path(
    "backend/market_lab/hilega_preparation_runtime_v1/source.py"
)
CANDIDATE_SHA = (
    "dbfce30057763b93e8f7f8332e86e2145890bd29c72d18016b3ad944125e6150"
)
INSTALLED_SHA = (
    "8163ca0db32a5fc95358368d2f474a6f0e083c853cb97008b7574f1241310f71"
)


@pytest.fixture(autouse=True)
def staged_source(monkeypatch):
    for path, expected in (
        (CANDIDATE, CANDIDATE_SHA), (INSTALLED, INSTALLED_SHA)
    ):
        assert path.is_file() and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected

    spec = importlib.util.spec_from_file_location(
        "market_lab.hilega_preparation_runtime_v1._signal_audit_candidate",
        CANDIDATE,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(application, "Source", module.Source)
    yield module
    assert hashlib.sha256(INSTALLED.read_bytes()).hexdigest() == INSTALLED_SHA


def audit_rows(e):
    with e["store"].db() as db:
        return [json.loads(row[0]) for row in db.execute(
            "SELECT data FROM preparation_events ORDER BY seq")]


def journal_event(e):
    row = json.loads(e["path"].read_text().splitlines()[-1])
    event, = accepted(row)
    return row, event


def expected_reference(module, event):
    return dict(
        signal_id=event["id"],
        signal_at=event["event_at"],
        direction=event["direction"],
        source_sequence=event["source_sequence"],
        source_record_hash=event["source_record_hash"],
        event_fingerprint=module.event_digest(event),
    )


def assert_no_transport(e):
    with e["adapter_store"].tx() as db:
        for table in ("attempts", "receipts"):
            assert db.execute(
                "SELECT COUNT(*) FROM " + table
            ).fetchone()[0] == 0


def test_success_records_exact_signal(bound_env, staged_source):
    e = bound_env
    process(e)
    _, event = journal_event(e)
    audit = audit_rows(e)[-1]
    assert audit["status"] == "EVIDENCE_LINKED_UNSENT"
    assert audit["source_event_references"] == [
        expected_reference(staged_source, event)]
    request, = e["adapter_store"].requests()
    assert request["signal_id"] == event["id"]
    assert audit["orders_sent"] is False
    assert audit["production_execution_enabled"] is False
    assert_no_transport(e)


def test_paused_refusal_records_exact_signal(bound_env, staged_source):
    e = bound_env
    command(e["s"], "pause")
    process(e)
    _, event = journal_event(e)
    audit = audit_rows(e)[-1]
    assert audit["status"] == "BLOCKED"
    assert audit["reasons"] == ["CONTROLLER_PAUSED_OR_STOP_PENDING"]
    assert audit["source_event_references"] == [
        expected_reference(staged_source, event)]
    assert not e["calls"]
    assert counts(e) == (0, 0, 0, 0, 0, 0)
    assert_no_transport(e)


def test_multiple_refused_events_keep_all_references(bound_env, staged_source):
    e = bound_env
    append(e["path"], [BULL])
    row, first = journal_event(e)
    second = deepcopy(first)
    second["id"] += "-synthetic-second-event"
    events = [first, second]
    original = deepcopy(events)
    cursor = dict(
        path=str(e["path"].resolve()),
        sequence=row["sequence"], hash=row["record_hash"],
    )
    # Direct helper test with two synthetic events, not a claimed live reversal.
    e["source"]._block_record(
        events, cursor, "SYNTHETIC_MULTI_EVENT_REFUSAL")
    audit = audit_rows(e)[-1]
    assert audit["source_event_references"] == [
        expected_reference(staged_source, event) for event in events]
    assert events == original
    with e["store"].db() as db:
        consumed = dict(db.execute(
            "SELECT id,fingerprint FROM preparation_consumed"))
    for event in events:
        assert consumed[event["id"]] == staged_source.event_digest(event)
    assert counts(e) == (0, 0, 0, 0, 0, 0)
    assert_no_transport(e)


def test_replay_does_not_duplicate_audit(bound_env):
    e = bound_env
    process(e)
    before = audit_rows(e)
    e["source"].run_source_once(e["path"])
    assert audit_rows(e) == before
    assert len(e["adapter_store"].requests()) == 1
    assert_no_transport(e)


def test_interruption_rolls_back_signal_audit(bound_env):
    e = bound_env
    before = audit_rows(e)
    reached = []

    class Interrupted(BaseException):
        pass

    def checkpoint(stage):
        if stage == "BEFORE_COMMIT":
            reached.append(stage)
            raise Interrupted()

    e["source"].checkpoint = checkpoint
    with pytest.raises(Interrupted):
        process(e)
    assert reached == ["BEFORE_COMMIT"]
    assert audit_rows(e) == before
    assert counts(e) == (0, 0, 0, 0, 0, 0)
    assert e["adapter_store"].requests() == []
    with e["store"].db() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM preparation_consumed"
        ).fetchone()[0] == 0
    assert_no_transport(e)