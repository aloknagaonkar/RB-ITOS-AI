from __future__ import annotations

from datetime import date, datetime, time
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
from .source import OptionParticipationSnapshotSource

IST = ZoneInfo("Asia/Kolkata")


class MarketTrendResearchService:
    def __init__(self, *, source: OptionParticipationSnapshotSource, repository: MarketTrendResearchRepository, policy: MarketTrendResearchPolicy, calendar: ExchangeSessionCalendar, calculator: DualPcrCalculator | None = None) -> None:
        self.source = source
        self.repository = repository
        self.policy = policy
        self.calendar = calendar
        self.calculator = calculator or DualPcrCalculator(policy)

    @staticmethod
    def _anchor_cells(raw: list[dict[str, object]]) -> tuple[OptionOiCell, ...]:
        return tuple(OptionOiCell(
            instrument_key=str(item["instrument_key"]), option_side=str(item["option_side"]),
            strike=float(item["strike"]), expiry=date.fromisoformat(str(item["expiry"])),
            current_oi=float(item["current_oi"]),
            provider_prev_oi=None if item.get("provider_prev_oi") is None else float(item["provider_prev_oi"]),
            source_timestamp=datetime.fromisoformat(str(item["source_timestamp"])),
        ) for item in raw)

    @staticmethod
    def _anchor_window(raw: dict[str, object]) -> PcrWindowDefinition:
        return PcrWindowDefinition(
            expiry=date.fromisoformat(str(raw["expiry"])), atm=float(raw["atm"]),
            strike_interval=float(raw["strike_interval"]), window_steps=int(raw["window_steps"]),
            strikes=tuple(float(value) for value in raw["strikes"]),
            instrument_keys=tuple(str(value) for value in raw["instrument_keys"]),
        )

    def evaluate(self, *, underlying: str, evaluated_at: datetime) -> DualPcrResearchSnapshot:
        started = monotonic()
        source_started = monotonic()
        chain = self.source.latest(underlying=underlying)
        source_ms = (monotonic() - source_started) * 1000.0
        if chain is None: raise ValueError("SOURCE_UNAVAILABLE")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None: raise ValueError("EVALUATED_AT_NAIVE")
        age = (evaluated_at - chain.source_timestamp).total_seconds()
        if age < 0: raise ValueError("SOURCE_TIMESTAMP_FUTURE")
        trading_date = evaluated_at.astimezone(IST).date()
        sessions = self.policy.sessions_to_expiry(trading_date, chain.expiry, self.calendar)
        steps = self.policy.window_steps(trading_date, chain.expiry, self.calendar)
        calc_started = monotonic()
        current_window = self.calculator.define_window(chain.cells, spot=chain.spot, window_steps=steps)
        anchor_raw = self.repository.load_anchor(underlying=underlying, trading_date=trading_date)
        anchor_cutoff = datetime.combine(trading_date, time(self.policy.anchor_hour, self.policy.anchor_minute), IST)
        if anchor_raw is None and chain.source_timestamp.astimezone(IST) >= anchor_cutoff and age <= self.policy.maximum_source_age_seconds:
            self.repository.create_anchor(underlying=underlying, trading_date=trading_date, anchor_timestamp=chain.source_timestamp, spot=chain.spot, window=current_window, cells=chain.cells)
            anchor_raw = self.repository.load_anchor(underlying=underlying, trading_date=trading_date)
        current_panel = self.calculator.panel(name="Current / Overall PCR", cells=chain.cells, window=current_window, spot=chain.spot, sessions_to_expiry=sessions, source_timestamp=chain.source_timestamp, evaluated_at=evaluated_at)
        morning_panel = None
        if anchor_raw is not None:
            anchor_window = self._anchor_window(anchor_raw["window"])
            anchor_cells = self._anchor_cells(anchor_raw["cells"])
            current_by_key = {cell.instrument_key: cell for cell in chain.cells}
            fixed_current = tuple(current_by_key[key] for key in anchor_window.instrument_keys if key in current_by_key)
            if len(fixed_current) == anchor_window.expected_contract_count and anchor_window.expiry == chain.expiry:
                morning_panel = self.calculator.panel(name="Morning Spot-Level PCR", cells=fixed_current, window=anchor_window, spot=chain.spot, sessions_to_expiry=sessions, source_timestamp=chain.source_timestamp, evaluated_at=evaluated_at, anchor_by_key={cell.instrument_key: cell for cell in anchor_cells}, anchor_timestamp=datetime.fromisoformat(str(anchor_raw["anchor_timestamp"])), anchor_spot=float(anchor_raw["spot"]))
        calculation_ms = (monotonic() - calc_started) * 1000.0
        state = ResearchState.STALE if age > self.policy.maximum_source_age_seconds else ResearchState.READY
        if morning_panel is None and state is ResearchState.READY: state = ResearchState.MORNING_ANCHOR_UNAVAILABLE
        agreement = "UNAVAILABLE"
        if morning_panel and current_panel.aggregate.pcr is not None and morning_panel.aggregate.pcr is not None:
            agreement = "AGREE" if current_panel.aggregate.classification == morning_panel.aggregate.classification else "DIVERGE"
        explanation = (
            f"NIFTY spot was {chain.spot:.2f}.",
            f"The nearest ATM was {current_window.atm:.0f}.",
            f"The expiry policy selected ATM ±{steps}.",
            f"{current_window.expected_contract_count} contracts were complete.",
            f"PCR was {current_panel.aggregate.pcr:.3f}." if current_panel.aggregate.pcr is not None else "PCR was unavailable because CE OI was zero.",
            "Final market direction has not yet been calculated.",
        )
        provisional_latency = ResearchLatencyEvidence(source_ms, 0.0, calculation_ms, 0.0, (monotonic() - started) * 1000.0)
        snapshot = DualPcrResearchSnapshot(DualPcrResearchSnapshot.build_id(underlying=underlying, provider=chain.provider, source_timestamp=chain.source_timestamp), trading_date, underlying, chain.provider, chain.source_timestamp, evaluated_at, current_panel, morning_panel, ResearchDataQuality(state, age, (() if state is ResearchState.READY else (state.value,))), provisional_latency, agreement, explanation)
        persist_started = monotonic()
        self.repository.persist(snapshot)
        persistence_ms = (monotonic() - persist_started) * 1000.0
        end_ms = (monotonic() - started) * 1000.0
        if end_ms > self.policy.hard_deadline_seconds * 1000.0:
            snapshot = DualPcrResearchSnapshot(snapshot.snapshot_id, snapshot.trading_date, snapshot.underlying, snapshot.provider, snapshot.source_timestamp, snapshot.evaluated_at, snapshot.current_panel, snapshot.morning_panel, ResearchDataQuality(ResearchState.TIMEOUT, age, ("DEADLINE_EXCEEDED",)), ResearchLatencyEvidence(source_ms, 0.0, calculation_ms, persistence_ms, end_ms), snapshot.agreement_state, snapshot.explanation)
            self.repository.persist(snapshot)
        return snapshot
