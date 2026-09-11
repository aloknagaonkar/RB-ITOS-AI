from datetime import date, datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from market_lab.api import create_app
from market_lab.domain import IST, PCRConfig
import market_lab.storage as storage_module
from market_lab.gateways import DemoGateway
from market_lab.storage import Configuration, Control, Observation, initialize, make_engine, record, replay, strike_positioning_results


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


def test_latest_pcr_trends_panel_only_is_filtered_before_calculation(engine):
    seed(engine)
    with TestClient(create_app(engine)) as client:
        normal = client.get("/api/pcr-trends/latest?config_id=1").json()
        panels = client.get("/api/pcr-trends/latest?config_id=1&panels_only=true").json()

    assert len(panels) == 12
    assert {item["record_kind"] for item in panels} == {"panel"}
    assert {item["mode"] for item in panels} == {"fixed", "moving", "full"}
    assert {item["requested_horizon_seconds"] for item in panels} == {60, 300, 900, 1800}
    assert any(item["record_kind"] == "strike" for item in normal)
    expected = {
        (item["mode"], item["requested_horizon_seconds"]): item
        for item in normal if item["record_kind"] == "panel"
    }
    assert {
        (item["mode"], item["requested_horizon_seconds"]): item for item in panels
    } == expected


def test_latest_pcr_trends_panel_only_preserves_unavailable_baselines(engine):
    seed(engine)
    with TestClient(create_app(engine)) as client:
        panels = client.get("/api/pcr-trends/latest?config_id=1&panels_only=true").json()

    long_horizons = [item for item in panels if item["requested_horizon_seconds"] in {900, 1800}]
    assert long_horizons
    assert all(item["status"] == "UNAVAILABLE" for item in long_horizons)
    assert all(item["baseline_received_at"] is None for item in long_horizons)


def test_latest_pcr_trends_panel_only_rejects_previous_ist_session(engine):
    with Session(engine) as session:
        config = PCRConfig.model_validate(session.get(Configuration, 1).payload)
    record(engine, 1, DemoGateway().collect_at(config, datetime(2026, 9, 9, 23, 59, 30, tzinfo=IST), 0))
    record(engine, 1, DemoGateway().collect_at(config, datetime(2026, 9, 10, 0, 0, 30, tzinfo=IST), 1))

    with TestClient(create_app(engine)) as client:
        panels = client.get("/api/pcr-trends/latest?config_id=1&panels_only=true").json()

    one_minute = [item for item in panels if item["requested_horizon_seconds"] == 60]
    assert {item["mode"] for item in one_minute} == {"fixed", "moving", "full"}
    assert all(item["status"] == "UNAVAILABLE" for item in one_minute)
    assert all(item["baseline_received_at"] is None for item in one_minute)

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


def _priced_demo(config, at, step):
    value = DemoGateway().collect_at(config, at, step)
    return value.model_copy(update={
        "quotes": [quote.model_copy(update={"ltp": 100 + step}) for quote in value.quotes]
    })


def test_positioning_validates_only_current_and_selected_baseline(engine, monkeypatch):
    with Session(engine) as session:
        config = PCRConfig.model_validate(session.get(Configuration, 1).payload)
    start = datetime(2026, 9, 9, 9, 20, tzinfo=IST)
    for step in range(32):
        record(engine, 1, _priced_demo(config, start + timedelta(minutes=step), step))

    original = storage_module.Snapshot.model_validate
    validated = []

    def validate(value):
        validated.append(value)
        return original(value)

    monkeypatch.setattr(storage_module.Snapshot, "model_validate", staticmethod(validate))
    with Session(engine) as session:
        results = strike_positioning_results(session, 1, horizon_seconds=1800)

    assert results
    assert len(validated) == 2
    assert {item["actual_elapsed_seconds"] for item in results} == {1800}


def test_positioning_multi_horizon_and_historical_observation_request(engine):
    with Session(engine) as session:
        config = PCRConfig.model_validate(session.get(Configuration, 1).payload)
    start = datetime(2026, 9, 9, 9, 20, tzinfo=IST)
    observation_ids = [record(engine, 1, _priced_demo(config, start + timedelta(minutes=step), step)) for step in range(32)]

    with Session(engine) as session:
        historical = strike_positioning_results(session, 1, observation_id=observation_ids[30])

    assert {item["horizon_seconds"] for item in historical} == {300, 900, 1800}
    assert all(item["observation_id"] == observation_ids[30] for item in historical)
    assert all(item["status"] == "AVAILABLE" for item in historical)


def test_positioning_api_optional_strike_window_and_validation(engine):
    config = seed(engine)
    moving_atm = DemoGateway().collect_at(config, datetime(2026, 9, 9, 9, 20, tzinfo=IST), 0).spot
    with TestClient(create_app(engine)) as client:
        full = client.get("/api/strike-positioning?config_id=1&horizon_seconds=300").json()
        window = client.get(
            f"/api/strike-positioning?config_id=1&horizon_seconds=300&center_strike={moving_atm}&wings=5"
        ).json()
        assert len(full) > len(window)
        assert len({item["strike"] for item in window}) == 11
        assert client.get("/api/strike-positioning?config_id=1&center_strike=25000").status_code == 422
        assert client.get("/api/strike-positioning?config_id=1&wings=5").status_code == 422
        assert client.get("/api/strike-positioning?config_id=1&center_strike=25025&wings=5").status_code == 422
        assert client.get("/api/strike-positioning?config_id=1&center_strike=25000&wings=-1").status_code == 422
