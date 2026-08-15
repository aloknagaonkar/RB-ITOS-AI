from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class RelevantContractCoverageRow:
    symbol: str
    option_type: str
    strike: float
    relevant: bool
    candle_coverage_pct: float
    oi_coverage_pct: float
    missing_bars: int
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "Symbol": self.symbol,
            "Option Type": self.option_type,
            "Strike": self.strike,
            "Strategy Relevant": self.relevant,
            "Candle Coverage %": round(self.candle_coverage_pct, 2),
            "OI Coverage %": round(self.oi_coverage_pct, 2),
            "Missing Bars": self.missing_bars,
            "Status": self.status,
        }


@dataclass(frozen=True)
class HistoricalDRIRelevantCoverageAudit:
    global_replay_ready: bool
    global_fidelity: str
    reference_low: float | None
    reference_high: float | None
    strike_step: float | None
    relevant_low: float | None
    relevant_high: float | None
    relevant_contracts: int
    relevant_ce_contracts: int
    relevant_pe_contracts: int
    relevant_complete_contracts: int
    relevant_candle_coverage_pct: float
    relevant_oi_coverage_pct: float
    missing_relevant_contracts: int
    status: str
    reason: str
    rows: tuple[RelevantContractCoverageRow, ...]

    @property
    def strategy_relevant_ready(self) -> bool:
        return self.status in {"FULL_REPLAY_READY", "STRATEGY_RELEVANT_COVERAGE_HIGH"}

    def summary(self) -> dict[str, object]:
        return {
            "Global Replay Ready": self.global_replay_ready,
            "Global Fidelity": self.global_fidelity,
            "Reference Low": self.reference_low,
            "Reference High": self.reference_high,
            "Strike Step": self.strike_step,
            "Relevant Range Low": self.relevant_low,
            "Relevant Range High": self.relevant_high,
            "Relevant Contracts": self.relevant_contracts,
            "Relevant CE": self.relevant_ce_contracts,
            "Relevant PE": self.relevant_pe_contracts,
            "Relevant Complete": self.relevant_complete_contracts,
            "Relevant Candle Coverage %": round(self.relevant_candle_coverage_pct, 2),
            "Relevant OI Coverage %": round(self.relevant_oi_coverage_pct, 2),
            "Missing Relevant Contracts": self.missing_relevant_contracts,
            "Audit Status": self.status,
            "Reason": self.reason,
        }

    def relevant_rows(self) -> list[dict[str, object]]:
        return [row.as_dict() for row in self.rows if row.relevant]

    def all_rows(self) -> list[dict[str, object]]:
        return [row.as_dict() for row in self.rows]


def analyze_historical_dri_relevant_coverage(
    coverage: object,
    underlying: pd.DataFrame,
    *,
    strike_buffer_steps: int = 2,
    minimum_candle_coverage_pct: float = 90.0,
    minimum_oi_coverage_pct: float = 80.0,
) -> HistoricalDRIRelevantCoverageAudit:
    """Audit contracts that could plausibly enter the DRI candidate universe.

    This function is diagnostic-only. It does not change ``coverage.replay_ready``
    and must not be used to bypass the existing historical replay gate.
    """

    contracts = tuple(getattr(coverage, "contracts", ()) or ())
    prices = _underlying_prices(underlying)
    reference_low = min(prices) if prices else None
    reference_high = max(prices) if prices else None
    strikes = sorted({
        float(getattr(item, "strike"))
        for item in contracts
        if _number(getattr(item, "strike", None)) is not None
        and float(getattr(item, "strike")) > 0.0
    })
    strike_step = _strike_step(strikes)

    if reference_low is None or reference_high is None or not strikes:
        return HistoricalDRIRelevantCoverageAudit(
            global_replay_ready=bool(getattr(coverage, "replay_ready", False)),
            global_fidelity=str(getattr(coverage, "fidelity", "UNKNOWN")),
            reference_low=reference_low,
            reference_high=reference_high,
            strike_step=strike_step,
            relevant_low=None,
            relevant_high=None,
            relevant_contracts=0,
            relevant_ce_contracts=0,
            relevant_pe_contracts=0,
            relevant_complete_contracts=0,
            relevant_candle_coverage_pct=0.0,
            relevant_oi_coverage_pct=0.0,
            missing_relevant_contracts=0,
            status="INSUFFICIENT_AUDIT_DATA",
            reason="Underlying prices or option strike metadata are unavailable.",
            rows=(),
        )

    midpoint = (reference_low + reference_high) / 2.0
    buffer = max(
        (strike_step or 0.0) * max(0, int(strike_buffer_steps)),
        midpoint * 0.01,
    )
    relevant_low = reference_low - buffer
    relevant_high = reference_high + buffer

    rows: list[RelevantContractCoverageRow] = []
    relevant_expected = relevant_stored = relevant_oi = 0
    relevant_count = relevant_complete = missing_relevant = 0
    ce_count = pe_count = 0

    for item in contracts:
        strike = float(_number(getattr(item, "strike", None)) or 0.0)
        relevant = relevant_low <= strike <= relevant_high
        expected = max(0, int(getattr(item, "expected_bars", 0) or 0))
        stored = max(0, int(getattr(item, "stored_bars", 0) or 0))
        oi_bars = max(0, int(getattr(item, "oi_bars", 0) or 0))
        candle_pct = float(_number(getattr(item, "candle_coverage_pct", None)) or 0.0)
        oi_pct = (oi_bars / expected * 100.0) if expected else 0.0
        complete = (
            expected > 0
            and candle_pct >= minimum_candle_coverage_pct
            and oi_pct >= minimum_oi_coverage_pct
        )
        status = "READY" if complete else "PARTIAL" if stored else "MISSING"
        option_type = str(getattr(item, "option_type", "") or "").upper()
        rows.append(
            RelevantContractCoverageRow(
                symbol=str(getattr(item, "symbol", "") or ""),
                option_type=option_type,
                strike=strike,
                relevant=relevant,
                candle_coverage_pct=candle_pct,
                oi_coverage_pct=oi_pct,
                missing_bars=max(0, int(getattr(item, "missing_bars", 0) or 0)),
                status=status,
            )
        )
        if not relevant:
            continue
        relevant_count += 1
        relevant_expected += expected
        relevant_stored += min(stored, expected) if expected else stored
        relevant_oi += min(oi_bars, expected) if expected else oi_bars
        if option_type == "CE":
            ce_count += 1
        elif option_type == "PE":
            pe_count += 1
        if complete:
            relevant_complete += 1
        if stored == 0:
            missing_relevant += 1

    candle_cov = (
        relevant_stored / relevant_expected * 100.0 if relevant_expected else 0.0
    )
    oi_cov = relevant_oi / relevant_expected * 100.0 if relevant_expected else 0.0
    global_ready = bool(getattr(coverage, "replay_ready", False))

    if global_ready:
        status = "FULL_REPLAY_READY"
        reason = "The existing global replay-readiness gate already passes."
    elif (
        relevant_count > 0
        and ce_count > 0
        and pe_count > 0
        and relevant_complete == relevant_count
        and candle_cov >= minimum_candle_coverage_pct
        and oi_cov >= minimum_oi_coverage_pct
    ):
        status = "STRATEGY_RELEVANT_COVERAGE_HIGH"
        reason = (
            "All contracts inside the DRI-relevant strike window meet the audit "
            "thresholds. This is a diagnostic finding only; the global replay gate "
            "remains unchanged."
        )
    else:
        status = "STRATEGY_RELEVANT_COVERAGE_INCOMPLETE"
        reason = (
            "One or more contracts inside the DRI-relevant strike window have "
            "insufficient candle or OI coverage."
        )

    return HistoricalDRIRelevantCoverageAudit(
        global_replay_ready=global_ready,
        global_fidelity=str(getattr(coverage, "fidelity", "UNKNOWN")),
        reference_low=reference_low,
        reference_high=reference_high,
        strike_step=strike_step,
        relevant_low=relevant_low,
        relevant_high=relevant_high,
        relevant_contracts=relevant_count,
        relevant_ce_contracts=ce_count,
        relevant_pe_contracts=pe_count,
        relevant_complete_contracts=relevant_complete,
        relevant_candle_coverage_pct=candle_cov,
        relevant_oi_coverage_pct=oi_cov,
        missing_relevant_contracts=missing_relevant,
        status=status,
        reason=reason,
        rows=tuple(rows),
    )


def _underlying_prices(frame: pd.DataFrame) -> list[float]:
    if frame is None or frame.empty:
        return []
    values: list[float] = []
    for column in ("open", "high", "low", "close"):
        if column in frame.columns:
            numeric = pd.to_numeric(frame[column], errors="coerce").dropna()
            values.extend(float(value) for value in numeric if float(value) > 0.0)
    return values


def _strike_step(strikes: Iterable[float]) -> float | None:
    ordered = sorted(set(float(value) for value in strikes))
    differences = [
        current - previous
        for previous, current in zip(ordered, ordered[1:])
        if current > previous
    ]
    return float(median(differences)) if differences else None


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number
