from __future__ import annotations

from datetime import date
from typing import Any

from red_bar_lab.services.historical_strategy_validation import DayValidationResult, NormalizedReplayRow


def _number(value: Any) -> float | None:
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_row(trading_date: date, row: Any) -> NormalizedReplayRow:
    raw = row.as_dict() if hasattr(row, 'as_dict') else (dict(row) if isinstance(row, dict) else vars(row))
    option_return = _number(raw.get('option_return_pct'))
    trailing_return = _number(raw.get('trailing_return_pct'))
    return NormalizedReplayRow(
        trading_date=trading_date,
        decision=str(raw.get('decision') or 'UNKNOWN'),
        execution=str(raw.get('execution') or 'UNKNOWN'),
        outcome_result=str(raw.get('outcome_result') or raw.get('verdict') or 'UNKNOWN'),
        return_pct=trailing_return if trailing_return is not None else option_return,
        mfe_pct=_number(raw.get('mfe_pct') or raw.get('maximum_favourable_excursion_pct')),
        mae_pct=_number(raw.get('mae_pct') or raw.get('maximum_adverse_excursion_pct')),
        data_fidelity=str(raw.get('data_fidelity') or 'UNKNOWN'),
    )


def _normalize_result(
    trading_date: date,
    result: Any,
    audit: Any | None = None,
) -> DayValidationResult:
    rows = tuple(_normalize_row(trading_date, row) for row in tuple(getattr(result, 'rows', ()) or ()))
    ready = bool(getattr(result, 'replay_ready', True))
    fidelity = str(getattr(result, 'data_fidelity', None) or getattr(result, 'fidelity', None) or 'UNKNOWN')
    reason = str(getattr(result, 'replay_fidelity_reason', None) or ('READY' if ready else fidelity))
    return DayValidationResult(
        trading_date=trading_date,
        ready=ready,
        fidelity=fidelity,
        readiness_reason=reason,
        rows=rows,
        coverage_basis=str(getattr(result, 'coverage_basis', 'FULL_CHAIN')),
        contract_coverage_pct=float(getattr(result, 'option_contract_coverage_pct', 0.0) or 0.0),
        candle_coverage_pct=float(getattr(result, 'option_candle_coverage_pct', 0.0) or 0.0),
        oi_coverage_pct=float(getattr(result, 'option_oi_coverage_pct', 0.0) or 0.0),
        global_replay_ready=bool(
            getattr(audit, 'global_replay_ready', ready)
        ),
        strategy_relevant_status=str(
            getattr(audit, 'relevant_status', 'NOT_EVALUATED')
        ),
        strategy_relevant_reason=str(
            getattr(audit, 'relevant_reason', '')
        ),
        relevant_contracts=int(
            getattr(audit, 'relevant_contracts', 0) or 0
        ),
        relevant_ce_contracts=int(
            getattr(audit, 'relevant_ce_contracts', 0) or 0
        ),
        relevant_pe_contracts=int(
            getattr(audit, 'relevant_pe_contracts', 0) or 0
        ),
        relevant_complete_contracts=int(
            getattr(audit, 'relevant_complete_contracts', 0) or 0
        ),
        relevant_candle_coverage_pct=float(
            getattr(audit, 'relevant_candle_coverage_pct', 0.0) or 0.0
        ),
        relevant_oi_coverage_pct=float(
            getattr(audit, 'relevant_oi_coverage_pct', 0.0) or 0.0
        ),
        missing_relevant_contracts=int(
            getattr(audit, 'missing_relevant_contracts', 0) or 0
        ),
    )


class _ResearchOnlyHistoricalStrategyAdapter:
    research_only = True

    def __init__(self, replay_service, readiness_service=None) -> None:
        self.replay_service = replay_service
        self.readiness_service = readiness_service

    def run_day(self, instrument_key: str, trading_date: date) -> DayValidationResult:
        audit = (
            self.readiness_service.inspect_day(instrument_key, trading_date)
            if self.readiness_service is not None
            else None
        )
        if audit is not None and not audit.effective_ready:
            return DayValidationResult(
                trading_date=trading_date,
                ready=False,
                fidelity=audit.global_fidelity,
                readiness_reason=audit.global_reason,
                coverage_basis=audit.coverage_basis,
                global_replay_ready=False,
                strategy_relevant_status=audit.relevant_status,
                strategy_relevant_reason=audit.relevant_reason,
                relevant_contracts=audit.relevant_contracts,
                relevant_ce_contracts=audit.relevant_ce_contracts,
                relevant_pe_contracts=audit.relevant_pe_contracts,
                relevant_complete_contracts=audit.relevant_complete_contracts,
                relevant_candle_coverage_pct=audit.relevant_candle_coverage_pct,
                relevant_oi_coverage_pct=audit.relevant_oi_coverage_pct,
                missing_relevant_contracts=audit.missing_relevant_contracts,
            )
        result = self.replay_service.run_day(instrument_key, trading_date)
        return _normalize_result(trading_date, result, audit)


class DRIHistoricalStrategyAdapter(_ResearchOnlyHistoricalStrategyAdapter):
    adapter_id = 'DRI_REPLAY'


class RedBarHistoricalStrategyAdapter(_ResearchOnlyHistoricalStrategyAdapter):
    adapter_id = 'RED_BAR_REPLAY'
