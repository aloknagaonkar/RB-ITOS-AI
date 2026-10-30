"""Synthetic signal admission; existing temporary database fixtures only."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile

import pytest

from test_hilega_application_preparation_v1 import (
    env, append, BULL, counts,
)
from test_hilega_atomic_disabled_binding_v1 import bound_env


def isolated(e):
    app = e["store"].path.resolve()
    broker = e["adapter_store"].path.resolve()
    assert app != broker
    assert app.parent == broker.parent
    assert app.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert any(part.startswith("pytest-") for part in app.parts)


def reservations(e):
    with e["store"].db() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            ("preparation_cash_reservations",),
        ).fetchone()
        return db.execute(
            "SELECT COUNT(*) FROM preparation_cash_reservations"
        ).fetchone()[0] if exists else 0


def no_transport(e):
    with e["adapter_store"].tx() as db:
        for table in ("attempts", "receipts"):
            assert db.execute(
                "SELECT COUNT(*) FROM " + table
            ).fetchone()[0] == 0


@pytest.mark.parametrize("case", ["stale", "future", "pre_resume"])
def test_invalid_signal_stops_before_evidence(bound_env, case):
    e = bound_env
    isolated(e)
    now = e["clock"][0]
    if case == "stale":
        at = now - timedelta(seconds=61)
    elif case == "future":
        at = now + timedelta(seconds=1)
    else:
        at = datetime.fromisoformat(
            e["store"].control()["resumed_at"])

    calls = len(e["calls"])
    append(e["path"], [BULL], at=at.isoformat())
    e["source"].run_source_once(e["path"])

    assert len(e["calls"]) == calls
    assert counts(e) == (0, 0, 0, 0, 0, 0)
    assert reservations(e) == 0
    assert e["adapter_store"].requests() == []
    assert e["store"].control()["mode"] == "PAUSED"
    no_transport(e)

    with e["store"].db() as db:
        event = json.loads(db.execute(
            "SELECT data FROM preparation_events "
            "ORDER BY seq DESC LIMIT 1"
        ).fetchone()[0])
    assert event["status"] == "BLOCKED"
    assert "SIGNAL_STALE_FUTURE_OR_PRE_RESUME" in event["reasons"]


def test_fresh_signal_replay_preserves_single_reservation(bound_env):
    e = bound_env
    isolated(e)
    at = (e["clock"][0] - timedelta(seconds=3)).isoformat()
    append(e["path"], [BULL], at=at)
    e["source"].run_source_once(e["path"])

    assert counts(e) == (1, 1, 1, 0, 0, 0)
    assert reservations(e) == 1
    original = e["adapter_store"].requests()
    assert len(original) == 1
    assert len(e["calls"]) == 1

    e["source"].run_source_once(e["path"])
    append(e["path"], [BULL], at=at)
    e["source"].run_source_once(e["path"])

    assert counts(e) == (1, 1, 1, 0, 0, 0)
    assert reservations(e) == 1
    assert e["adapter_store"].requests() == original
    assert len(e["calls"]) == 1
    assert e["store"].control()["mode"] == "PAUSED"
    no_transport(e)