from __future__ import annotations

from datetime import date, datetime
from time import monotonic
from zoneinfo import ZoneInfo

from .calculator import DualPcrCalculator
from .models import (
    DualPcrResearchSnapshot,
    MorningLifecycleState,
    MorningReference,
    OpeningOiBaseline,
    OptionOiCell,
    PcrWindowDefinition,
    ResearchDataQuality,
    ResearchLatencyEvidence,
    ResearchState,
)
from .policy import ExchangeSessionCalendar, MarketTrendResearchPolicy
from .repository import MarketTrendResearchRepository
from .source import NormalizedChainSnapshot, OptionParticipationSnapshotSource

IST = ZoneInfo("Asia/Kolkata")


class MarketTrendResearchService:
    def __init__(
        self,
        *,
        source: OptionParticipationSnapshotSource,
        repository: MarketTrendResearchRepository,
        policy: MarketTrendResearchPolicy,
        calendar: ExchangeSessionCalendar,
        calculator: DualPcrCalculator | None = None,
    ) -> None:
        self.source = source
        self.repository = repository
        self.policy = policy
        self.calendar = calendar
        self.calculator = calculator or DualPcrCalculator(policy)

    @staticmethod
    def _aware(value: object) -> datetime:
        result = datetime.fromisoformat(str(value))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("PERSISTED_TIMESTAMP_NAIVE")
        return result

    @classmethod
    def _cell(cls, raw: dict[str, object]) -> OptionOiCell:
        return OptionOiCell(
            instrument_key=str(raw["instrument_key"]),
            option_side=str(raw["option_side"]),
            strike=float(raw["strike"]),
            expiry=date.fromisoformat(str(raw["expiry"])),
            current_oi=float(raw["current_oi"]),
            provider_prev_oi=(
                None
                if raw.get("provider_prev_oi") is None
                else float(raw["provider_prev_oi"])
            ),
            source_timestamp=cls._aware(raw["source_timestamp"]),
        )

    @classmethod
    def _reference(cls, raw: dict[str, object]) -> MorningReference:
        return MorningReference(
            trading_date=date.fromisoformat(str(raw["trading_date"])),
            underlying=str(raw["underlying"]),
            reference_spot=float(raw["reference_spot"]),
            reference_timestamp=cls._aware(raw["reference_timestamp"]),
            expiry=date.fromisoformat(str(raw["expiry"])),
            strike_interval=float(raw["strike_interval"]),
            fixed_atm=float(raw["fixed_atm"]),
            window_steps=int(raw["window_steps"]),
            fixed_strikes=tuple(float(value) for value in raw["fixed_strikes"]),
            source=str(raw["source"]),
            source_age_seconds=float(raw["source_age_seconds"]),
            status=str(raw["status"]),
        )

    @classmethod
    def _baseline(cls, raw: dict[str, object]) -> OpeningOiBaseline:
        return OpeningOiBaseline(
            trading_date=date.fromisoformat(str(raw["trading_date"])),
            underlying=str(raw["underlying"]),
            baseline_timestamp=cls._aware(raw["baseline_timestamp"]),
            expiry=date.fromisoformat(str(raw["expiry"])),
            cells=tuple(cls._cell(item) for item in raw["cells"]),
            status=str(raw["status"]),
        )

    @staticmethod
    def _by_key(chain: NormalizedChainSnapshot) -> dict[str, OptionOiCell]:
        return {cell.instrument_key: cell for cell in chain.cells}

    @staticmethod
    def _selected(
        chain: NormalizedChainSnapshot,
        window: PcrWindowDefinition,
    ) -> tuple[OptionOiCell, ...]:
        by_key = MarketTrendResearchService._by_key(chain)
        selected = tuple(
            by_key[key] for key in window.instrument_keys if key in by_key
        )
        if len(selected) != window.expected_contract_count:
            raise ValueError("PARTIAL_CONTRACT_WINDOW")
        return selected

    def _previous_evidence(
        self,
        *,
        previous: NormalizedChainSnapshot | None,
        current: NormalizedChainSnapshot,
        current_window: PcrWindowDefinition,
        steps: int,
    ) -> tuple[
        dict[str, OptionOiCell],
        float | None,
        datetime | None,
        ResearchState | None,
        str,
    ]:
        if previous is None:
            return {}, None, None, None, "INSUFFICIENT_HISTORY"
        if previous.source_timestamp >= current.source_timestamp:
            return {}, None, None, None, "PREVIOUS_TIMESTAMP_NOT_EARLIER"
        if (
            previous.source_timestamp.astimezone(IST).date()
            != current.source_timestamp.astimezone(IST).date()
        ):
            return {}, None, None, None, "INSUFFICIENT_HISTORY"
        if previous.expiry != current_window.expiry:
            return (
                {},
                None,
                None,
                ResearchState.WINDOW_TRANSITION,
                "NOT_COMPARABLE_WINDOW_CHANGED",
            )
        previous_window = self.calculator.define_window(
            previous.cells,
            spot=previous.spot,
            window_steps=steps,
        )
        if (
            previous_window.atm != current_window.atm
            or previous_window.strike_interval != current_window.strike_interval
            or previous_window.instrument_keys != current_window.instrument_keys
        ):
            return (
                {},
                None,
                None,
                ResearchState.WINDOW_TRANSITION,
                "NOT_COMPARABLE_WINDOW_CHANGED",
            )
        selected = self._selected(previous, previous_window)
        ce_total = sum(
            cell.current_oi for cell in selected if cell.option_side == "CE"
        )
        pe_total = sum(
            cell.current_oi for cell in selected if cell.option_side == "PE"
        )
        return (
            {cell.instrument_key: cell for cell in selected},
            None if ce_total == 0 else pe_total / ce_total,
            previous.source_timestamp,
            None,
            "COMPARABLE",
        )

    def _ensure_reference(
        self,
        *,
        chain: NormalizedChainSnapshot,
        trading_date: date,
        steps: int,
        age: float,
    ) -> MorningReference | None:
        raw = self.repository.load_reference(
            underlying=chain.underlying,
            trading_date=trading_date,
        )
        if raw is not None:
            return self._reference(raw)
        source_time = chain.source_timestamp.astimezone(IST).time().replace(tzinfo=None)
        if not self.policy.reference_start <= source_time <= self.policy.reference_cutoff:
            return None
        if age > self.policy.maximum_source_age_seconds:
            return None
        window = self.calculator.define_window(
            chain.cells,
            spot=chain.spot,
            window_steps=steps,
        )
        reference = MorningReference(
            trading_date=trading_date,
            underlying=chain.underlying,
            reference_spot=chain.spot,
            reference_timestamp=chain.source_timestamp,
            expiry=chain.expiry,
            strike_interval=window.strike_interval,
            fixed_atm=window.atm,
            window_steps=steps,
            fixed_strikes=window.strikes,
            source=chain.provider,
            source_age_seconds=age,
            status="REFERENCE_FIXED",
        )
        self.repository.create_reference(reference)
        stored = self.repository.load_reference(
            underlying=chain.underlying,
            trading_date=trading_date,
        )
        return None if stored is None else self._reference(stored)

    def _fixed_window(
        self,
        *,
        chain: NormalizedChainSnapshot,
        reference: MorningReference,
    ) -> PcrWindowDefinition:
        if reference.expiry != chain.expiry:
            raise ValueError("EXPIRY_MISMATCH")
        return self.calculator.window_for_fixed_strikes(
            chain.cells,
            expiry=reference.expiry,
            atm=reference.fixed_atm,
            strike_interval=reference.strike_interval,
            window_steps=reference.window_steps,
            strikes=reference.fixed_strikes,
        )

    def _ensure_baseline(
        self,
        *,
        chain: NormalizedChainSnapshot,
        trading_date: date,
        reference: MorningReference,
        age: float,
    ) -> OpeningOiBaseline | None:
        raw = self.repository.load_oi_baseline(
            underlying=chain.underlying,
            trading_date=trading_date,
        )
        if raw is not None:
            return self._baseline(raw)
        source_time = chain.source_timestamp.astimezone(IST).time().replace(tzinfo=None)
        if (
            source_time < self.policy.oi_baseline_start
            or age > self.policy.maximum_source_age_seconds
        ):
            return None
        window = self._fixed_window(chain=chain, reference=reference)
        cells = self._selected(chain, window)
        baseline = OpeningOiBaseline(
            trading_date=trading_date,
            underlying=chain.underlying,
            baseline_timestamp=chain.source_timestamp,
            expiry=chain.expiry,
            cells=cells,
            status="OI_BASELINE_FIXED",
        )
        self.repository.create_oi_baseline(baseline)
        stored = self.repository.load_oi_baseline(
            underlying=chain.underlying,
            trading_date=trading_date,
        )
        return None if stored is None else self._baseline(stored)

    def evaluate(
        self,
        *,
        underlying: str,
        evaluated_at: datetime,
        runtime_mode: str = "ONE_SHOT",
        automatic_refresh: str = "NOT_CONNECTED",
        dropped_obsolete_tasks: int = 0,
        consecutive_failures: int = 0,
    ) -> DualPcrResearchSnapshot:
        started = monotonic()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("EVALUATED_AT_NAIVE")
        source_result = self.source.recent_with_timings(
            underlying=underlying,
            limit=2,
        )
        recent = source_result.snapshots
        if not recent:
            raise ValueError("SOURCE_UNAVAILABLE")
        chain = recent[0]
        previous = recent[1] if len(recent) > 1 else None
        age = (evaluated_at - chain.source_timestamp).total_seconds()
        if age < 0:
            raise ValueError("SOURCE_TIMESTAMP_FUTURE")
        trading_date = chain.source_timestamp.astimezone(IST).date()
        calendar_source = self.policy.calendar_source(self.calendar)
        sessions = self.policy.sessions_to_expiry(
            trading_date,
            chain.expiry,
            self.calendar,
        )
        steps = self.policy.window_steps(
            trading_date,
            chain.expiry,
            self.calendar,
        )

        calculation_started = monotonic()
        current_window = self.calculator.define_window(
            chain.cells,
            spot=chain.spot,
            window_steps=steps,
        )
        (
            previous_by_key,
            previous_pcr,
            previous_timestamp,
            transition,
            persistence,
        ) = self._previous_evidence(
            previous=previous,
            current=chain,
            current_window=current_window,
            steps=steps,
        )
        current_panel = self.calculator.panel(
            name="Current/Overall PCR",
            cells=chain.cells,
            window=current_window,
            spot=chain.spot,
            sessions_to_expiry=sessions,
            source_timestamp=chain.source_timestamp,
            evaluated_at=evaluated_at,
            previous_by_key=previous_by_key,
            previous_pcr=previous_pcr,
            previous_timestamp=previous_timestamp,
            panel_state=transition,
            persistence_state=persistence,
            data_status=(
                "Not comparable — ATM/window changed"
                if transition is ResearchState.WINDOW_TRANSITION
                else "Available"
            ),
        )

        reference = self._ensure_reference(
            chain=chain,
            trading_date=trading_date,
            steps=steps,
            age=age,
        )
        baseline = None
        morning_panel = None
        lifecycle = MorningLifecycleState.WAITING_FOR_REFERENCE
        if reference is not None:
            lifecycle = MorningLifecycleState.REFERENCE_FIXED
            baseline = self._ensure_baseline(
                chain=chain,
                trading_date=trading_date,
                reference=reference,
                age=age,
            )
            if baseline is None:
                lifecycle = MorningLifecycleState.WAITING_FOR_OI_BASELINE
            else:
                fixed_window = self._fixed_window(
                    chain=chain,
                    reference=reference,
                )
                opening_by_key = {
                    cell.instrument_key: cell for cell in baseline.cells
                }
                if set(fixed_window.instrument_keys) != set(opening_by_key):
                    raise ValueError("MORNING_BASELINE_IDENTITY_MISMATCH")
                morning_panel = self.calculator.panel(
                    name="Morning Fixed-Level PCR",
                    cells=chain.cells,
                    window=fixed_window,
                    spot=chain.spot,
                    sessions_to_expiry=sessions,
                    source_timestamp=chain.source_timestamp,
                    evaluated_at=evaluated_at,
                    opening_by_key=opening_by_key,
                    persistence_state="OPENING_BASELINE",
                    reference_timestamp=reference.reference_timestamp,
                    reference_status=reference.status,
                    reference_spot=reference.reference_spot,
                    baseline_timestamp=baseline.baseline_timestamp,
                    baseline_status=baseline.status,
                    data_status="Available",
                )
                lifecycle = MorningLifecycleState.MORNING_RESEARCH_READY

        state = (
            ResearchState.STALE
            if age > self.policy.maximum_source_age_seconds
            else ResearchState.READY
        )
        if transition is ResearchState.WINDOW_TRANSITION and state is ResearchState.READY:
            state = ResearchState.WINDOW_TRANSITION
        if reference is None and state is ResearchState.READY:
            state = ResearchState.MORNING_REFERENCE_UNAVAILABLE
        elif reference is not None and baseline is None and state is ResearchState.READY:
            state = ResearchState.MORNING_OI_BASELINE_UNAVAILABLE
        if (
            (monotonic() - started) * 1000.0
            > self.policy.hard_deadline_seconds * 1000.0
        ):
            state = ResearchState.TIMEOUT

        agreement = "UNAVAILABLE"
        if (
            morning_panel
            and morning_panel.aggregate.pcr is not None
            and current_panel.aggregate.pcr is not None
        ):
            agreement = (
                "AGREE"
                if morning_panel.aggregate.classification
                == current_panel.aggregate.classification
                else "DIVERGE"
            )
        calculation_ms = (monotonic() - calculation_started) * 1000.0
        reasons = () if state is ResearchState.READY else (state.value,)
        snapshot = DualPcrResearchSnapshot(
            snapshot_id=DualPcrResearchSnapshot.build_id(
                underlying=underlying,
                provider=chain.provider,
                source_timestamp=chain.source_timestamp,
            ),
            trading_date=trading_date,
            underlying=underlying,
            provider=chain.provider,
            source_timestamp=chain.source_timestamp,
            evaluated_at=evaluated_at,
            current_panel=current_panel,
            morning_panel=morning_panel,
            quality=ResearchDataQuality(state, age, reasons),
            latency=ResearchLatencyEvidence(
                database_read_ms=source_result.database_read_ms,
                normalization_ms=(
                    source_result.normalization_ms + chain.normalization_ms
                ),
                calculation_ms=calculation_ms,
                persistence_ms=0.0,
                end_to_end_ms=(monotonic() - started) * 1000.0,
                provider_request_ms=chain.provider_request_ms,
                dropped_obsolete_tasks=dropped_obsolete_tasks,
                consecutive_failures=consecutive_failures,
            ),
            agreement_state=agreement,
            explanation=(
                f"Morning lifecycle: {lifecycle.value}.",
                (
                    f"Current NIFTY spot was {chain.spot:.2f}; "
                    f"current ATM was {current_window.atm:.0f}."
                ),
                f"The verified expiry policy selected ATM ±{steps}.",
                "Final market direction has not yet been calculated.",
            ),
            calendar_source=calendar_source,
            lifecycle_state=lifecycle,
            morning_reference=reference,
            opening_oi_baseline=baseline,
            runtime_mode=runtime_mode,
            automatic_refresh=automatic_refresh,
        )
        return self.repository.persist_once(
            snapshot,
            evaluation_started=started,
            database_read_ms=source_result.database_read_ms,
            normalization_ms=(
                source_result.normalization_ms + chain.normalization_ms
            ),
            calculation_ms=calculation_ms,
            hard_deadline_ms=self.policy.hard_deadline_seconds * 1000.0,
            provider_request_ms=chain.provider_request_ms,
            dropped_obsolete_tasks=dropped_obsolete_tasks,
            consecutive_failures=consecutive_failures,
        )
