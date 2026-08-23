from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time
from enum import Enum
import os
from pathlib import Path
import signal
from threading import Event
from typing import Mapping
from zoneinfo import ZoneInfo

from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution.paper_engine import RedBarPaperExecutionEngine
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_models import (
    PaperCanaryCycleOutcome,
    PaperCanaryCycleResult,
    PaperCanaryPolicy,
    PaperCanaryPrerequisites,
    PaperCanaryRuntimeState,
    PaperCanaryWorkerStatus,
    initial_runtime_state,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_repository import (
    SQLiteCanonicalPaperCandidateRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_runtime import PaperCanaryRuntime
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_state_store import (
    AtomicJsonPaperCanaryStateStore,
    PaperCanaryStateCorruptionError,
    PaperCanaryStateStorageError,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_adapter import (
    ExistingPaperContractSelector,
    ExistingRedBarPaperAdapter,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_ledger import (
    StrictSQLiteCanonicalPaperExecutionRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data import (
    PaperMarketDataConfigurationError,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_factory import (
    build_paper_canary_market_data,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_recovery import (
    ControlledCanonicalPaperRecoveryService,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_replay_guard import (
    ReplayGuardedCanonicalPaperService,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_repository import (
    SQLiteCanonicalReservationRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.reservation_service import (
    RedBarV2CanonicalReservationService,
)
from red_bar_lab.storage.database import RedBarDatabase

IST = ZoneInfo("Asia/Kolkata")


class PaperCanaryStartupAction(str, Enum):
    DISABLED = "DISABLED"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    PAPER_CANARY = "PAPER_CANARY"


@dataclass(frozen=True, slots=True)
class PaperCanaryStartupDecision:
    action: PaperCanaryStartupAction
    reason_code: str
    runtime_construction_allowed: bool


def evaluate_paper_canary_startup(settings: RedBarSettings) -> PaperCanaryStartupDecision:
    """Pure startup policy. Reads settings only and performs no I/O."""
    if not settings.red_bar_v2_paper_canary_worker_enabled:
        return PaperCanaryStartupDecision(PaperCanaryStartupAction.DISABLED, "WORKER_DISABLED", False)
    mode = settings.red_bar_v2_canonical_paper_execution_mode
    if mode == "OBSERVE_ONLY":
        return PaperCanaryStartupDecision(PaperCanaryStartupAction.OBSERVE_ONLY, "OBSERVE_ONLY", False)
    if mode != "PAPER_CANARY":
        return PaperCanaryStartupDecision(PaperCanaryStartupAction.CONFIGURATION_INVALID, "INVALID_PAPER_EXECUTION_MODE", False)
    prerequisites = (
        (settings.red_bar_v2_canonical_shadow_enabled, "CANONICAL_SHADOW_DISABLED"),
        (settings.red_bar_v2_canonical_reservation_enabled, "CANONICAL_RESERVATION_DISABLED"),
        (settings.red_bar_v2_canonical_paper_execution_enabled, "CANONICAL_PAPER_EXECUTION_DISABLED"),
    )
    for enabled, reason_code in prerequisites:
        if not enabled:
            return PaperCanaryStartupDecision(PaperCanaryStartupAction.CONFIGURATION_INVALID, reason_code, False)
    provider = settings.red_bar_v2_paper_canary_market_data_provider
    if provider == "UNCONFIGURED":
        return PaperCanaryStartupDecision(PaperCanaryStartupAction.CONFIGURATION_INVALID, "MARKET_DATA_PROVIDER_UNCONFIGURED", False)
    if provider not in {"ZERODHA", "UPSTOX"}:
        return PaperCanaryStartupDecision(PaperCanaryStartupAction.CONFIGURATION_INVALID, "MARKET_DATA_PROVIDER_INVALID", False)
    return PaperCanaryStartupDecision(PaperCanaryStartupAction.PAPER_CANARY, "PAPER_CANARY_STARTUP_ALLOWED", True)


def _market_session_active(now: datetime | None = None) -> bool:
    current = (now or datetime.now(IST)).astimezone(IST)
    return current.weekday() < 5 and time(9, 15) <= current.time().replace(tzinfo=None) <= time(15, 30)


class ExchangeClock:
    def now(self) -> datetime:
        return datetime.now(IST)


class _SessionClosedCandidateRepository:
    def list_candidates(self, **kwargs):
        return ()


class SessionAwarePaperCanaryRuntime(PaperCanaryRuntime):
    """Runs recovery first off-session and records escaped process failures."""

    def record_process_boundary_failure(self, *, failed_at: datetime, reason_code: str) -> PaperCanaryRuntimeState:
        if not isinstance(failed_at, datetime) or failed_at.tzinfo is None or failed_at.utcoffset() is None:
            raise ValueError("failed_at must be timezone-aware")
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise ValueError("reason_code must be non-empty")
        state = self.state_store.load() or initial_runtime_state()
        failed = self._failure_state(
            state,
            now=failed_at,
            reason=reason_code,
            status=PaperCanaryWorkerStatus.ENTRY_SUSPENDED,
        )
        return self._safe_save(failed)

    def run_cycle(self):
        cycle_now = self.clock.now()
        session_active = _market_session_active(cycle_now)
        original_prerequisites = self.prerequisites
        original_candidates = self.candidate_repository
        self.prerequisites = replace(original_prerequisites, market_session_active=session_active)
        if not session_active:
            self.candidate_repository = _SessionClosedCandidateRepository()
        try:
            result = super().run_cycle()
            if not session_active and result.outcome is PaperCanaryCycleOutcome.HEALTHY_IDLE:
                suspended = replace(
                    result.state,
                    worker_status=PaperCanaryWorkerStatus.ENTRY_SUSPENDED,
                    entry_suspended=True,
                    latest_reason_code="MARKET_SESSION_CLOSED",
                )
                try:
                    suspended = self._safe_save(suspended)
                except PaperCanaryStateStorageError:
                    return PaperCanaryCycleResult(
                        PaperCanaryCycleOutcome.STORAGE_UNAVAILABLE,
                        "RUNTIME_STATE_SAVE_FAILED",
                        replace(suspended, persistence_status="STATE_UNAVAILABLE"),
                        result.execution_results,
                    )
                return PaperCanaryCycleResult(
                    PaperCanaryCycleOutcome.ENTRY_SUSPENDED,
                    "MARKET_SESSION_CLOSED",
                    suspended,
                    result.execution_results,
                )
            return result
        finally:
            self.prerequisites = original_prerequisites
            self.candidate_repository = original_candidates


class PaperCanaryProcessLock:
    """Non-blocking OS ownership lock with bounded PID metadata."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._file = None
        self._locked = False

    def _try_os_lock(self) -> None:
        if os.name == "nt":
            import msvcrt
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self) -> None:
        if os.name == "nt":
            import msvcrt
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)

    def acquire(self) -> bool:
        if self._locked:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("a+b")
            if self.path.stat().st_size == 0:
                self._file.write(b"0")
                self._file.flush()
            self._try_os_lock()
            self._locked = True
            self._file.seek(0)
            self._file.truncate(0)
            self._file.write(f"pid={os.getpid()}\n".encode("ascii")[:64])
            self._file.flush()
            os.fsync(self._file.fileno())
            return True
        except (OSError, BlockingIOError):
            if self._file is not None:
                try:
                    self._file.close()
                except OSError:
                    pass
            self._file = None
            self._locked = False
            return False

    def release(self) -> None:
        if self._file is None:
            self._locked = False
            return
        try:
            if self._locked:
                try:
                    self._unlock()
                except OSError:
                    pass
        finally:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
            self._locked = False

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("PAPER_CANARY_PROCESS_OWNERSHIP_UNAVAILABLE")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def build_runtime(
    settings: RedBarSettings,
    *,
    environment: Mapping[str, str] | None = None,
) -> PaperCanaryRuntime:
    """Single composition root for normalized read-only market data and virtual paper."""
    market_data = build_paper_canary_market_data(
        settings=settings,
        environment=environment if environment is not None else os.environ,
    )
    database = RedBarDatabase(settings.database_path)
    database.initialize()
    paper_engine = RedBarPaperExecutionEngine(database, settings)
    execution_repository = StrictSQLiteCanonicalPaperExecutionRepository(settings.database_path)
    reservation_repository = SQLiteCanonicalReservationRepository(settings.database_path)
    reservation_service = RedBarV2CanonicalReservationService(
        reservation_repository,
        enabled=settings.red_bar_v2_canonical_reservation_enabled,
        lease_seconds=settings.red_bar_v2_canonical_reservation_lease_seconds,
        maximum_bundle_age_seconds=settings.red_bar_v2_canonical_reservation_max_bundle_age_seconds,
    )
    selector = ExistingPaperContractSelector(
        engine=paper_engine,
        market_data=market_data,
        underlying_name=settings.default_underlying,
    )
    adapter = ExistingRedBarPaperAdapter(
        engine=paper_engine,
        market_data=market_data,
        database_path=settings.database_path,
        underlying_name=settings.default_underlying,
    )
    execution_service = ReplayGuardedCanonicalPaperService(
        database_path=settings.database_path,
        repository=execution_repository,
        reservation_service=reservation_service,
        selector=selector,
        adapter=adapter,
        enabled=settings.red_bar_v2_canonical_paper_execution_enabled,
        mode=settings.red_bar_v2_canonical_paper_execution_mode,
    )
    recovery_service = ControlledCanonicalPaperRecoveryService(
        repository=execution_repository,
        adapter=adapter,
        reservation_service=reservation_service,
    )
    prerequisites = PaperCanaryPrerequisites(
        shadow_enabled=settings.red_bar_v2_canonical_shadow_enabled,
        reservation_enabled=settings.red_bar_v2_canonical_reservation_enabled,
        paper_execution_enabled=settings.red_bar_v2_canonical_paper_execution_enabled,
        paper_execution_mode=settings.red_bar_v2_canonical_paper_execution_mode,
        worker_enabled=settings.red_bar_v2_paper_canary_worker_enabled,
        market_session_active=True,
    )
    policy = PaperCanaryPolicy(
        poll_seconds=settings.red_bar_v2_paper_canary_poll_seconds,
        max_actions_per_cycle=settings.red_bar_v2_paper_canary_max_actions_per_cycle,
        max_actions_per_day=settings.red_bar_v2_paper_canary_max_actions_per_day,
        max_bundle_age_seconds=settings.red_bar_v2_paper_canary_max_bundle_age_seconds,
        failure_threshold=settings.red_bar_v2_paper_canary_failure_threshold,
        required_probe_cycles=settings.red_bar_v2_paper_canary_required_probe_cycles,
    )
    return SessionAwarePaperCanaryRuntime(
        state_store=AtomicJsonPaperCanaryStateStore(settings.paper_canary_state_path),
        candidate_repository=SQLiteCanonicalPaperCandidateRepository(settings.database_path),
        recovery_service=recovery_service,
        execution_service=execution_service,
        execution_repository=execution_repository,
        clock=ExchangeClock(),
        prerequisites=prerequisites,
        policy=policy,
    )


def run_once(settings: RedBarSettings):
    decision = evaluate_paper_canary_startup(settings)
    if not decision.runtime_construction_allowed:
        raise RuntimeError(decision.reason_code)
    return build_runtime(settings).run_cycle()


def install_signal_handlers(stop_requested: Event) -> None:
    def request_stop(signum, frame) -> None:
        stop_requested.set()
    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is not None:
            try:
                signal.signal(signum, request_stop)
            except (ValueError, OSError):
                pass


def emit_bounded_status(result) -> None:
    print(
        "paper_canary "
        f"outcome={result.outcome.value} "
        f"reason={result.reason_code} "
        f"circuit={result.state.circuit_state.value} "
        f"attempted={result.state.attempted_count}"
    )


def _emit_startup(decision: PaperCanaryStartupDecision) -> None:
    print(f"paper_canary outcome={decision.action.value} reason={decision.reason_code}")


def main(argv: list[str] | None = None) -> int:
    settings = RedBarSettings.from_env()
    decision = evaluate_paper_canary_startup(settings)
    if decision.action in {PaperCanaryStartupAction.DISABLED, PaperCanaryStartupAction.OBSERVE_ONLY}:
        _emit_startup(decision)
        return 0
    if decision.action is PaperCanaryStartupAction.CONFIGURATION_INVALID:
        _emit_startup(decision)
        return 2

    process_lock = PaperCanaryProcessLock(settings.artifacts_root / "red_bar_v2_paper_canary.lock")
    if not process_lock.acquire():
        print("paper_canary outcome=ENTRY_SUSPENDED reason=PROCESS_OWNERSHIP_UNAVAILABLE")
        return 3
    stop_requested = Event()
    install_signal_handlers(stop_requested)
    try:
        try:
            runtime = build_runtime(settings)
        except PaperMarketDataConfigurationError as exc:
            print(f"paper_canary outcome=CONFIGURATION_INVALID reason={str(exc)}")
            return 2
        except Exception:
            print("paper_canary outcome=CONFIGURATION_INVALID reason=RUNTIME_CONSTRUCTION_FAILED")
            return 2
        while not stop_requested.is_set():
            try:
                emit_bounded_status(runtime.run_cycle())
            except Exception:
                try:
                    state = runtime.record_process_boundary_failure(
                        failed_at=runtime.clock.now(),
                        reason_code="WORKER_CYCLE_FAILED",
                    )
                    print(
                        "paper_canary outcome=ENTRY_SUSPENDED "
                        f"reason=WORKER_CYCLE_FAILED circuit={state.circuit_state.value}"
                    )
                except (PaperCanaryStateStorageError, PaperCanaryStateCorruptionError, OSError):
                    print("paper_canary outcome=STORAGE_UNAVAILABLE reason=RUNTIME_STATE_FAILURE_UNPERSISTED")
                    return 4
            stop_requested.wait(settings.red_bar_v2_paper_canary_poll_seconds)
        return 0
    finally:
        process_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
