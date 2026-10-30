"""Actual preparation Source + staged worker boundary; fixture execution only."""
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from test_automatic_entry_fixture import synthetic_scope, env, bound_env
from test_hilega_application_preparation_v1 import append, BULL
from fixture_journal_consumer import FixtureConsumer
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.adapter import Store, FixtureTransport

CANDIDATE = Path(
    "hilega-worker-handoff-stage-51fc37nx/hilega_production_simulator_bridge.py"
)
INSTALLED = Path("scripts/hilega_production_simulator_bridge.py")
EXPECTED = "24a2d5b3ded4c929016c9dcc55933e19141dd19371dd44ce654d61a8ef2fa16c"
ORIGINAL = "9fd8bc6b22af63229f59743722cfb156b12feb0ca279bc2117a103d02670de98"


@pytest.fixture
def worker():
    for p, expected in ((CANDIDATE, EXPECTED), (INSTALLED, ORIGINAL)):
        assert p.is_file() and not p.is_symlink()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == expected
    spec = importlib.util.spec_from_file_location("staged_worker_handoff", CANDIDATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    assert hashlib.sha256(INSTALLED.read_bytes()).hexdigest() == ORIGINAL


def test_default_worker_handoff_is_closed(worker, bound_env):
    e = bound_env
    append(e["path"], [BULL])
    result = worker.preparation_tick(e["source"], e["path"])

    assert len(e["adapter_store"].requests()) == 1
    assert result["execution_handoff"] == dict(
        status="APPLICATION_HANDOFF_CLOSED",
        production_execution_enabled=False,
        orders_sent_to_upstox=False,
        transport_attempt_created=False,
    )
    with e["adapter_store"].tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert e["store"].control()["mode"] == "PAUSED"


def test_source_failure_prevents_handoff(worker, bound_env):
    e = bound_env
    handoff = Mock(side_effect=AssertionError("Handoff must not run"))
    with patch.object(
        e["source"], "run_source_once",
        side_effect=ValueError("SYNTHETIC_SOURCE_FAILURE"),
    ):
        with pytest.raises(ValueError, match="^SYNTHETIC_SOURCE_FAILURE$"):
            worker.preparation_tick(
                e["source"], e["path"], test_handoff=handoff)
    handoff.assert_not_called()


def test_worker_tick_drives_fake_entry_and_replay(worker, bound_env, tmp_path):
    e = bound_env
    execution = Store(
        tmp_path / "worker-execution.sqlite", PIN["scope"], "OFFLINE_FIXTURE")
    consumer = FixtureConsumer(
        e["store"].path, e["adapter_store"].path,
        execution, PIN, e["path"],
    )
    calls = []

    def handoff():
        calls.append(1)
        return consumer.poll(as_of=e["clock"][0].isoformat())

    append(e["path"], [BULL])
    first = worker.preparation_tick(
        e["source"], e["path"], test_handoff=handoff)
    second = worker.preparation_tick(
        e["source"], e["path"], test_handoff=handoff)

    assert first["execution_handoff"]["processed_record_count"] == 1
    assert second["execution_handoff"]["processed_record_count"] == 0
    assert len(calls) == 2
    assert len(FixtureTransport(execution).orders()) == 1
    with execution.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    with e["adapter_store"].tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert e["store"].control()["mode"] == "PAUSED"


def test_result_retains_worker_health_input_and_json_shape(worker, bound_env):
    e = bound_env
    # No execution event is needed to verify result compatibility.
    result = worker.preparation_tick(e["source"], e["path"])
    assert "source_at" in result
    assert result["production_execution_enabled"] is False
    assert result["execution_handoff"]["status"] == "APPLICATION_HANDOFF_CLOSED"
    assert json.loads(json.dumps(result)) == result