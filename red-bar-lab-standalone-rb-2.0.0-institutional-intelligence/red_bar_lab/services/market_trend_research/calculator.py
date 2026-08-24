from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import isfinite

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
    return OiChangeEvidence(current, baseline, absolute, absolute / baseline * 100.0, "AVAILABLE")


def _nearest_atm(strikes: tuple[float, ...], spot: float) -> float:
    if not strikes: raise ValueError("NO_STRIKES")
    return min(set(strikes), key=lambda strike: (abs(strike - spot), strike))


def _interval(strikes: tuple[float, ...]) -> float:
    unique = sorted(set(strikes))
    diffs = [round(unique[i + 1] - unique[i], 8) for i in range(len(unique) - 1)]
    positive = [value for value in diffs if value > 0]
    if not positive: raise ValueError("STRIKE_INTERVAL_UNAVAILABLE")
    counts: dict[float, int] = defaultdict(int)
    for value in positive: counts[value] += 1
    highest = max(counts.values())
    modes = [value for value, count in counts.items() if count == highest]
    if len(modes) != 1: raise ValueError("STRIKE_INTERVAL_AMBIGUOUS")
    return modes[0]


class DualPcrCalculator:
    def __init__(self, policy: MarketTrendResearchPolicy) -> None:
        self.policy = policy

    @staticmethod
    def index(cells: tuple[OptionOiCell, ...]) -> dict[tuple[float, str], OptionOiCell]:
        result: dict[tuple[float, str], OptionOiCell] = {}
        for cell in cells:
            key = (float(cell.strike), cell.option_side)
            if key in result: raise ValueError("DUPLICATE_STRIKE_SIDE")
            result[key] = cell
        return result

    def define_window(self, cells: tuple[OptionOiCell, ...], *, spot: float, window_steps: int) -> PcrWindowDefinition:
        if not cells: raise ValueError("EMPTY_CHAIN")
        expiries = {cell.expiry for cell in cells}
        if len(expiries) != 1: raise ValueError("EXPIRY_MISMATCH")
        expiry = next(iter(expiries))
        common = tuple(sorted(
            {cell.strike for cell in cells if cell.option_side == "CE"}
            & {cell.strike for cell in cells if cell.option_side == "PE"}
        ))
        interval = _interval(common)
        atm = _nearest_atm(common, spot)
        strikes = tuple(atm + interval * offset for offset in range(-window_steps, window_steps + 1))
        index = self.index(cells)
        keys: list[str] = []
        for strike in strikes:
            for side in ("CE", "PE"):
                cell = index.get((float(strike), side))
                if cell is None: raise ValueError("PARTIAL_CONTRACT_WINDOW")
                keys.append(cell.instrument_key)
        return PcrWindowDefinition(expiry, atm, interval, window_steps, strikes, tuple(keys))

    def panel(
        self,
        *,
        name: str,
        cells: tuple[OptionOiCell, ...],
        window: PcrWindowDefinition,
        spot: float,
        sessions_to_expiry: int,
        previous_by_key: dict[str, OptionOiCell] | None = None,
        anchor_by_key: dict[str, OptionOiCell] | None = None,
        previous_pcr: float | None = None,
        previous_timestamp: datetime | None = None,
        source_timestamp: datetime,
        evaluated_at: datetime,
        anchor_timestamp: datetime | None = None,
        anchor_spot: float | None = None,
    ) -> PcrResearchPanel:
        by_key = {cell.instrument_key: cell for cell in cells}
        selected = [by_key[key] for key in window.instrument_keys if key in by_key]
        if len(selected) != window.expected_contract_count: raise ValueError("PARTIAL_CONTRACT_WINDOW")
        ce = sum(cell.current_oi for cell in selected if cell.option_side == "CE")
        pe = sum(cell.current_oi for cell in selected if cell.option_side == "PE")
        pcr = None if ce == 0 else pe / ce
        state = ResearchState.PCR_UNAVAILABLE_ZERO_DENOMINATOR if pcr is None else ResearchState.READY
        classification = PcrBias.UNAVAILABLE if pcr is None else self.policy.classify(pcr)
        elapsed = None
        if previous_timestamp is not None:
            elapsed = (source_timestamp - previous_timestamp).total_seconds()
        absolute = None if pcr is None or previous_pcr is None else pcr - previous_pcr
        percentage = None if absolute is None or previous_pcr == 0 else absolute / previous_pcr * 100.0
        slope = None if absolute is None or not elapsed or elapsed <= 0 else absolute / (elapsed / 60.0)
        persistence = "UNAVAILABLE" if absolute is None else ("RISING" if absolute > 0 else "FALLING" if absolute < 0 else "FLAT")
        aggregate = PcrAggregate(ce, pe, pcr, classification, previous_pcr, absolute, percentage, slope, persistence)
        previous_by_key = previous_by_key or {}
        anchor_by_key = anchor_by_key or {}
        grouped: dict[float, dict[str, OptionOiCell]] = defaultdict(dict)
        for cell in selected: grouped[cell.strike][cell.option_side] = cell
        rows: list[dict[str, object]] = []
        for strike in window.strikes:
            ce_cell, pe_cell = grouped[strike]["CE"], grouped[strike]["PE"]
            ce_prev = previous_by_key.get(ce_cell.instrument_key)
            pe_prev = previous_by_key.get(pe_cell.instrument_key)
            ce_change = _change(ce_cell.current_oi, ce_prev.current_oi if ce_prev else None)
            pe_change = _change(pe_cell.current_oi, pe_prev.current_oi if pe_prev else None)
            rows.append({
                "strike": strike,
                "position": "ATM" if strike == window.atm else ("BELOW_ATM" if strike < window.atm else "ABOVE_ATM"),
                "ce_current_oi": ce_cell.current_oi,
                "ce_baseline_oi": ce_change.baseline,
                "ce_change": ce_change.absolute_change,
                "ce_change_pct": ce_change.percentage_change,
                "pe_current_oi": pe_cell.current_oi,
                "pe_baseline_oi": pe_change.baseline,
                "pe_change": pe_change.absolute_change,
                "pe_change_pct": pe_change.percentage_change,
                "ce_day_change": _change(ce_cell.current_oi, ce_cell.provider_prev_oi).absolute_change,
                "pe_day_change": _change(pe_cell.current_oi, pe_cell.provider_prev_oi).absolute_change,
                "ce_anchor_change": _change(ce_cell.current_oi, anchor_by_key.get(ce_cell.instrument_key).current_oi if ce_cell.instrument_key in anchor_by_key else None).absolute_change,
                "pe_anchor_change": _change(pe_cell.current_oi, anchor_by_key.get(pe_cell.instrument_key).current_oi if pe_cell.instrument_key in anchor_by_key else None).absolute_change,
            })
        ce_baseline = sum(float(row["ce_baseline_oi"]) for row in rows if row["ce_baseline_oi"] is not None)
        pe_baseline = sum(float(row["pe_baseline_oi"]) for row in rows if row["pe_baseline_oi"] is not None)
        rows.append({
            "strike": "OVERALL TOTAL", "position": "TOTAL",
            "ce_current_oi": ce, "ce_baseline_oi": ce_baseline,
            "ce_change": ce - ce_baseline, "ce_change_pct": None if ce_baseline == 0 else (ce - ce_baseline) / ce_baseline * 100.0,
            "pe_current_oi": pe, "pe_baseline_oi": pe_baseline,
            "pe_change": pe - pe_baseline, "pe_change_pct": None if pe_baseline == 0 else (pe - pe_baseline) / pe_baseline * 100.0,
        })
        relevance = None
        if anchor_spot is not None:
            distance = abs(spot - window.atm) / window.strike_interval
            relevance = "ACTIVE" if distance < window.window_steps - 1 else "NEAR_EDGE" if distance <= window.window_steps else "OUTSIDE_RANGE"
        return PcrResearchPanel(name, state, spot, window.atm, window.expiry, sessions_to_expiry, window.strike_interval, window.window_steps, window.expected_contract_count, len(selected), source_timestamp, aggregate, tuple(rows), anchor_timestamp, anchor_spot, window.atm if anchor_timestamp else None, relevance)
