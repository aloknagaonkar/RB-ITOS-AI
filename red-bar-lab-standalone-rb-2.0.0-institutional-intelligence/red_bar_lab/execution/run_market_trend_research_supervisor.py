from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
from threading import Event
from time import monotonic
from typing import Callable, Mapping, Protocol

from red_bar_lab.config import RedBarSettings

AUTHORITY = "OBSERVATIONAL_ONLY"


class SupervisorConfigurationError(RuntimeError):
    pass


class AlreadyRunningError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SupervisorConfig:
    work_root: Path
    initial_backoff_seconds: float = 2.0
    maximum_backoff_seconds: float = 60.0
    stable_run_seconds: float = 120.0
    maximum_rapid_failures: int = 5
    circuit_cooldown_seconds: float = 300.0
    heartbeat_seconds: float = 2.0
    graceful_stop_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.initial_backoff_seconds <= 0:
            raise ValueError("initial_backoff_seconds invalid")
        if self.maximum_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("maximum_backoff_seconds invalid")
        if self.stable_run_seconds <= 0 or self.maximum_rapid_failures < 1:
            raise ValueError("restart policy invalid")
        if self.circuit_cooldown_seconds <= 0 or self.heartbeat_seconds <= 0:
            raise ValueError("supervisor timing invalid")

    @property
    def lock_path(self) -> Path:
        return self.work_root / "supervisor.lock"

    @property
    def state_path(self) -> Path:
        return self.work_root / "supervisor_state.json"

    @property
    def stop_request_path(self) -> Path:
        return self.work_root / "stop.request"

    @property
    def log_path(self) -> Path:
        return self.work_root / "logs" / "supervisor.log"


@dataclass(frozen=True, slots=True)
class SupervisorState:
    supervisor_state: str
    supervisor_pid: int
    child_pid: int | None
    supervisor_started_at: str
    heartbeat_at: str
    child_started_at: str | None = None
    last_child_exit_at: str | None = None
    last_child_exit_code: int | None = None
    restart_count: int = 0
    consecutive_rapid_failures: int = 0
    next_restart_at: str | None = None
    safe_reason: str | None = None
    authority: str = AUTHORITY


class ChildProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


class MarketTrendResearchProcessLock:
    """OS-level single-owner lock held for the supervisor lifetime."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise AlreadyRunningError("ALREADY_RUNNING") from exc
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> "MarketTrendResearchProcessLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_reason(value: object) -> str:
    text = str(value).strip().upper()
    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in text)
    return (cleaned or "UNKNOWN")[:64]


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_supervisor_state(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _logger(config: SupervisorConfig) -> logging.Logger:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("market_trend_research_supervisor")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        config.log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


class MarketTrendResearchSupervisor:
    def __init__(
        self,
        *,
        config: SupervisorConfig,
        process_factory: Callable[..., ChildProcess] = subprocess.Popen,
        now: Callable[[], datetime] = _utc_now,
        monotonic_clock: Callable[[], float] = monotonic,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self.config = config
        self.process_factory = process_factory
        self.now = now
        self.monotonic_clock = monotonic_clock
        self.random_source = random_source
        self.stop_event = Event()
        self.child: ChildProcess | None = None
        started = self.now().isoformat()
        self.state = SupervisorState(
            supervisor_state="STARTING",
            supervisor_pid=os.getpid(),
            child_pid=None,
            supervisor_started_at=started,
            heartbeat_at=started,
        )
        self.logger = _logger(config)

    def request_stop(self) -> None:
        self.stop_event.set()

    def _publish(self, state: str | None = None, **changes: object) -> None:
        values = {"heartbeat_at": self.now().isoformat(), **changes}
        if state is not None:
            values["supervisor_state"] = state
        self.state = replace(self.state, **values)
        _atomic_json(self.config.state_path, asdict(self.state))
        self.logger.info(json.dumps({
            "timestamp": self.state.heartbeat_at,
            "event": "SUPERVISOR_STATE",
            "state": self.state.supervisor_state,
            "safe_reason": self.state.safe_reason,
            "restart_count": self.state.restart_count,
            "child_exit_code": self.state.last_child_exit_code,
        }, sort_keys=True))

    def _validate(self) -> None:
        if not os.getenv("UPSTOX_ACCESS_TOKEN", "").strip():
            raise SupervisorConfigurationError("UPSTOX_ACCESS_TOKEN_MISSING")
        if os.getenv("MARKET_TREND_RESEARCH_PROVIDER", "UPSTOX").strip().upper() != "UPSTOX":
            raise SupervisorConfigurationError("MARKET_TREND_RESEARCH_PROVIDER_UNSUPPORTED")
        if os.getenv("MARKET_TREND_RESEARCH_CALENDAR_VERIFIED", "").strip().lower() not in {"1", "true", "yes", "on"}:
            raise SupervisorConfigurationError("CALENDAR_UNVERIFIED")

    def _child_environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment["MARKET_TREND_RESEARCH_RUNTIME_ENABLED"] = "true"
        environment["MARKET_TREND_RESEARCH_PROVIDER"] = "UPSTOX"
        environment["MARKET_TREND_RESEARCH_UNATTENDED"] = "true"
        return environment

    def _start_child(self) -> ChildProcess:
        command = [
            sys.executable,
            "-m",
            "red_bar_lab.execution.run_market_trend_research_runtime",
        ]
        child = self.process_factory(
            command,
            env=self._child_environment(),
            shell=False,
            cwd=str(Path.cwd()),
        )
        self.child = child
        started = self.now().isoformat()
        self._publish(
            "RUNNING",
            child_pid=child.pid,
            child_started_at=started,
            next_restart_at=None,
            safe_reason=None,
        )
        return child

    def _stop_child(self) -> None:
        child = self.child
        if child is None or child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=self.config.graceful_stop_seconds)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5.0)

    def _backoff_seconds(self, rapid_failures: int) -> float:
        base = min(
            self.config.maximum_backoff_seconds,
            self.config.initial_backoff_seconds * (2 ** max(0, rapid_failures - 1)),
        )
        return min(
            self.config.maximum_backoff_seconds,
            base + base * 0.25 * self.random_source(),
        )

    def _wait_with_heartbeat(self, seconds: float, *, state: str) -> bool:
        deadline = self.monotonic_clock() + max(0.0, seconds)
        while not self.stop_event.is_set():
            if self.config.stop_request_path.exists():
                self.request_stop()
                return True
            remaining = deadline - self.monotonic_clock()
            if remaining <= 0:
                return False
            self._publish(state)
            self.stop_event.wait(min(self.config.heartbeat_seconds, remaining))
        return True

    def run(self) -> int:
        self.config.work_root.mkdir(parents=True, exist_ok=True)
        lock = MarketTrendResearchProcessLock(self.config.lock_path)
        try:
            lock.acquire()
        except AlreadyRunningError:
            return 3
        try:
            self.config.stop_request_path.unlink(missing_ok=True)
            try:
                self._validate()
            except SupervisorConfigurationError as exc:
                self._publish("CONFIGURATION_ERROR", safe_reason=_safe_reason(exc))
                return 2

            rapid_failures = 0
            restart_count = 0
            while not self.stop_event.is_set():
                if self.config.stop_request_path.exists():
                    self.request_stop()
                    break
                child = self._start_child()
                child_started_mono = self.monotonic_clock()
                while not self.stop_event.wait(self.config.heartbeat_seconds):
                    if self.config.stop_request_path.exists():
                        self.request_stop()
                        break
                    exit_code = child.poll()
                    if exit_code is None:
                        self._publish("RUNNING")
                        continue
                    runtime_seconds = self.monotonic_clock() - child_started_mono
                    rapid_failures = (
                        0
                        if runtime_seconds >= self.config.stable_run_seconds
                        else rapid_failures + 1
                    )
                    restart_count += 1
                    self._publish(
                        "BACKING_OFF",
                        child_pid=None,
                        last_child_exit_at=self.now().isoformat(),
                        last_child_exit_code=exit_code,
                        restart_count=restart_count,
                        consecutive_rapid_failures=rapid_failures,
                        safe_reason="UNEXPECTED_CHILD_EXIT",
                    )
                    self.child = None
                    break
                if self.stop_event.is_set():
                    break
                if child.poll() is None:
                    continue
                if rapid_failures >= self.config.maximum_rapid_failures:
                    next_restart = self.now() + timedelta(
                        seconds=self.config.circuit_cooldown_seconds
                    )
                    self._publish(
                        "CIRCUIT_OPEN",
                        next_restart_at=next_restart.isoformat(),
                        safe_reason="RAPID_FAILURE_THRESHOLD_REACHED",
                    )
                    if self._wait_with_heartbeat(
                        self.config.circuit_cooldown_seconds,
                        state="CIRCUIT_OPEN",
                    ):
                        break
                    rapid_failures = 0
                else:
                    delay = self._backoff_seconds(rapid_failures)
                    self._publish(
                        "BACKING_OFF",
                        next_restart_at=(
                            self.now() + timedelta(seconds=delay)
                        ).isoformat(),
                    )
                    if self._wait_with_heartbeat(delay, state="BACKING_OFF"):
                        break

            self._publish("STOPPING", safe_reason="STOP_REQUESTED")
            self._stop_child()
            self.child = None
            self._publish("STOPPED", child_pid=None, next_restart_at=None)
            return 0
        finally:
            self.config.stop_request_path.unlink(missing_ok=True)
            lock.release()


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def supervisor_config() -> SupervisorConfig:
    settings = RedBarSettings.from_env()
    root = settings.artifacts_root / "market_trend_research"
    return SupervisorConfig(
        work_root=root,
        initial_backoff_seconds=_float(
            "MARKET_TREND_RESEARCH_SUPERVISOR_INITIAL_BACKOFF_SECONDS", 2.0
        ),
        maximum_backoff_seconds=_float(
            "MARKET_TREND_RESEARCH_SUPERVISOR_MAX_BACKOFF_SECONDS", 60.0
        ),
        stable_run_seconds=_float(
            "MARKET_TREND_RESEARCH_SUPERVISOR_STABLE_RUN_SECONDS", 120.0
        ),
        maximum_rapid_failures=_int(
            "MARKET_TREND_RESEARCH_SUPERVISOR_MAX_RAPID_FAILURES", 5
        ),
        circuit_cooldown_seconds=_float(
            "MARKET_TREND_RESEARCH_SUPERVISOR_CIRCUIT_COOLDOWN_SECONDS", 300.0
        ),
    )


def main() -> int:
    supervisor = MarketTrendResearchSupervisor(config=supervisor_config())

    def _handle_signal(_signum, _frame) -> None:
        supervisor.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)
    outcome = supervisor.run()
    label = {
        0: "STOPPED",
        2: "CONFIGURATION_ERROR",
        3: "ALREADY_RUNNING",
    }.get(outcome, "FAILED")
    print(
        f"market-trend-research-supervisor outcome={label} "
        f"authority={AUTHORITY}"
    )
    return outcome


if __name__ == "__main__":
    raise SystemExit(main())
