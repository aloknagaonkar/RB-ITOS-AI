from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from red_bar_lab.execution.run_market_trend_research_supervisor import (
    AlreadyRunningError,
    MarketTrendResearchProcessLock,
    MarketTrendResearchSupervisor,
    SupervisorConfig,
    SupervisorConfigurationError,
    read_supervisor_state,
)

NOW = datetime(2026, 8, 24, 8, 30, tzinfo=timezone.utc)


class FakeProcess:
    def __init__(self, pid: int = 1234, exit_code=None):
        self.pid = pid
        self.exit_code = exit_code
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.exit_code = 0

    def kill(self):
        self.killed = True
        self.exit_code = -9

    def wait(self, timeout=None):
        return 0 if self.exit_code is None else self.exit_code


def _config(tmp_path: Path) -> SupervisorConfig:
    return SupervisorConfig(
        work_root=tmp_path / "artifacts" / "red_bar" / "market_trend_research",
        heartbeat_seconds=0.01,
        graceful_stop_seconds=0.01,
    )


def test_first_lock_acquires_and_second_reports_already_running(tmp_path):
    path = _config(tmp_path).lock_path
    first = MarketTrendResearchProcessLock(path)
    second = MarketTrendResearchProcessLock(path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunningError, match="ALREADY_RUNNING"):
            second.acquire()
    finally:
        first.release()


def test_stale_pid_metadata_does_not_block_free_lock(tmp_path):
    config = _config(tmp_path)
    config.work_root.mkdir(parents=True)
    config.state_path.write_text(json.dumps({"supervisor_pid": 999999}), encoding="utf-8")
    lock = MarketTrendResearchProcessLock(config.lock_path)
    lock.acquire()
    lock.release()


def test_supervisor_starts_exactly_one_child_without_token_argument(tmp_path, monkeypatch):
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "secret-token")
    monkeypatch.setenv("MARKET_TREND_RESEARCH_CALENDAR_VERIFIED", "true")
    calls = []

    def factory(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    supervisor = MarketTrendResearchSupervisor(
        config=_config(tmp_path),
        process_factory=factory,
        now=lambda: NOW,
    )
    supervisor._validate()
    child = supervisor._start_child()
    assert child.pid == 1234
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[-1] == "red_bar_lab.execution.run_market_trend_research_runtime"
    assert "secret-token" not in " ".join(command)
    assert kwargs["shell"] is False
    assert kwargs["env"]["UPSTOX_ACCESS_TOKEN"] == "secret-token"
    status = read_supervisor_state(supervisor.config.state_path)
    assert status["child_pid"] == 1234
    assert "secret-token" not in supervisor.config.state_path.read_text(encoding="utf-8")
    assert "secret-token" not in supervisor.config.log_path.read_text(encoding="utf-8")


def test_missing_token_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("MARKET_TREND_RESEARCH_CALENDAR_VERIFIED", "true")
    supervisor = MarketTrendResearchSupervisor(config=_config(tmp_path), now=lambda: NOW)
    with pytest.raises(SupervisorConfigurationError, match="UPSTOX_ACCESS_TOKEN_MISSING"):
        supervisor._validate()


def test_unverified_calendar_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "secret-token")
    monkeypatch.delenv("MARKET_TREND_RESEARCH_CALENDAR_VERIFIED", raising=False)
    supervisor = MarketTrendResearchSupervisor(config=_config(tmp_path), now=lambda: NOW)
    with pytest.raises(SupervisorConfigurationError, match="CALENDAR_UNVERIFIED"):
        supervisor._validate()


def test_backoff_is_bounded_and_stable_run_policy_is_configured(tmp_path):
    supervisor = MarketTrendResearchSupervisor(
        config=_config(tmp_path), now=lambda: NOW, random_source=lambda: 0.0
    )
    assert supervisor._backoff_seconds(1) == 2.0
    assert supervisor._backoff_seconds(20) == 60.0
    assert supervisor.config.stable_run_seconds == 120.0
    assert supervisor.config.maximum_rapid_failures == 5


def test_stop_child_targets_only_recorded_child(tmp_path):
    child = FakeProcess()
    supervisor = MarketTrendResearchSupervisor(config=_config(tmp_path), now=lambda: NOW)
    supervisor.child = child
    supervisor._stop_child()
    assert child.terminated is True
    assert child.killed is False


def test_malformed_status_is_unavailable(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not-json", encoding="utf-8")
    assert read_supervisor_state(path) is None


def test_supervisor_has_no_trading_authority_imports():
    source = Path(
        "red_bar_lab/execution/run_market_trend_research_supervisor.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "paper_execution", "opportunity_queue", "reservation", "canonical_bundle"
    ):
        assert forbidden not in source
    assert "shell=True" not in source
