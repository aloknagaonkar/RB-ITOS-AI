from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from market_lab.domain import IST, PCRConfig
from market_lab.gateways import DemoGateway
import market_lab.storage as storage_module
from market_lab.storage import Configuration, Observation, backfill_pcr_history, initialize, make_engine, record, utc_now


SESSION = date(2026, 9, 11)
MORNING = datetime(2026, 9, 11, 9, 20, 10, tzinfo=IST)
AFTERNOON = datetime(2026, 9, 11, 13, 55, tzinfo=IST)


@pytest.fixture
def engine(tmp_path):
    value = make_engine("sqlite:///" + (tmp_path / "anchors.db").as_posix())
    initialize(value)
    yield value
    value.dispose()


def replace_config(engine, identifier, config):
    with Session(engine) as session, session.begin():
        row = session.get(Configuration, identifier)
        if row:
            row.payload = config.model_dump(mode="json")
        else:
            session.add(Configuration(id=identifier, created_at=utc_now(), payload=config.model_dump(mode="json")))


def observation(engine, identifier):
    with Session(engine) as session:
        return session.get(Observation, identifier).evaluation


def capture(engine, config_id=1, config=None, at=MORNING, step=0):
    config = config or PCRConfig(expiry=date(2026, 9, 15))
    replace_config(engine, config_id, config)
    return record(engine, config_id, DemoGateway().collect_at(config, at, step))


def test_interval_only_version_change_recovers_exact_anchor_and_then_propagates(engine):
    original = PCRConfig(expiry=date(2026, 9, 15), interval_seconds=60)
    first_id = capture(engine, config=original)
    captured = observation(engine, first_id)["anchor"]
    revised = original.model_copy(update={"interval_seconds": 15})
    replace_config(engine, 2, revised)

    recovered_id = record(engine, 2, DemoGateway().collect_at(revised, AFTERNOON, 1))
    propagated_id = record(engine, 2, DemoGateway().collect_at(revised, AFTERNOON + timedelta(seconds=20), 2))

    assert observation(engine, recovered_id)["anchor"] == captured
    assert observation(engine, propagated_id)["anchor"] == captured
    assert captured["captured_at"].startswith("2026-09-11T09:20:10")
    assert captured["spot"] == observation(engine, first_id)["anchor"]["spot"]
    assert len(captured["contracts"]) == 22


@pytest.mark.parametrize(
    "change",
    [
        {"underlying": "NSE_INDEX|Other"},
        {"expiry": date(2026, 9, 22)},
        {"provider": "upstox"},
        {"wings": 4},
        {"anchor_time": "09:21"},
        {"anchor_tolerance_seconds": 121},
        {"max_quote_age_seconds": 31},
        {"max_collection_seconds": 21},
    ],
)
def test_incompatible_anchor_semantics_do_not_recover(engine, change):
    original = PCRConfig(expiry=date(2026, 9, 15))
    capture(engine, config=original)
    revised = original.model_copy(update=change)
    replace_config(engine, 2, revised)
    value = DemoGateway().collect_at(revised, AFTERNOON, 1)
    if revised.provider == "upstox":
        value = value.model_copy(update={"provider": "upstox"})

    result = observation(engine, record(engine, 2, value))

    assert result["anchor_status"] == "missed"
    assert result["anchor"] is None


def test_previous_ist_session_anchor_does_not_recover(engine):
    config = PCRConfig(expiry=date(2026, 9, 15))
    capture(engine, config=config, at=MORNING - timedelta(days=1))
    replace_config(engine, 2, config.model_copy(update={"interval_seconds": 15}))
    result = observation(engine, record(engine, 2, DemoGateway().collect_at(config, AFTERNOON, 1)))
    assert result["anchor_status"] == "missed"


def test_no_previous_anchor_remains_missed(engine):
    config = PCRConfig(expiry=date(2026, 9, 15), interval_seconds=15)
    replace_config(engine, 2, config)
    result = observation(engine, record(engine, 2, DemoGateway().collect_at(config, AFTERNOON, 1)))
    assert result["anchor_status"] == "missed"
    assert result["anchor"] is None


def test_existing_missed_observation_is_not_mutated(engine):
    config = PCRConfig(expiry=date(2026, 9, 15), interval_seconds=15)
    replace_config(engine, 2, config)
    missed_id = record(engine, 2, DemoGateway().collect_at(config, AFTERNOON, 1))
    before = observation(engine, missed_id)
    capture(engine, config_id=1, config=config.model_copy(update={"interval_seconds": 60}))
    record(engine, 2, DemoGateway().collect_at(config, AFTERNOON + timedelta(minutes=1), 2))
    assert observation(engine, missed_id) == before


def test_future_candidate_is_not_selected(engine):
    config = PCRConfig(expiry=date(2026, 9, 15))
    future_id = capture(engine, config=config)
    with Session(engine) as session, session.begin():
        row = session.get(Observation, future_id)
        row.snapshot = {**row.snapshot, "received_at": (AFTERNOON + timedelta(minutes=1)).isoformat()}
        row.session_date = SESSION.isoformat()
    replace_config(engine, 2, config.model_copy(update={"interval_seconds": 15}))
    result = observation(engine, record(engine, 2, DemoGateway().collect_at(config, AFTERNOON, 1)))
    assert result["anchor_status"] == "missed"


def test_latest_compatible_captured_anchor_wins(engine):
    config = PCRConfig(expiry=date(2026, 9, 15))
    first_id = capture(engine, config_id=1, config=config, at=MORNING, step=0)
    first_anchor = observation(engine, first_id)["anchor"]
    replace_config(engine, 2, config)
    later_at = MORNING + timedelta(seconds=50)
    later_snapshot = DemoGateway().collect_at(config, later_at, 1)
    later_evaluation = deepcopy(observation(engine, first_id))
    later_anchor = deepcopy(first_anchor)
    later_anchor.update({
        "captured_at": later_at.isoformat(),
        "spot": later_snapshot.spot,
    })
    later_evaluation.update({"observed_at": later_at.isoformat(), "anchor": later_anchor})
    with Session(engine) as session, session.begin():
        later_row = Observation(
            config_id=2,
            recorded_at=utc_now(),
            session_date=SESSION.isoformat(),
            snapshot=later_snapshot.model_dump(mode="json"),
            evaluation=later_evaluation,
        )
        session.add(later_row)
        session.flush()
        later_id = later_row.id
    replace_config(engine, 3, config.model_copy(update={"interval_seconds": 15}))

    recovered = observation(
        engine, record(engine, 3, DemoGateway().collect_at(config, AFTERNOON, 2))
    )["anchor"]

    assert recovered == later_anchor
    assert later_id > first_id
    assert recovered["captured_at"] == later_at.isoformat()
    assert recovered["spot"] == later_anchor["spot"]
    assert recovered["atm"] == later_anchor["atm"]
    assert recovered["contracts"] == later_anchor["contracts"]


def test_backfill_does_not_invoke_live_anchor_recovery(engine, monkeypatch):
    config = PCRConfig(expiry=date(2026, 9, 15))
    capture(engine, config=config)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("live anchor recovery must not run during backfill")

    monkeypatch.setattr(storage_module, "find_compatible_fixed_anchor", forbidden)
    with Session(engine) as session, session.begin():
        report = backfill_pcr_history(session, 1)

    assert report["errors"] == []


def test_replay_recovers_cross_config_anchor_only_at_recorded_transition(engine):
    """Old missed rows stay missed; a later recorded recovery is reproducible."""
    original = PCRConfig(expiry=date(2026, 9, 15), interval_seconds=60)
    captured_id = capture(engine, config_id=1, config=original)
    captured = observation(engine, captured_id)["anchor"]

    revised = original.model_copy(update={"interval_seconds": 15})
    replace_config(engine, 2, revised)

    # Seed an immutable pre-fix row: at this historical point cross-config
    # recovery was not yet active, so the stored evaluation is anchor_missed.
    missed_at = AFTERNOON
    missed_snapshot = DemoGateway().collect_at(revised, missed_at, 1)
    missed_evaluation = storage_module.evaluate(missed_snapshot, revised, None)
    with Session(engine) as session, session.begin():
        missed_row = Observation(
            config_id=2,
            recorded_at=utc_now(),
            session_date=SESSION.isoformat(),
            snapshot=missed_snapshot.model_dump(mode="json"),
            evaluation=missed_evaluation.model_dump(mode="json"),
        )
        session.add(missed_row)
        session.flush()
        missed_id = missed_row.id

    # This is the historical deployment/restart boundary: live record() uses
    # the already-captured compatible config-1 anchor from here onward.
    recovered_id = record(
        engine,
        2,
        DemoGateway().collect_at(revised, AFTERNOON + timedelta(seconds=20), 2),
    )

    before = observation(engine, missed_id)
    recovered = observation(engine, recovered_id)
    assert before["anchor_status"] == "missed"
    assert before["anchor"] is None
    assert recovered["anchor"] == captured

    report = storage_module.replay(engine, 2)
    assert report["matched"]
    assert report["mismatches"] == []
    assert observation(engine, missed_id) == before
    assert observation(engine, recovered_id) == recovered


def test_replay_does_not_accept_tampered_cross_config_anchor(engine):
    original = PCRConfig(expiry=date(2026, 9, 15), interval_seconds=60)
    capture(engine, config_id=1, config=original)
    revised = original.model_copy(update={"interval_seconds": 15})
    replace_config(engine, 2, revised)
    recovered_id = record(engine, 2, DemoGateway().collect_at(revised, AFTERNOON, 1))

    with Session(engine) as session, session.begin():
        row = session.get(Observation, recovered_id)
        tampered = deepcopy(row.evaluation)
        tampered["anchor"] = {**tampered["anchor"], "spot": tampered["anchor"]["spot"] + 1}
        row.evaluation = tampered

    report = storage_module.replay(engine, 2)
    assert not report["matched"]
    assert report["mismatches"] == [recovered_id]
