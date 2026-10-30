"""Staged worker main() routing; all runtime dependencies mocked."""
from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from test_worker_handoff import worker


@pytest.fixture
def main_env(worker, monkeypatch, tmp_path):
    import sys
    import market_lab.hilega_preparation_runtime_v1 as preparation
    import market_lab.hilega_preparation_runtime_v1.source as source
    import market_lab.hilega_production_bridge_health_v1 as health
    import market_lab.hilega_combined_policy_v1 as policy

    monkeypatch.setenv("HILEGA_PRODUCTION_WORKSPACE_MODE", "SIMULATION_ONLY")
    monkeypatch.setenv("HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED", "1")
    monkeypatch.setattr(policy, "POLICY_ID", worker.POLICY)
    monkeypatch.setattr(policy, "VERSION", worker.VERSION)

    store = Mock()
    store.path = tmp_path / "unused-application.sqlite"
    service = Mock()
    monkeypatch.setattr(worker, "Store", Mock(return_value=store))
    monkeypatch.setattr(worker, "SimBroker", Mock())
    monkeypatch.setattr(worker, "Service", Mock(return_value=service))

    preparation_bridge = Mock()
    simulator_bridge = Mock()
    for bridge in (preparation_bridge, simulator_bridge):
        bridge.run_source_once.return_value = dict(
            status="SYNTHETIC_SOURCE_PROCESSED", source_at=None)
    preparation_bridge.poll.return_value = dict(
        status="PREPARATION_ONLY_NO_BROKER_RECONCILIATION")
    simulator_bridge.poll.return_value = dict(
        status="RECONCILED_OFFLINE_FIXTURE")

    preparation_factory = Mock(return_value=preparation_bridge)
    simulator_factory = Mock(return_value=simulator_bridge)
    monkeypatch.setattr(source, "Source", preparation_factory)
    monkeypatch.setattr(worker, "Bridge", simulator_factory)

    monkeypatch.setattr(health, "worker_lock", lambda path: nullcontext())
    monkeypatch.setattr(health, "claim", Mock(return_value="synthetic-run"))
    heartbeat = Mock(return_value={"healthy": True})
    finish = Mock()
    monkeypatch.setattr(health, "heartbeat", heartbeat)
    monkeypatch.setattr(health, "finish", finish)

    argv = [
        "staged-worker", "--once",
        "--env-file", str(tmp_path / "nonexistent.env"),
        "--source", str(tmp_path / "unused-journal.jsonl"),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return dict(
        preparation=preparation,
        prep=preparation_bridge, sim=simulator_bridge,
        prep_factory=preparation_factory,
        sim_factory=simulator_factory,
        heartbeat=heartbeat, finish=finish,
        service=service, argv=argv,
    )


@pytest.mark.parametrize("route", ["PREPARATION_ONLY", "SIMULATOR"])
def test_main_selects_correct_route(worker, main_env, monkeypatch, route):
    e = main_env
    monkeypatch.setattr(e["preparation"], "route", lambda: route)
    tick = Mock(wraps=worker.preparation_tick)
    monkeypatch.setattr(worker, "preparation_tick", tick)

    assert worker.main() == 0
    if route == "PREPARATION_ONLY":
        e["prep_factory"].assert_called_once()
        e["sim_factory"].assert_not_called()
        tick.assert_called_once()
        # main() supplies no injected execution callback.
        assert tick.call_args.kwargs == {}
        e["prep"].run_source_once.assert_called_once()
    else:
        e["sim_factory"].assert_called_once()
        e["prep_factory"].assert_not_called()
        tick.assert_not_called()
        e["sim"].run_source_once.assert_called_once()

    e["service"].watch_bridge_health.assert_called_once()
    e["finish"].assert_called_once()


@pytest.mark.parametrize("arguments", [
    ["--synthetic-cash", "1000"],
    ["--synthetic-fills"],
])
def test_preparation_main_rejects_synthetic_cli_options(
    worker, main_env, monkeypatch, arguments,
):
    e = main_env
    monkeypatch.setattr(e["preparation"], "route", lambda: "PREPARATION_ONLY")
    e["argv"].extend(arguments)
    with pytest.raises(
        ValueError, match="^SYNTHETIC_OPTIONS_FORBIDDEN_ON_PREPARATION_ROUTE$"
    ):
        worker.main()
    e["prep_factory"].assert_not_called()
    e["sim_factory"].assert_not_called()


def test_main_source_failure_reports_health_and_finishes(
    worker, main_env, monkeypatch,
):
    e = main_env
    monkeypatch.setattr(e["preparation"], "route", lambda: "PREPARATION_ONLY")
    e["prep"].run_source_once.side_effect = ValueError("SYNTHETIC_SOURCE_FAILURE")
    with pytest.raises(ValueError, match="^SYNTHETIC_SOURCE_FAILURE$"):
        worker.main()
    assert e["heartbeat"].call_args.kwargs["problem"] == "SOURCE_OR_WORKER_ERROR"
    e["finish"].assert_called_once()
    e["service"].watch_bridge_health.assert_not_called()