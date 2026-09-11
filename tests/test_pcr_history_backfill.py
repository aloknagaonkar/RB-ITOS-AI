from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_lab.domain import IST, PCRConfig
from market_lab.gateways import DemoGateway
from market_lab.storage import (
    Configuration, Observation, PCRHistorySnapshot, backfill_pcr_history, make_engine, initialize,
)


def legacy_engine(tmp_path):
    engine = make_engine("sqlite:///" + (tmp_path / "legacy.db").as_posix())
    initialize(engine)
    with Session(engine) as session, session.begin():
        session.get(Configuration, 1).payload = PCRConfig(expiry=date(2026, 9, 15)).model_dump(mode="json")
        config = PCRConfig.model_validate(session.get(Configuration, 1).payload)
        for index in range(2):
            snapshot = DemoGateway().collect_at(config, datetime(2026, 9, 9, 9, 20, tzinfo=IST) + timedelta(minutes=index), index)
            from market_lab.domain import evaluate
            evaluation = evaluate(snapshot, config)
            session.add(Observation(config_id=1, recorded_at=snapshot.received_at.isoformat(), session_date="2026-09-09", snapshot=snapshot.model_dump(mode="json"), evaluation=evaluation.model_dump(mode="json")))
    return engine


def test_backfill_creates_normalized_history_and_preserves_recorded_values(tmp_path):
    engine = legacy_engine(tmp_path)
    with Session(engine) as session, session.begin():
        report = backfill_pcr_history(session, 1)
        rows = session.scalars(select(PCRHistorySnapshot).order_by(PCRHistorySnapshot.id)).all()
        first = session.get(Observation, 1)
        assert report["observations_backfilled"] == 2
        assert report["errors"] == []
        assert any(row.record_kind == "panel" for row in rows)
        assert any(row.record_kind == "strike" for row in rows)
        assert rows[0].received_at == first.snapshot["received_at"]
        assert rows[0].underlying_spot == first.snapshot["spot"]


def test_backfill_is_idempotent_and_adds_missing_identity_only(tmp_path):
    engine = legacy_engine(tmp_path)
    with Session(engine) as session, session.begin():
        first = backfill_pcr_history(session, 1)
        count = session.scalar(select(func.count()).select_from(PCRHistorySnapshot))
        second = backfill_pcr_history(session, 1)
        assert first["history_rows_created"] == count
        assert second["history_rows_created"] == 0
        assert second["observations_skipped"] == 2
