from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from market_lab.domain import IST, PCRConfig
from market_lab.gateways import DemoGateway
from market_lab.recorded_session_inventory import recorded_session_inventory
from market_lab.storage import Configuration, PCRHistorySnapshot, initialize, make_engine, record


def inventory_engine(tmp_path):
    engine = make_engine("sqlite:///" + (tmp_path / "inventory.db").as_posix())
    initialize(engine)
    with Session(engine) as session, session.begin():
        session.get(Configuration, 1).payload = PCRConfig(expiry=date(2026, 9, 15), interval_seconds=60).model_dump(mode="json")
    return engine


def seed_session(engine, day, minutes):
    with Session(engine) as session:
        config = PCRConfig.model_validate(session.get(Configuration, 1).payload)
    for index, minute in enumerate(minutes):
        record(engine, 1, DemoGateway().collect_at(config, datetime(2026, 9, day, 9, 20, tzinfo=IST) + timedelta(minutes=minute), index))


def test_inventory_groups_sessions_and_reports_quality_and_readiness(tmp_path):
    engine = inventory_engine(tmp_path)
    seed_session(engine, 9, [0, 1, 3, 8, 13, 18, 23, 28, 33])
    seed_session(engine, 10, [0])
    with Session(engine) as session:
        report = recorded_session_inventory(session, 1)
    assert [row.session_date for row in report.rows] == [date(2026, 9, 9), date(2026, 9, 10)]
    first = report.rows[0]
    assert first.observation_count == 9
    assert first.first_received_at.minute == 20 and first.last_received_at.minute == 53
    assert first.maximum_interval_seconds == 300 and first.gap_count == 7
    assert first.spot_available_count == 9
    assert first.moving_available_count == 9 and first.full_available_count == 9
    assert first.fixed_anchor_status == "CAPTURED"
    assert first.current_oi_complete_observation_count == 9
    assert first.previous_oi_complete_observation_count == 9
    assert first.contract_complete_observation_count == 9
    assert first.pcr_history_complete_observation_count == 9
    assert first.replay_ready and first.backfill_ready and first.session_analysis_ready
    assert first.forward_5m_available_count > 0 and first.multi_session_evidence_ready


def test_inventory_reports_missing_history_without_writing(tmp_path):
    engine = inventory_engine(tmp_path)
    seed_session(engine, 9, [0, 1])
    with Session(engine) as session, session.begin():
        observation_id = session.scalar(select(PCRHistorySnapshot.observation_id).limit(1))
        session.execute(delete(PCRHistorySnapshot).where(PCRHistorySnapshot.observation_id == observation_id))
    with Session(engine) as session:
        before = len(session.scalars(select(PCRHistorySnapshot)).all())
        row = recorded_session_inventory(session, 1).rows[0]
        after = len(session.scalars(select(PCRHistorySnapshot)).all())
    assert row.pcr_history_missing_observation_count == 1
    assert not row.session_analysis_ready
    assert before == after


def test_inventory_empty_and_config_filter(tmp_path):
    engine = inventory_engine(tmp_path)
    with Session(engine) as session:
        assert recorded_session_inventory(session).rows == []
        assert recorded_session_inventory(session, 1).rows == []
