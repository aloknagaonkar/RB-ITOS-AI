from datetime import date, datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from market_lab.api import create_app
from market_lab.domain import IST, PCRConfig
from market_lab.gateways import DemoGateway
from market_lab.storage import Configuration, Control, Observation, initialize, make_engine, record, replay


@pytest.fixture
def engine(tmp_path):
    engine = make_engine("sqlite:///" + (tmp_path / "test.db").as_posix())
    initialize(engine)
    with Session(engine) as session, session.begin():
        session.get(Configuration, 1).payload = PCRConfig(expiry=date(2026, 9, 15)).model_dump(mode="json")
    yield engine
    engine.dispose()


def seed(engine):
    with Session(engine) as session:
        config = PCRConfig.model_validate(session.get(Configuration, 1).payload)
    for i in range(4):
        record(
            engine,
            1,
            DemoGateway().collect_at(
                config, datetime(2026, 9, 9, 9, 20, tzinfo=IST) + timedelta(minutes=i), i
            ),
        )
    return config


def test_restart_anchor_and_replay(engine):
    config = seed(engine)
    restarted = make_engine(str(engine.url))
    record(restarted, 1, DemoGateway().collect_at(config, datetime(2026, 9, 9, 11, 0, tzinfo=IST), 60))
    assert replay(restarted, 1)["matched"]
    with Session(restarted) as session:
        latest = session.scalar(select(Observation).order_by(Observation.id.desc()))
        assert latest.evaluation["anchor"]["captured_at"].startswith("2026-09-09T09:20")
    restarted.dispose()


def test_replay_detects_mismatch(engine):
    seed(engine)
    with Session(engine) as session, session.begin():
        row = session.get(Observation, 2)
        row.evaluation = {**row.evaluation, "anchor_status": "tampered"}
    assert replay(engine, 1)["mismatches"] == [2]


def test_out_of_order(engine):
    config = seed(engine)
    with pytest.raises(ValueError, match="Out-of-order"):
        record(engine, 1, DemoGateway().collect_at(config, datetime(2026, 9, 9, 9, 20, tzinfo=IST), 0))


def test_api_flow(engine):
    config = seed(engine)
    with TestClient(create_app(engine)) as client:
        state = client.get("/api/state").json()
        assert state["observation_count"] == 4 and not state["execution_enabled"]
        assert client.get("/api/observations/1").json()["snapshot"]["raw"]["synthetic"]
        assert client.post("/api/replay/1", json={}).json()["matched"]
        assert client.post("/api/collection", json={"enabled": True}).status_code == 200
        assert client.post("/api/configurations", json=config.model_dump(mode="json")).status_code == 409
        client.post("/api/collection", json={"enabled": False})
        response = client.post("/api/configurations", json=config.model_dump(mode="json"))
        assert response.status_code == 201 and response.json()["config_id"] == 2
        assert client.get("/api/state").json()["observation_count"] == 0
        assert client.get("/api/observations/1").status_code == 200
        assert not client.post("/api/replay/2", json={}).json()["matched"]
        assert client.get("/api/observations/999").status_code == 404
        assert client.post("/api/replay/999", json={}).status_code == 404


def test_validation_origin(engine):
    with TestClient(create_app(engine)) as client:
        assert (
            client.post("/api/configurations", json={"expiry": "2026-09-15", "wings": -1}).status_code == 422
        )
        assert (
            client.post(
                "/api/configurations", json={"expiry": "2026-09-15", "anchor_time": "09:00"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/collection", json={"enabled": True}, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
    with Session(engine) as session:
        assert not session.get(Control, 1).enabled


def test_preview_origin_allowed(engine):
    with TestClient(create_app(engine)) as client:
        response = client.post(
            "/api/collection", json={"enabled": False}, headers={"Origin": "http://127.0.0.1:8123"}
        )
        assert response.status_code == 200
