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
    if not isfinite(current):
        raise ValueError("CURRENT_OI_INVALID")
    if baseline is None:
        return OiChangeEvidence(current, None, None, None, "BASELINE_MISSING")
    if not isfinite(baseline):
        raise ValueError("BASELINE_OI_INVALID")
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
    return _change(current, sum(float(value) for value in baselines if value is not None))


def _put_change(
    row: dict[str, object],
    *,
    prefix: str,
    evidence: OiChangeEvidence,
) -> None:
    change_prefix = prefix.replace("_previous_day", "_day").replace(
        "_previous_refresh", "_refresh"
    )
    row[f"{prefix}_oi"] = evidence.baseline
    row[f"{change_prefix}_change"] = evidence.absolute_change
    row[f"{change_prefix}_change_pct"] = evidence.percentage_change
    row[f"{change_prefix}_change_reason"] = evidence.reason


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

    def window_for_fixed_strikes(
        self,
        cells: tuple[OptionOiCell, ...],
        *,
        expiry,
        atm: float,
        strike_interval: float,
        window_steps: int,
        strikes: tuple[float, ...],
    ) -> PcrWindowDefinition:
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
            strike_interval,
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
        opening_by_key: dict[str, OptionOiCell] | None = None,
        previous_pcr: float | None = None,
        previous_timestamp: datetime | None = None,
        persistence_state: str | None = None,
        consecutive_count: int = 0,
        panel_state: ResearchState | None = None,
        reference_timestamp: datetime | None = None,
        reference_status: str | None = None,
        reference_spot: float | None = None,
        baseline_timestamp: datetime | None = None,
        baseline_status: str | None = None,
        data_status: str | None = None,
        **_: object,
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
            "INSUFFICIENT_HISTORY"
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

        refresh_by_key = previous_by_key or {}
        opening_by_key = opening_by_key or {}
        grouped: dict[float, dict[str, OptionOiCell]] = defaultdict(dict)
        for cell in selected:
            grouped[cell.strike][cell.option_side] = cell

        rows: list[dict[str, object]] = []
        ce_day_baselines: list[float | None] = []
        pe_day_baselines: list[float | None] = []
        ce_opening_baselines: list[float | None] = []
        pe_opening_baselines: list[float | None] = []
        ce_refresh_baselines: list[float | None] = []
        pe_refresh_baselines: list[float | None] = []

        for strike in window.strikes:
            ce_cell = grouped[strike]["CE"]
            pe_cell = grouped[strike]["PE"]
            ce_open = opening_by_key.get(ce_cell.instrument_key)
            pe_open = opening_by_key.get(pe_cell.instrument_key)
            ce_refresh = refresh_by_key.get(ce_cell.instrument_key)
            pe_refresh = refresh_by_key.get(pe_cell.instrument_key)

            ce_day = _change(ce_cell.current_oi, ce_cell.provider_prev_oi)
            pe_day = _change(pe_cell.current_oi, pe_cell.provider_prev_oi)
            ce_opening = _change(
                ce_cell.current_oi,
                None if ce_open is None else ce_open.current_oi,
            )
            pe_opening = _change(
                pe_cell.current_oi,
                None if pe_open is None else pe_open.current_oi,
            )
            ce_refresh_change = _change(
                ce_cell.current_oi,
                None if ce_refresh is None else ce_refresh.current_oi,
            )
            pe_refresh_change = _change(
                pe_cell.current_oi,
                None if pe_refresh is None else pe_refresh.current_oi,
            )

            ce_day_baselines.append(ce_day.baseline)
            pe_day_baselines.append(pe_day.baseline)
            ce_opening_baselines.append(ce_opening.baseline)
            pe_opening_baselines.append(pe_opening.baseline)
            ce_refresh_baselines.append(ce_refresh_change.baseline)
            pe_refresh_baselines.append(pe_refresh_change.baseline)

            row: dict[str, object] = {
                "strike": strike,
                "position": (
                    "ATM"
                    if strike == window.atm
                    else "BELOW_ATM"
                    if strike < window.atm
                    else "ABOVE_ATM"
                ),
                "ce_current_oi": ce_cell.current_oi,
                "pe_current_oi": pe_cell.current_oi,
            }
            _put_change(row, prefix="ce_previous_day", evidence=ce_day)
            _put_change(row, prefix="pe_previous_day", evidence=pe_day)
            _put_change(row, prefix="ce_opening", evidence=ce_opening)
            _put_change(row, prefix="pe_opening", evidence=pe_opening)
            _put_change(
                row,
                prefix="ce_previous_refresh",
                evidence=ce_refresh_change,
            )
            _put_change(
                row,
                prefix="pe_previous_refresh",
                evidence=pe_refresh_change,
            )
            rows.append(row)

        ce_day_total = _aggregate_change(ce_total, tuple(ce_day_baselines))
        pe_day_total = _aggregate_change(pe_total, tuple(pe_day_baselines))
        ce_opening_total = _aggregate_change(ce_total, tuple(ce_opening_baselines))
        pe_opening_total = _aggregate_change(pe_total, tuple(pe_opening_baselines))
        ce_refresh_total = _aggregate_change(ce_total, tuple(ce_refresh_baselines))
        pe_refresh_total = _aggregate_change(pe_total, tuple(pe_refresh_baselines))

        total_row: dict[str, object] = {
            "strike": "OVERALL TOTAL",
            "position": "TOTAL",
            "ce_current_oi": ce_total,
            "pe_current_oi": pe_total,
        }
        _put_change(total_row, prefix="ce_previous_day", evidence=ce_day_total)
        _put_change(total_row, prefix="pe_previous_day", evidence=pe_day_total)
        _put_change(total_row, prefix="ce_opening", evidence=ce_opening_total)
        _put_change(total_row, prefix="pe_opening", evidence=pe_opening_total)
        _put_change(
            total_row,
            prefix="ce_previous_refresh",
            evidence=ce_refresh_total,
        )
        _put_change(
            total_row,
            prefix="pe_previous_refresh",
            evidence=pe_refresh_total,
        )
        rows.append(total_row)

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
            previous_timestamp=previous_timestamp,
            reference_timestamp=reference_timestamp,
            reference_status=reference_status,
            reference_spot=reference_spot,
            baseline_timestamp=baseline_timestamp,
            baseline_status=baseline_status,
            data_status=data_status or state.value,
        )
