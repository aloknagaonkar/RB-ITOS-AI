from __future__ import annotations

from datetime import date, datetime, time, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

from .calculator import DualPcrCalculator
from .models import (
    DualPcrResearchSnapshot,
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
    def _anchor_cells(
        raw: list[dict[str, object]],
    ) -> tuple[OptionOiCell, ...]:
        return tuple(
            OptionOiCell(
                instrument_key=str(item["instrument_key"]),
                option_side=str(item["option_side"]),
                strike=float(item["strike"]),
                expiry=date.fromisoformat(str(item["expiry"])),
                current_oi=float(item["current_oi"]),
                provider_prev_oi=(
                    None
                    if item.get("provider_prev_oi") is None
                    else float(item["provider_prev_oi"])
                ),
                source_timestamp=datetime.fromisoformat(
                    str(item["source_timestamp"])
                ),
            )
            for item in raw
        )

    @staticmethod
    def _anchor_window(raw: dict[str, object]) -> PcrWindowDefinition:
        return PcrWindowDefinition(
            expiry=date.fromisoformat(str(raw["expiry"])),
            atm=float(raw["atm"]),
            strike_interval=float(raw["strike_interval"]),
            window_steps=int(raw["window_steps"]),
            strikes=tuple(float(value) for value in raw["strikes"]),
            instrument_keys=tuple(str(value) for value in raw["instrument_keys"]),
        )

    @staticmethod
    def _cells_by_key(
        chain: NormalizedChainSnapshot,
    ) -> dict[str, OptionOiCell]:
        return {cell.instrument_key: cell for cell in chain.cells}

    @staticmethod
    def _selected_cells(
        chain: NormalizedChainSnapshot,
        window: PcrWindowDefinition,
    ) -> tuple[OptionOiCell, ...]:
        by_key = MarketTrendResearchService._cells_by_key(chain)
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
        current_date = current.source_timestamp.astimezone(IST).date()
        previous_date = previous.source_timestamp.astimezone(IST).date()
        if previous_date != current_date:
            return {}, None, None, None, "INSUFFICIENT_HISTORY"
        if previous.expiry != current_window.expiry:
            return (
                {},
                None,
                None,
                ResearchState.WINDOW_TRANSITION,
                "WINDOW_TRANSITION",
            )
        previous_window = self.calculator.define_window(
            previous.cells,
            spot=previous.spot,
            window_steps=steps,
        )
        if (
            previous_window.strike_interval != current_window.strike_interval
            or previous_window.atm != current_window.atm
            or previous_window.instrument_keys != current_window.instrument_keys
        ):
            return (
                {},
                None,
                None,
                ResearchState.WINDOW_TRANSITION,
                "WINDOW_TRANSITION",
            )
        selected = self._selected_cells(previous, previous_window)
        ce_total = sum(
            cell.current_oi for cell in selected if cell.option_side == "CE"
        )
        pe_total = sum(
            cell.current_oi for cell in selected if cell.option_side == "PE"
        )
        previous_pcr = None if ce_total == 0 else pe_total / ce_total
        return (
            {cell.instrument_key: cell for cell in selected},
            previous_pcr,
            previous.source_timestamp,
            None,
            "COMPARABLE",
        )

    def evaluate(
        self,
        *,
        underlying: str,
        evaluated_at: datetime,
    ) -> DualPcrResearchSnapshot:
        started = monotonic()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("EVALUATED_AT_NAIVE")

        if hasattr(self.source, "recent_with_timings"):
            source_result = self.source.recent_with_timings(
                underlying=underlying,
                limit=2,
            )
            recent = source_result.snapshots
            database_read_ms = source_result.database_read_ms
            normalization_ms = source_result.normalization_ms
        else:
            source_started = monotonic()
            recent = self.source.recent(underlying=underlying, limit=2)
            database_read_ms = (monotonic() - source_started) * 1000.0
            normalization_ms = 0.0
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
            transition_state,
            persistence_state,
        ) = self._previous_evidence(
            previous=previous,
            current=chain,
            current_window=current_window,
            steps=steps,
        )

        anchor_raw = self.repository.load_anchor(
            underlying=underlying,
            trading_date=trading_date,
        )
        anchor_cutoff = datetime.combine(
            trading_date,
            time(self.policy.anchor_hour, self.policy.anchor_minute),
            IST,
        )
        anchor_on_time_deadline = anchor_cutoff + timedelta(
            seconds=self.policy.anchor_on_time_tolerance_seconds
        )
        anchor_deadline = anchor_cutoff + timedelta(
            seconds=self.policy.maximum_anchor_delay_seconds
        )
        source_ist = chain.source_timestamp.astimezone(IST)
        if (
            anchor_raw is None
            and anchor_cutoff <= source_ist <= anchor_deadline
            and age <= self.policy.maximum_source_age_seconds
        ):
            selected_for_anchor = self._selected_cells(chain, current_window)
            self.repository.create_anchor(
                underlying=underlying,
                trading_date=trading_date,
                anchor_timestamp=chain.source_timestamp,
                spot=chain.spot,
                window=current_window,
                cells=selected_for_anchor,
            )
            anchor_raw = self.repository.load_anchor(
                underlying=underlying,
                trading_date=trading_date,
            )

        current_panel = self.calculator.panel(
            name="Current / Overall PCR",
            cells=chain.cells,
            window=current_window,
            spot=chain.spot,
            sessions_to_expiry=sessions,
            source_timestamp=chain.source_timestamp,
            evaluated_at=evaluated_at,
            previous_by_key=previous_by_key,
            previous_pcr=previous_pcr,
            previous_timestamp=previous_timestamp,
            panel_state=transition_state,
            persistence_state=persistence_state,
        )

        morning_panel = None
        if anchor_raw is not None:
            anchor_window = self._anchor_window(anchor_raw["window"])
            anchor_cells = self._anchor_cells(anchor_raw["cells"])
            if anchor_window.expiry != chain.expiry:
                raise ValueError("EXPIRY_MISMATCH")
            fixed_current = self._selected_cells(chain, anchor_window)
            previous_fixed: dict[str, OptionOiCell] = {}
            previous_fixed_pcr = None
            previous_fixed_timestamp = None
            same_session_previous = (
                previous is not None
                and previous.source_timestamp.astimezone(IST).date()
                == chain.source_timestamp.astimezone(IST).date()
            )
            if (
                same_session_previous
                and previous is not None
                and previous.expiry == anchor_window.expiry
            ):
                previous_map = self._cells_by_key(previous)
                if all(key in previous_map for key in anchor_window.instrument_keys):
                    previous_fixed = {
                        key: previous_map[key]
                        for key in anchor_window.instrument_keys
                    }
                    previous_ce = sum(
                        cell.current_oi
                        for cell in previous_fixed.values()
                        if cell.option_side == "CE"
                    )
                    previous_pe = sum(
                        cell.current_oi
                        for cell in previous_fixed.values()
                        if cell.option_side == "PE"
                    )
                    previous_fixed_pcr = (
                        None if previous_ce == 0 else previous_pe / previous_ce
                    )
                    previous_fixed_timestamp = previous.source_timestamp
            anchor_timestamp = datetime.fromisoformat(
                str(anchor_raw["anchor_timestamp"])
            )
            anchor_status = (
                "ON_TIME_ANCHOR"
                if anchor_cutoff
                <= anchor_timestamp.astimezone(IST)
                <= anchor_on_time_deadline
                else "DELAYED_ANCHOR"
            )
            morning_panel = self.calculator.panel(
                name="Morning Spot-Level PCR",
                cells=fixed_current,
                window=anchor_window,
                spot=chain.spot,
                sessions_to_expiry=sessions,
                source_timestamp=chain.source_timestamp,
                evaluated_at=evaluated_at,
                previous_by_key=previous_fixed,
                previous_pcr=previous_fixed_pcr,
                previous_timestamp=previous_fixed_timestamp,
                persistence_state=(
                    "COMPARABLE"
                    if previous_fixed_timestamp is not None
                    else "INSUFFICIENT_HISTORY"
                ),
                anchor_by_key={
                    cell.instrument_key: cell for cell in anchor_cells
                },
                anchor_timestamp=anchor_timestamp,
                anchor_status=anchor_status,
                anchor_spot=float(anchor_raw["spot"]),
            )

        calculation_ms = (monotonic() - calculation_started) * 1000.0
        state = (
            ResearchState.STALE
            if age > self.policy.maximum_source_age_seconds
            else ResearchState.READY
        )
        if transition_state is ResearchState.WINDOW_TRANSITION:
            state = ResearchState.WINDOW_TRANSITION
        elif morning_panel is None and state is ResearchState.READY:
            state = ResearchState.MORNING_ANCHOR_UNAVAILABLE
        if (
            (monotonic() - started) * 1000.0
            > self.policy.hard_deadline_seconds * 1000.0
        ):
            state = ResearchState.TIMEOUT

        agreement = "UNAVAILABLE"
        if (
            morning_panel is not None
            and current_panel.aggregate.pcr is not None
            and morning_panel.aggregate.pcr is not None
        ):
            agreement = (
                "AGREE"
                if current_panel.aggregate.classification
                == morning_panel.aggregate.classification
                else "DIVERGE"
            )

        explanation = (
            f"NIFTY spot was {chain.spot:.2f}.",
            f"The nearest ATM was {current_window.atm:.0f}.",
            f"The expiry policy selected ATM ±{steps} using {calendar_source}.",
            f"{current_window.expected_contract_count} contracts were complete.",
            (
                f"PCR was {current_panel.aggregate.pcr:.3f} and classified as "
                f"{current_panel.aggregate.classification.value.lower()}."
                if current_panel.aggregate.pcr is not None
                else "PCR was unavailable because CE OI was zero."
            ),
            "Final market direction has not yet been calculated.",
        )
        reason_codes = (
            ("DEADLINE_EXCEEDED",)
            if state is ResearchState.TIMEOUT
            else ()
            if state is ResearchState.READY
            else (state.value,)
        )
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
            quality=ResearchDataQuality(state, age, reason_codes),
            latency=ResearchLatencyEvidence(
                database_read_ms=database_read_ms,
                normalization_ms=normalization_ms,
                calculation_ms=calculation_ms,
                persistence_ms=0.0,
                end_to_end_ms=(monotonic() - started) * 1000.0,
            ),
            agreement_state=agreement,
            explanation=explanation,
            calendar_source=calendar_source,
        )
        return self.repository.persist_once(
            snapshot,
            evaluation_started=started,
            database_read_ms=database_read_ms,
            normalization_ms=normalization_ms,
            calculation_ms=calculation_ms,
            hard_deadline_ms=self.policy.hard_deadline_seconds * 1000.0,
        )
