from __future__ import annotations

from datetime import datetime
import sqlite3

from .paper_execution_ledger import StrictSQLiteCanonicalPaperExecutionRepository
from .paper_execution_models import (
    PaperExecutionMode,
    PaperExecutionOutcome,
    PaperExecutionResult,
)
from .paper_execution_repository import (
    PaperExecutionConflictError,
    PaperExecutionCorruptionError,
    PaperExecutionStorageError,
)
from .paper_execution_safety import (
    ReservationFinalizationRequired,
    UncertainPaperAdapterBoundary,
    VerifiedReservationFinalizationService,
)
from .paper_execution_service import CanonicalPaperExecutionService
from .paper_market_data import (
    PaperMarketDataAuthenticationError,
    PaperMarketDataConfigurationError,
    PaperMarketDataCorruptionError,
    PaperMarketDataRateLimitError,
    PaperMarketDataUnavailableError,
)
from .persistence_models import CanonicalPersistenceCorruptionError
from .reservation_evidence_verification import ReservationCorruptionError


class _SelectedContractSelector:
    """Reuse one already-validated selection without repeating market-data work."""

    def __init__(self, contract) -> None:
        self._contract = contract

    def select(self, **kwargs):
        return self._contract


class ReplayGuardedCanonicalPaperService(CanonicalPaperExecutionService):
    """Fail-closed replay preflight and paper-only execution boundary."""

    repository: StrictSQLiteCanonicalPaperExecutionRepository | None

    def execute(
        self,
        *,
        bundle_id: str,
        spot_price: float,
        requested_at: datetime,
        quantity_lots: int = 1,
    ) -> PaperExecutionResult:
        if not self.enabled or self.mode is not PaperExecutionMode.PAPER_CANARY:
            return super().execute(
                bundle_id=bundle_id,
                spot_price=spot_price,
                requested_at=requested_at,
                quantity_lots=quantity_lots,
            )

        if self.repository is None or self.selector is None or self.adapter is None:
            return PaperExecutionResult(PaperExecutionOutcome.STORAGE_UNAVAILABLE, "PREFLIGHT_DEPENDENCY_UNAVAILABLE")
        if self.reservation_service is None:
            return PaperExecutionResult(PaperExecutionOutcome.STORAGE_UNAVAILABLE, "RESERVATION_SERVICE_UNAVAILABLE")

        try:
            canonical = self._read_canonical(bundle_id=bundle_id)
            previous = self.repository.find_by_idempotency_key(
                idempotency_key=canonical.bundle.idempotency_key
            )
            if previous is not None:
                return PaperExecutionResult(
                    PaperExecutionOutcome.IDEMPOTENT_REPLAY,
                    "IDEMPOTENT_REPLAY",
                    command=previous.command,
                    state=previous.state,
                    paper_order_id=previous.paper_order_id,
                )

            contract = self.selector.select(
                option_side=canonical.bundle.option_side.value,
                spot_price=float(spot_price),
                selected_at=requested_at,
            )
            if contract is None:
                return PaperExecutionResult(PaperExecutionOutcome.CONTRACT_UNAVAILABLE, "CONTRACT_UNAVAILABLE")
            if contract.option_side is not canonical.bundle.option_side:
                return PaperExecutionResult(PaperExecutionOutcome.INVALID_REQUEST, "CONTRACT_OPTION_SIDE_MISMATCH")

            guarded = CanonicalPaperExecutionService(
                database_path=self.database_path,
                repository=self.repository,
                reservation_service=VerifiedReservationFinalizationService(self.reservation_service),
                selector=_SelectedContractSelector(contract),
                adapter=UncertainPaperAdapterBoundary(self.adapter),
                enabled=True,
                mode=PaperExecutionMode.PAPER_CANARY.value,
                owner_id=self.owner_id,
            )
            return guarded.execute(
                bundle_id=bundle_id,
                spot_price=spot_price,
                requested_at=requested_at,
                quantity_lots=quantity_lots,
            )
        except LookupError:
            return PaperExecutionResult(PaperExecutionOutcome.BUNDLE_UNAVAILABLE, "BUNDLE_NOT_FOUND")
        except CanonicalPersistenceCorruptionError:
            return PaperExecutionResult(PaperExecutionOutcome.BUNDLE_CORRUPT, "BUNDLE_CORRUPT")
        except ReservationCorruptionError:
            return PaperExecutionResult(PaperExecutionOutcome.RESERVATION_CORRUPT, "RESERVATION_CORRUPT")
        except PaperMarketDataAuthenticationError:
            return PaperExecutionResult(PaperExecutionOutcome.RECOVERY_REQUIRED, "MARKET_DATA_AUTHENTICATION_FAILED")
        except PaperMarketDataConfigurationError:
            return PaperExecutionResult(PaperExecutionOutcome.INVALID_REQUEST, "MARKET_DATA_CONFIGURATION_INVALID")
        except PaperMarketDataRateLimitError:
            return PaperExecutionResult(PaperExecutionOutcome.STORAGE_UNAVAILABLE, "MARKET_DATA_RATE_LIMITED")
        except PaperMarketDataUnavailableError:
            return PaperExecutionResult(PaperExecutionOutcome.STORAGE_UNAVAILABLE, "MARKET_DATA_UNAVAILABLE")
        except PaperMarketDataCorruptionError:
            return PaperExecutionResult(PaperExecutionOutcome.RECOVERY_REQUIRED, "MARKET_DATA_CORRUPT")
        except PaperExecutionCorruptionError:
            return PaperExecutionResult(PaperExecutionOutcome.RECOVERY_REQUIRED, "EXECUTION_LEDGER_CORRUPT")
        except PaperExecutionConflictError:
            return PaperExecutionResult(PaperExecutionOutcome.RECOVERY_REQUIRED, "EXECUTION_LEDGER_CONFLICT")
        except ReservationFinalizationRequired as exc:
            try:
                previous = self.repository.find_by_idempotency_key(
                    idempotency_key=canonical.bundle.idempotency_key
                )
            except (PaperExecutionCorruptionError, PaperExecutionStorageError):
                previous = None
            return PaperExecutionResult(
                PaperExecutionOutcome.RECOVERY_REQUIRED,
                f"RESERVATION_FINALIZATION_REQUIRED:{exc.reason_code}",
                command=previous.command if previous else None,
                state=previous.state if previous else None,
                paper_order_id=previous.paper_order_id if previous else None,
            )
        except (PaperExecutionStorageError, sqlite3.Error, OSError):
            return PaperExecutionResult(PaperExecutionOutcome.STORAGE_UNAVAILABLE, "PREFLIGHT_STORAGE_UNAVAILABLE")
        except (ValueError, TypeError):
            return PaperExecutionResult(PaperExecutionOutcome.INVALID_REQUEST, "INVALID_PREFLIGHT_INPUT")
        except Exception:
            return PaperExecutionResult(PaperExecutionOutcome.RECOVERY_REQUIRED, "UNEXPECTED_PREFLIGHT_FAILURE")
