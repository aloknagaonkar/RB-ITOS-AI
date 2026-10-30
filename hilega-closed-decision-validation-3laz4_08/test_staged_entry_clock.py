"""Staged Source clock tests; synthetic evidence and temporary DBs only."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import re

import pytest

import test_hilega_application_preparation_v1 as application
from test_hilega_application_preparation_v1 import env, append, BULL, counts
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN, T
from market_lab.hilega_production_account_adapter_v1 import sign


CANDIDATE = Path("hilega-entry-clock-stage-a6h90flu/source.py")
CANDIDATE_SHA = (
    "8163ca0db32a5fc95358368d2f474a6f0e083c853cb97008b7574f1241310f71"
)
INSTALLED = Path(
    "backend/market_lab/hilega_preparation_runtime_v1/source.py"
)
INSTALLED_SHA = (
    "c792ebb12ab5d17a20d624843c8f6a2af7b8405fd69439d68c283a2ee1bb1a5b"
)


@pytest.fixture(autouse=True)
def staged_source(monkeypatch):
    for path, expected in (
        (CANDIDATE, CANDIDATE_SHA),
        (INSTALLED, INSTALLED_SHA),
    ):
        assert path.is_file() and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected

    spec = importlib.util.spec_from_file_location(
        "market_lab.hilega_preparation_runtime_v1._clock_candidate",
        CANDIDATE,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(application, "Source", module.Source)
    yield
    assert hashlib.sha256(INSTALLED.read_bytes()).hexdigest() == INSTALLED_SHA


def move(e, hour, minute):
    target = T.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = target - T

    def shift(value):
        if isinstance(value, dict):
            return {k: shift(v) for k, v in value.items()}
        if isinstance(value, list):
            return [shift(v) for v in value]
        if isinstance(value, str) and re.match(
            r"^\d{4}-\d{2}-\d{2}T", value
        ):
            return (datetime.fromisoformat(value) + delta).isoformat()
        return value

    data = shift(deepcopy(e["data"]))
    cash = data["cash_capture"]
    cash.pop("signature", None)
    cash["signature"] = sign(cash, PIN)
    data.pop("signature", None)
    data["signature"] = sign(data, PIN)
    e["data"].clear()
    e["data"].update(data)
    e["clock"][0] = target + timedelta(seconds=3)

    with e["store"].db() as db:
        for table in ("control", "sim_bridge_health"):
            row = json.loads(db.execute(
                "SELECT data FROM " + table + " WHERE id=1"
            ).fetchone()[0])
            db.execute(
                "UPDATE " + table + " SET data=? WHERE id=1",
                (json.dumps(shift(row)),),
            )
    return target


def emit(e, at):
    append(e["path"], [BULL], at=at.isoformat())
    return e["source"].run_source_once(e["path"])


def no_transport(e):
    with e["adapter_store"].tx() as db:
        for table in ("attempts", "receipts"):
            assert db.execute(
                "SELECT COUNT(*) FROM " + table
            ).fetchone()[0] == 0


def clean(e):
    assert counts(e) == (0, 0, 0, 0, 0, 0)
    assert e["adapter_store"].requests() == []
    with e["store"].db() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?",
            ("preparation_cash_reservations",),
        ).fetchone()
        if exists:
            assert db.execute(
                "SELECT COUNT(*) FROM preparation_cash_reservations"
            ).fetchone()[0] == 0
    no_transport(e)


def last_event(e):
    with e["store"].db() as db:
        return json.loads(db.execute(
            "SELECT data FROM preparation_events "
            "ORDER BY seq DESC LIMIT 1"
        ).fetchone()[0])


@pytest.mark.parametrize("hour,minute,allowed", [
    (9, 10, False),
    (9, 15, True),
    (14, 50, True),
    (14, 55, False),
])
def test_clock_admission(bound_env, hour, minute, allowed):
    e = bound_env
    at = move(e, hour, minute)
    emit(e, at)
    assert e["store"].control()["mode"] == "PAUSED"

    if allowed:
        assert counts(e) == (1, 1, 1, 0, 0, 0)
        assert len(e["adapter_store"].requests()) == 1
        assert len(e["calls"]) == 1
        no_transport(e)
    else:
        clean(e)
        assert e["calls"] == []
        assert "ENTRY_CLOCK_WINDOW_CLOSED" in last_event(e)["reasons"]


def test_cutoff_during_evidence_collection(bound_env):
    e = bound_env
    at = move(e, 14, 50)
    original = e["source"].provider

    def delayed():
        result = original()
        e["clock"][0] = at.replace(hour=14, minute=55)
        return result

    e["source"].provider = delayed
    emit(e, at)
    clean(e)
    assert len(e["calls"]) == 1
    assert e["store"].control()["mode"] == "PAUSED"
    assert "ENTRY_CLOCK_WINDOW_CLOSED" in last_event(e)["reasons"]


def test_cutoff_before_commit_rolls_back(bound_env):
    e = bound_env
    at = move(e, 14, 50)
    reached = []

    def checkpoint(stage):
        if stage == "BEFORE_COMMIT":
            reached.append(stage)
            e["clock"][0] = at.replace(hour=14, minute=55)

    e["source"].checkpoint = checkpoint
    with pytest.raises(
        ValueError, match="^ENTRY_CLOCK_WINDOW_CLOSED_BEFORE_COMMIT$"
    ):
        emit(e, at)

    assert reached == ["BEFORE_COMMIT"]
    clean(e)
    assert e["store"].control()["mode"] == "PAUSED"