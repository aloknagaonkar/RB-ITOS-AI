from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .models import (
    OiChangeEvidence,
    OptionOiCell,
    PcrAggregate,
    PcrBias,
    PcrResearchPanel,
    PcrWindowDefinition,
    ResearchState,
)
from .policy import MarketTrendResearchPolicy


def _change(current: float, baseline: float | None) -> OiChangeEvidence:
    if baseline is None:
        return OiChangeEvidence(current, None, None, None, "BASELINE_MISSING")
    absolute = current - baseline
    if baseline == 0:
        return OiChangeEvidence(current, baseline, absolute, None, "ZERO_BASELINE")
    return OiChangeEvidence(
        current,
        baseline,
        absolute,
        absolute / baseline * 100.0,
        "AVAILABLE",
    )


def _nearest_atm(strikes: tuple[float, ...], spot: float) -> float:
    if not strikes:
        raise ValueError("NO_STRIKES")
    return min(set(strikes), key=lambda strike: (abs(strike - spot), strike))


def _interval(strikes: tuple[float, ...]) -> float:
    unique = sorted(set(strikes))
    differences = [
        round(unique[index + 1] - unique[index], 8)
        for index in range(len(unique) - 1)
    ]
    positive = [value for value in differences if value > 0]
    if not positive:
        raise ValueError("STRIKE_INTERVAL_UNAVAILABLE")
    counts: dict[float, int] = defaultdict(int)
    for value in positive:
        counts[value] += 1
    highest = max(counts.values())
    modes = [value for value, count in counts.items() if count == highest]
    if len(modes) != 1:
        raise ValueError("STRIKE_INTERVAL_AMBIGUOUS")
    return modes[0]


def _aggregate_change(
    current: float,
    baselines: tuple[float | None, ...],
) -> OiChangeEvidence:
    if any(value is None for value in baselines):
        return OiChangeEvidence(current, None, None, None, "BASELINE_MISSING")
    baseline = sum(float(value) for value in baselines if value is not None)
    return _change(current, baseline)


class DualPcrCalculator:
    def __init__(self, policy: MarketTrendResearchPolicy) -> None:
        self.policy = policy

    @staticmethod
    def index(
        cells: tuple[OptionOiCell, ...],
    ) -> dict[tuple[float, str], OptionOiCell]:
        result: dict[tuple[float, str], OptionOiCell] = {}
        for cell in cells:
            key = (float(cell.strike), cell.option_side)
            if key in result:
                raise ValueError("DUPLICATE_STRIKE_SIDE")
            result[key] = cell
        return result

    def define_window(
        self,
        cells: tuple[OptionOiCell, ...],
        *,
        spot: float,
        window_steps: int,
    ) -> PcrWindowDefinition:
        if not cells:
            raise ValueError("EMPTY_CHAIN")
        expiries = {cell.expiry for cell in cells}
        if len(expiries) != 1:
            raise ValueError("EXPIRY_MISMATCH")
        expiry = next(iter(expiries))
        common = tuple(
            sorted(
                {cell.strike for cell in cells if cell.option_side == "CE"}
                & {cell.strike for cell in cells if cell.option_side == "PE"}
            )
        )
        interval = _interval(common)
        atm = _nearest_atm(common, spot)
        strikes = tuple(
            atm + interval * offset
            for offset in range(-window_steps, window_steps + 1)
        )
        index = self.index(cells)
        keys: list[str] = []
        for strike in strikes:
            for side in ("CE", "PE"):
                cell = index.get((float(strike), side))
                if cell is None:
                    raise ValueError("PARTIAL_CONTRACT_WINDOW")
                keys.append(cell.instrument_key)
        return PcrWindowDefinition(
            expiry,
            atm,
            interval,
            window_steps,
            strikes,
            tuple(keys),
        )

    def panel(
        self,
        *,
        name: str,
        cells: tuple[OptionOiCell, ...],
        window: PcrWindowDefinition,
        spot: float,
        sessions_to_expiry: int,
        source_timestamp: datetime,
        evaluated_at: datetime,
        previous_by_key: dict[str, OptionOiCell] | None = None,
        anchor_by_key: dict[str, OptionOiCell] | None = None,
        previous_pcr: float | None = None,
        previous_timestamp: datetime | None = None,
        persistence_state: str | None = None,
        consecutive_count: int = 0,
        panel_state: ResearchState | None = None,
        anchor_timestamp: datetime | None = None,
        anchor_status: str | None = None,
        anchor_spot: float | None = None,
    ) -> PcrResearchPanel:
        del evaluated_at
        by_key = {cell.instrument_key: cell for cell in cells}
        selected = [by_key[key] for key in window.instrument_keys if key in by_key]
        if len(selected) != window.expected_contract_count:
            raise ValueError("PARTIAL_CONTRACT_WINDOW")
        ce_total = sum(
            cell.current_oi for cell in selected if cell.option_side == "CE"
        )
        pe_total = sum(
            cell.current_oi for cell in selected if cell.option_side == "PE"
        )
        pcr = None if ce_total == 0 else pe_total / ce_total
        state = panel_state or (
            ResearchState.PCR_UNAVAILABLE_ZERO_DENOMINATOR
            if pcr is None
            else ResearchState.READY
        )
        classification = (
            PcrBias.UNAVAILABLE if pcr is None else self.policy.classify(pcr)
        )
        elapsed_seconds = (
            None
            if previous_timestamp is None
            else (source_timestamp - previous_timestamp).total_seconds()
        )
        absolute = (
            None if pcr is None or previous_pcr is None else pcr - previous_pcr
        )
        percentage = (
            None
            if absolute is None or previous_pcr == 0
            else absolute / previous_pcr * 100.0
        )
        slope = (
            None
            if absolute is None
            or elapsed_seconds is None
            or elapsed_seconds <= 0
            else absolute / (elapsed_seconds / 60.0)
        )
        derived_persistence = (
            "UNAVAILABLE"
            if absolute is None
            else "RISING"
            if absolute > 0
            else "FALLING"
            if absolute < 0
            else "FLAT"
        )
        aggregate = PcrAggregate(
            ce_total,
            pe_total,
            pcr,
            classification,
            previous_pcr,
            absolute,
            percentage,
            slope,
            persistence_state or derived_persistence,
            consecutive_count,
        )
        previous_by_key = previous_by_key or {}
        anchor_by_key = anchor_by_key or {}
        grouped: dict[float, dict[str, OptionOiCell]] = defaultdict(dict)
        for cell in selected:
            grouped[cell.strike][cell.option_side] = cell
        rows: list[dict[str, object]] = []
        ce_baselines: list[float | None] = []
        pe_baselines: list[float | None] = []
        for strike in window.strikes:
            ce_cell = grouped[strike]["CE"]
            pe_cell = grouped[strike]["PE"]
            ce_previous = previous_by_key.get(ce_cell.instrument_key)
            pe_previous = previous_by_key.get(pe_cell.instrument_key)
            ce_change = _change(
                ce_cell.current_oi,
                ce_previous.current_oi if ce_previous else None,
            )
            pe_change = _change(
                pe_cell.current_oi,
                pe_previous.current_oi if pe_previous else None,
            )
            ce_anchor = anchor_by_key.get(ce_cell.instrument_key)
            pe_anchor = anchor_by_key.get(pe_cell.instrument_key)
            ce_anchor_change = _change(
                ce_cell.current_oi,
                ce_anchor.current_oi if ce_anchor else None,
            )
            pe_anchor_change = _change(
                pe_cell.current_oi,
                pe_anchor.current_oi if pe_anchor else None,
            )
            ce_day_change = _change(ce_cell.current_oi, ce_cell.provider_prev_oi)
            pe_day_change = _change(pe_cell.current_oi, pe_cell.provider_prev_oi)
            ce_baselines.append(ce_change.baseline)
            pe_baselines.append(pe_change.baseline)
            rows.append(
                {
                    "strike": strike,
                    "position": (
                        "ATM"
                        if strike == window.atm
                        else "BELOW_ATM"
                        if strike < window.atm
                        else "ABOVE_ATM"
                    ),
                    "ce_current_oi": ce_cell.current_oi,
                    "ce_baseline_oi": ce_change.baseline,
                    "ce_change": ce_change.absolute_change,
                    "ce_change_pct": ce_change.percentage_change,
                    "ce_change_reason": ce_change.reason,
                    "pe_current_oi": pe_cell.current_oi,
                    "pe_baseline_oi": pe_change.baseline,
                    "pe_change": pe_change.absolute_change,
                    "pe_change_pct": pe_change.percentage_change,
                    "pe_change_reason": pe_change.reason,
                    "ce_day_change": ce_day_change.absolute_change,
                    "ce_day_change_pct": ce_day_change.percentage_change,
                    "pe_day_change": pe_day_change.absolute_change,
                    "pe_day_change_pct": pe_day_change.percentage_change,
                    "ce_anchor_change": ce_anchor_change.absolute_change,
                    "ce_anchor_change_pct": ce_anchor_change.percentage_change,
                    "pe_anchor_change": pe_anchor_change.absolute_change,
                    "pe_anchor_change_pct": pe_anchor_change.percentage_change,
                }
            )
        ce_aggregate_change = _aggregate_change(ce_total, tuple(ce_baselines))
        pe_aggregate_change = _aggregate_change(pe_total, tuple(pe_baselines))
        rows.append(
            {
                "strike": "OVERALL TOTAL",
                "position": "TOTAL",
                "ce_current_oi": ce_total,
                "ce_baseline_oi": ce_aggregate_change.baseline,
                "ce_change": ce_aggregate_change.absolute_change,
                "ce_change_pct": ce_aggregate_change.percentage_change,
                "ce_change_reason": ce_aggregate_change.reason,
                "pe_current_oi": pe_total,
                "pe_baseline_oi": pe_aggregate_change.baseline,
                "pe_change": pe_aggregate_change.absolute_change,
                "pe_change_pct": pe_aggregate_change.percentage_change,
                "pe_change_reason": pe_aggregate_change.reason,
            }
        )
        relevance = None
        if anchor_spot is not None:
            distance_steps = abs(spot - window.atm) / window.strike_interval
            relevance = (
                "ACTIVE"
                if distance_steps < window.window_steps - 1
                else "NEAR_EDGE"
                if distance_steps <= window.window_steps
                else "OUTSIDE_RANGE"
            )
        return PcrResearchPanel(
            name=name,
            state=state,
            spot=spot,
            atm=window.atm,
            expiry=window.expiry,
            sessions_to_expiry=sessions_to_expiry,
            strike_interval=window.strike_interval,
            window_steps=window.window_steps,
            expected_contract_count=window.expected_contract_count,
            observed_contract_count=len(selected),
            source_timestamp=source_timestamp,
            aggregate=aggregate,
            rows=tuple(rows),
            anchor_timestamp=anchor_timestamp,
            anchor_status=anchor_status,
            anchor_spot=anchor_spot,
            anchor_atm=window.atm if anchor_timestamp else None,
            anchor_relevance=relevance,
        )
