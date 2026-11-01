import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_hilega_application_preparation_v1 import env, process, counts
from hilega_application_preparation_fixtures import PIN, resign
from market_lab.hilega_preparation_runtime_v1.pricing_state import pricing_state


def test_plan_persists_pricing_without_executable_outbox(env):
    process(env)
    assert counts(env) == (1, 1, 1, 0, 0, 0)
    with env["store"].db() as db:
        plan = json.loads(db.execute(
            "SELECT data FROM preparation_plans"
        ).fetchone()[0])
        outbox = json.loads(db.execute(
            "SELECT data FROM preparation_outbox"
        ).fetchone()[0])
    assert plan["evidence"]["pricing_preview"]["normalized_tick_rupees"] == "0.05"
    assert plan["evidence"]["tick_units_verified"] is False
    assert outbox["request_body"] is None
    assert outbox["status"] == "NON_EXECUTABLE_PRICING_POLICY_PENDING"


def test_off_grid_quote_blocks_before_plan_and_hold(env):
    for key, quote in env["data"]["quotes"].items():
        if key.startswith("NSE_FO|"):
            quote["depth"]["sell"][0]["price"] = 100.01
    resign(env["data"])
    process(env)
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    assert env["store"].control()["mode"] == "PAUSED"
    with env["store"].db() as db:
        audit = json.loads(db.execute(
            "SELECT data FROM preparation_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()[0])
    assert "PRICE_GRID_PRICE_OFF_TICK_GRID" in audit["reasons"]


def test_authenticated_pricing_endpoint_is_read_only_and_private(env, monkeypatch):
    from market_lab.hilega_production_workspace_v1 import router
    monkeypatch.setenv("HILEGA_PRODUCTION_CONTROL_TOKEN", "x"*40)
    monkeypatch.delenv("HILEGA_PRODUCTION_CONTROL_TOKEN_FILE", raising=False)
    process(env)
    before = Path(env["store"].path).read_bytes()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        url = "/api/hilega-production/execution-preparation/pricing"
        assert client.get(url).status_code == 401
        response = client.get(url, headers={"Authorization": "Bearer "+"x"*40})
    assert response.status_code == 200
    result = response.json()
    assert result["total_plans"] == 1
    assert result["items"][0]["recorded_pricing_available"] is True
    assert result["production_ready"] is False
    assert result["freshness_reassessed"] is False
    assert PIN["scope"] not in response.text
    assert PIN["key"] not in response.text
    assert Path(env["store"].path).read_bytes() == before


def test_older_plan_is_not_assumed_to_have_pricing(env):
    process(env)
    with env["store"].db() as db:
        row = db.execute("SELECT id,data FROM preparation_plans").fetchone()
        plan = json.loads(row[1])
        plan["evidence"].pop("pricing_preview")
        db.execute("UPDATE preparation_plans SET data=? WHERE id=?",
                   (json.dumps(plan), row[0]))
    result = pricing_state(env["store"].path)
    assert result["items"][0]["recorded_pricing_available"] is False
    assert result["items"][0]["pricing"] is None
    assert result["production_ready"] is False


def test_empty_plan_state_has_no_pricing_or_permission(env):
    result = pricing_state(env["store"].path)
    assert result["total_plans"] == 0
    assert result["items"] == []
    assert result["entry_permission"] is False
    assert result["production_ready"] is False
