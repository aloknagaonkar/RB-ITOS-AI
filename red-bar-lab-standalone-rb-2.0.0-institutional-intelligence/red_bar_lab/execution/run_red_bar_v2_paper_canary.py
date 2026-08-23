from __future__ import annotations

from datetime import datetime, time
import os
import signal
from threading import Event
from zoneinfo import ZoneInfo

from red_bar_lab.brokers.zerodha_client import ZerodhaKiteClient
from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution.paper_engine import RedBarPaperExecutionEngine
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_models import (
    PaperCanaryPolicy,
    PaperCanaryPrerequisites,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_repository import (
    SQLiteCanonicalPaperCandidateRepository,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_runtime import (
    PaperCanaryRuntime,
    SystemClock,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_canary_state_store import (
    AtomicJsonPaperCanaryStateStore,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_adapter import (
    ExistingPaperContractSelector,
    ExistingRedBarPaperAdapter,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_execution_ledger import (
    StrictSQLiteCanonicalPaperExecutionRepository,
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


def _market_session_active(now: datetime | None = None) -> bool:
    current = (now or datetime.now(IST)).astimezone(IST)
    return (
        current.weekday() < 5
        and time(9, 15) <= current.time().replace(tzinfo=None) <= time(15, 30)
    )


def build_runtime(settings: RedBarSettings) -> PaperCanaryRuntime:
    """Single composition root for canonical paper-only dependencies."""
    database = RedBarDatabase(settings.database_path)
    database.initialize()
    paper_engine = RedBarPaperExecutionEngine(database, settings)

    api_key = os.getenv("ZERODHA_API_KEY", "").strip()
    access_token = os.getenv("ZERODHA_ACCESS_TOKEN", "").strip()
    if not api_key or not access_token:
        raise RuntimeError("READ_ONLY_MARKET_DATA_CONFIGURATION_MISSING")
    market_data = ZerodhaKiteClient(api_key, access_token)

    execution_repository = StrictSQLiteCanonicalPaperExecutionRepository(
        settings.database_path
    )
    reservation_repository = SQLiteCanonicalReservationRepository(
        settings.database_path
    )
    reservation_service = RedBarV2CanonicalReservationService(
        reservation_repository,
        enabled=settings.red_bar_v2_canonical_reservation_enabled,
        lease_seconds=settings.red_bar_v2_canonical_reservation_lease_seconds,
        maximum_bundle_age_seconds=(
            settings.red_bar_v2_canonical_reservation_max_bundle_age_seconds
        ),
    )
    selector = ExistingPaperContractSelector(
        engine=paper_engine,
        zerodha=market_data,
        underlying_name=settings.default_underlying,
    )
    adapter = ExistingRedBarPaperAdapter(
        engine=paper_engine,
        zerodha=market_data,
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
        paper_execution_enabled=(
            settings.red_bar_v2_canonical_paper_execution_enabled
        ),
        paper_execution_mode=(
            settings.red_bar_v2_canonical_paper_execution_mode
        ),
        worker_enabled=settings.red_bar_v2_paper_canary_worker_enabled,
        market_session_active=_market_session_active(),
    )
    policy = PaperCanaryPolicy(
        poll_seconds=settings.red_bar_v2_paper_canary_poll_seconds,
        max_actions_per_cycle=(
            settings.red_bar_v2_paper_canary_max_actions_per_cycle
        ),
        max_actions_per_day=(
            settings.red_bar_v2_paper_canary_max_actions_per_day
        ),
        max_bundle_age_seconds=(
            settings.red_bar_v2_paper_canary_max_bundle_age_seconds
        ),
        failure_threshold=settings.red_bar_v2_paper_canary_failure_threshold,
        required_probe_cycles=(
            settings.red_bar_v2_paper_canary_required_probe_cycles
        ),
    )
    return PaperCanaryRuntime(
        state_store=AtomicJsonPaperCanaryStateStore(
            settings.paper_canary_state_path
        ),
        candidate_repository=SQLiteCanonicalPaperCandidateRepository(
            settings.database_path
        ),
        recovery_service=recovery_service,
        execution_service=execution_service,
        execution_repository=execution_repository,
        clock=SystemClock(),
        prerequisites=prerequisites,
        policy=policy,
    )


def run_once(settings: RedBarSettings):
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


def main(argv: list[str] | None = None) -> int:
    settings = RedBarSettings.from_env()
    if not settings.red_bar_v2_paper_canary_worker_enabled:
        print("Canonical paper-canary worker is disabled.")
        return 0

    stop_requested = Event()
    install_signal_handlers(stop_requested)
    try:
        runtime = build_runtime(settings)
    except Exception:
        print("Canonical paper-canary configuration is unavailable.")
        return 2

    while not stop_requested.is_set():
        try:
            emit_bounded_status(runtime.run_cycle())
        except Exception:
            print("paper_canary outcome=ENTRY_SUSPENDED reason=WORKER_CYCLE_FAILED")
        stop_requested.wait(settings.red_bar_v2_paper_canary_poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
