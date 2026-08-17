from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import inf
from typing import Iterable, Protocol, Sequence

RESEARCH_ONLY = "RESEARCH_ONLY"


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    display_name: str
    version: str
    adapter_id: str
    description: str
    research_scope: str = RESEARCH_ONLY
    enabled: bool = True

    @property
    def identity(self) -> str:
        return f"{self.strategy_id}@{self.version}"


@dataclass(frozen=True)
class NormalizedReplayRow:
    trading_date: date
    decision: str
    execution: str
    outcome_result: str
    return_pct: float | None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    data_fidelity: str = "UNKNOWN"


@dataclass(frozen=True)
class DayValidationResult:
    trading_date: date
    ready: bool
    fidelity: str
    readiness_reason: str
    rows: tuple[NormalizedReplayRow, ...] = ()
    coverage_basis: str = "UNKNOWN"
    contract_coverage_pct: float = 0.0
    candle_coverage_pct: float = 0.0
    oi_coverage_pct: float = 0.0


@dataclass(frozen=True)
class ValidationMetrics:
    total_days: int
    ready_days: int
    blocked_days: int
    readiness_pct: float
    trade_count: int
    winners: int
    losers: int
    breakeven: int
    win_rate_pct: float
    net_return_pct: float
    expectancy_pct: float
    profit_factor: float | None
    maximum_drawdown_pct: float
    average_mfe_pct: float | None
    average_mae_pct: float | None
    promotion_eligible: bool
    promotion_reasons: tuple[str, ...]


@dataclass(frozen=True)
class StrategyValidationReport:
    strategy: StrategyDefinition
    requested_dates: tuple[date, ...]
    days: tuple[DayValidationResult, ...]
    metrics: ValidationMetrics
    research_scope: str = RESEARCH_ONLY


class HistoricalStrategyAdapter(Protocol):
    adapter_id: str
    research_only: bool

    def run_day(self, instrument_key: str, trading_date: date) -> DayValidationResult:
        ...


class StrategyRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, StrategyDefinition] = {}

    def register(self, definition: StrategyDefinition) -> None:
        if definition.research_scope != RESEARCH_ONLY:
            raise ValueError("Historical strategies must be RESEARCH_ONLY.")
        if not definition.strategy_id or not definition.version:
            raise ValueError("Strategy id and version are required.")
        if definition.identity in self._definitions:
            raise ValueError(f"Duplicate strategy version: {definition.identity}")
        self._definitions[definition.identity] = definition

    def get(self, strategy_id: str, version: str) -> StrategyDefinition:
        key = f"{strategy_id}@{version}"
        if key not in self._definitions:
            raise KeyError(f"Unknown historical strategy: {key}")
        return self._definitions[key]

    def definitions(self) -> tuple[StrategyDefinition, ...]:
        return tuple(sorted(self._definitions.values(), key=lambda x: (x.display_name, x.version)))

    def versions(self, strategy_id: str) -> tuple[str, ...]:
        return tuple(sorted(x.version for x in self._definitions.values() if x.strategy_id == strategy_id))


def default_strategy_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(StrategyDefinition(
        strategy_id="DRI",
        display_name="Directional Regime Intelligence",
        version="1.0.0",
        adapter_id="DRI_REPLAY",
        description="Existing point-in-time DRI historical decision replay.",
    ))
    registry.register(StrategyDefinition(
        strategy_id="RED_BAR",
        display_name="Reference-Level Red Bar",
        version="1.0.0",
        adapter_id="RED_BAR_REPLAY",
        description="Existing reference-level Red Bar historical decision replay.",
    ))
    return registry


def select_validation_dates(
    available_dates: Iterable[date],
    *,
    window: str,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> tuple[date, ...]:
    dates = tuple(sorted(set(available_dates)))
    normalized = str(window or '').upper()
    if normalized == '10_DAY':
        return dates[-10:]
    if normalized == '20_DAY':
        return dates[-20:]
    if normalized != 'CUSTOM':
        raise ValueError(f'Unsupported validation window: {window}')
    if custom_start is None or custom_end is None:
        raise ValueError('Custom start and end dates are required.')
    if custom_start > custom_end:
        raise ValueError('Custom start cannot be after custom end.')
    return tuple(x for x in dates if custom_start <= x <= custom_end)


def _num(value, default=0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def calculate_metrics(
    days: Sequence[DayValidationResult],
    *,
    minimum_ready_days: int = 10,
    minimum_readiness_pct: float = 80.0,
    minimum_trades: int = 10,
    minimum_win_rate_pct: float = 50.0,
    maximum_allowed_drawdown_pct: float = 20.0,
) -> ValidationMetrics:
    ready_days = [d for d in days if d.ready]
    rows = [r for d in ready_days for r in d.rows if r.return_pct is not None]
    returns = [_num(r.return_pct) for r in rows]
    winners = sum(v > 0 for v in returns)
    losers = sum(v < 0 for v in returns)
    breakeven = sum(v == 0 for v in returns)
    gross_profit = sum(v for v in returns if v > 0)
    gross_loss = abs(sum(v for v in returns if v < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (inf if gross_profit > 0 else None)

    cumulative = 0.0
    peak = 0.0
    maximum_drawdown = 0.0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)

    total_days = len(days)
    ready_count = len(ready_days)
    readiness_pct = ready_count / total_days * 100.0 if total_days else 0.0
    trade_count = len(returns)
    win_rate = winners / trade_count * 100.0 if trade_count else 0.0
    expectancy = sum(returns) / trade_count if trade_count else 0.0
    mfe = [_num(r.mfe_pct) for r in rows if r.mfe_pct is not None]
    mae = [_num(r.mae_pct) for r in rows if r.mae_pct is not None]

    reasons: list[str] = []
    if ready_count < minimum_ready_days:
        reasons.append(f'READY_DAYS_BELOW_MINIMUM:{ready_count}<{minimum_ready_days}')
    if readiness_pct < minimum_readiness_pct:
        reasons.append(f'READINESS_BELOW_MINIMUM:{readiness_pct:.1f}<{minimum_readiness_pct:.1f}')
    if trade_count < minimum_trades:
        reasons.append(f'TRADES_BELOW_MINIMUM:{trade_count}<{minimum_trades}')
    if win_rate < minimum_win_rate_pct:
        reasons.append(f'WIN_RATE_BELOW_MINIMUM:{win_rate:.1f}<{minimum_win_rate_pct:.1f}')
    if maximum_drawdown > maximum_allowed_drawdown_pct:
        reasons.append(f'DRAWDOWN_ABOVE_MAXIMUM:{maximum_drawdown:.1f}>{maximum_allowed_drawdown_pct:.1f}')

    return ValidationMetrics(
        total_days=total_days,
        ready_days=ready_count,
        blocked_days=total_days - ready_count,
        readiness_pct=round(readiness_pct, 4),
        trade_count=trade_count,
        winners=winners,
        losers=losers,
        breakeven=breakeven,
        win_rate_pct=round(win_rate, 4),
        net_return_pct=round(sum(returns), 4),
        expectancy_pct=round(expectancy, 4),
        profit_factor=round(profit_factor, 4) if profit_factor not in (None, inf) else profit_factor,
        maximum_drawdown_pct=round(maximum_drawdown, 4),
        average_mfe_pct=round(sum(mfe) / len(mfe), 4) if mfe else None,
        average_mae_pct=round(sum(mae) / len(mae), 4) if mae else None,
        promotion_eligible=not reasons,
        promotion_reasons=tuple(reasons or ['ALL_PROMOTION_GATES_PASS']),
    )


class HistoricalStrategyValidationEngine:
    """Research-only orchestration over registered replay adapters."""

    def __init__(self, registry: StrategyRegistry, adapters: Iterable[HistoricalStrategyAdapter]) -> None:
        self.registry = registry
        self.adapters = {adapter.adapter_id: adapter for adapter in adapters}

    def validate(
        self,
        *,
        strategy_id: str,
        version: str,
        instrument_key: str,
        trading_dates: Sequence[date],
    ) -> StrategyValidationReport:
        definition = self.registry.get(strategy_id, version)
        adapter = self.adapters.get(definition.adapter_id)
        if adapter is None:
            raise KeyError(f'No adapter registered for {definition.adapter_id}')
        if not getattr(adapter, 'research_only', False):
            raise RuntimeError('Historical validation adapter is not research-only.')

        results: list[DayValidationResult] = []
        for trading_date in trading_dates:
            try:
                results.append(adapter.run_day(instrument_key, trading_date))
            except Exception as exc:
                results.append(DayValidationResult(
                    trading_date=trading_date,
                    ready=False,
                    fidelity='BLOCKED',
                    readiness_reason=f'{type(exc).__name__}:{exc}',
                ))
        day_tuple = tuple(results)
        return StrategyValidationReport(
            strategy=definition,
            requested_dates=tuple(trading_dates),
            days=day_tuple,
            metrics=calculate_metrics(day_tuple),
        )

    def compare(
        self,
        *,
        strategies: Sequence[tuple[str, str]],
        instrument_key: str,
        trading_dates: Sequence[date],
    ) -> tuple[StrategyValidationReport, ...]:
        return tuple(self.validate(
            strategy_id=strategy_id,
            version=version,
            instrument_key=instrument_key,
            trading_dates=trading_dates,
        ) for strategy_id, version in strategies)
