"""Tests for the platform supervisor and CLI validation."""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass
class _FakePopen:
    pid: int = 999
    returncode: int = 1
    stdout = None
    stderr = None

    def poll(self):
        return self.returncode

    def communicate(self, timeout: float = 2.0):
        return (b"UPSTOX_ACCESS_TOKEN is required.\n", b"")


@dataclass
class _FakeManaged:
    name: str
    pid: int = 999
    proc: _FakePopen = None
    command: list = None
    started_at: float = 0.0


def test_platform_config_validation_catches_missing_token(monkeypatch):
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    from red_bar_lab.platform.config import PlatformConfig

    errors = PlatformConfig().validate()
    assert any("UPSTOX_ACCESS_TOKEN" in err for err in errors)


def test_platform_config_validation_catches_bad_underlying(monkeypatch):
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "test-token")
    from red_bar_lab.platform.config import PlatformConfig

    config = PlatformConfig(underlying="BANANA")
    errors = config.validate()
    assert any("Invalid underlying" in err for err in errors)


def test_platform_config_validation_passes_minimum(monkeypatch, tmp_path):
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("RED_BAR_ARTIFACTS_ROOT", str(tmp_path / "artifacts"))
    from red_bar_lab.platform.config import PlatformConfig

    errors = PlatformConfig().validate()
    assert errors == []


def test_control_cli_refuses_to_start_without_token(monkeypatch, capsys):
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    from red_bar_lab.platform import control

    rc = control.main(["start"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "UPSTOX_ACCESS_TOKEN" in captured.err
    assert "refusing to start" in captured.err.lower()


def test_control_cli_refuses_to_restart_without_token(monkeypatch, capsys):
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    from red_bar_lab.platform import control

    rc = control.main(["restart"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "UPSTOX_ACCESS_TOKEN" in captured.err


def test_control_cli_status_does_not_require_token(monkeypatch, capsys):
    """status is a read-only action and should not be blocked by missing token."""
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    from red_bar_lab.platform import control

    rc = control.main(["status"])
    captured = capsys.readouterr()
    # status should not be blocked by the validator
    assert "refusing to start" not in captured.err.lower()
    # exit code may be 0 (ok) or non-zero (no state) but not the 2 we use for validation
    assert rc != 2


def test_process_controller_get_recent_output_returns_child_output():
    from red_bar_lab.platform.process_controller import ProcessController

    controller = ProcessController()
    proc = _FakePopen()
    controller._managed["paper_monitor"] = _FakeManaged(
        name="paper_monitor", proc=proc
    )
    output = controller.get_recent_output("paper_monitor")
    assert "UPSTOX_ACCESS_TOKEN" in output


def test_process_controller_get_recent_output_empty_when_process_running():
    from red_bar_lab.platform.process_controller import ProcessController

    controller = ProcessController()

    class _RunningProc:
        pid = 1234
        stdout = None
        stderr = None

        def poll(self):
            return None  # still running

    controller._managed["x"] = _FakeManaged(name="x", proc=_RunningProc())
    assert controller.get_recent_output("x") == ""


def test_process_controller_get_recent_output_empty_for_unknown_name():
    from red_bar_lab.platform.process_controller import ProcessController

    controller = ProcessController()
    assert controller.get_recent_output("never_started") == ""


def test_supervisor_startup_error_includes_child_output(monkeypatch):
    """When a required child crashes at startup, the RuntimeError must
    include the child's last stdout/stderr lines, not just the exit code."""
    from red_bar_lab.platform import supervisor as sup
    from red_bar_lab.platform.config import PlatformConfig
    from red_bar_lab.platform.process_controller import ManagedProcess

    fake_proc = _FakePopen()

    class FakeController:
        def start(self, name, command, env_extras=None):
            return ManagedProcess(
                name=name, pid=fake_proc.pid, proc=fake_proc, command=command
            )

        def is_running(self, name):
            return False

        def get_exit_code(self, name):
            return 1

        def get_recent_output(self, name, max_lines=20):
            return "UPSTOX_ACCESS_TOKEN is required.\nlast line"

    class FakeStateStore:
        def __init__(self):
            self.writes = []

        def write_component(self, comp):
            self.writes.append(comp)

    class FakeSpec:
        name = "paper_monitor"
        required = True
        startup_timeout_seconds = 0.1
        restart = False

        def command(self, project_root):
            return ["python", "-c", "pass"]

        env_extras = {}

    config = PlatformConfig()
    state_store = FakeStateStore()
    instance = sup.PlatformSupervisor.__new__(sup.PlatformSupervisor)
    instance.config = config
    instance._state_store = state_store
    instance._controller = FakeController()
    instance._shutdown_requested = False

    with pytest.raises(RuntimeError) as exc_info:
        instance._start_component(FakeSpec())
    msg = str(exc_info.value)
    assert "paper_monitor" in msg
    assert "code=1" in msg
    assert "UPSTOX_ACCESS_TOKEN is required" in msg
    # The state store should also have received the crash with child output
    crash = next(w for w in state_store.writes if w.state == "CRASHED")
    assert "UPSTOX_ACCESS_TOKEN" in crash.last_error


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
