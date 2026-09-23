from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable

from .domain import IST
from .hilega_milega_option_candidate_v1 import OptionCandidateSet
from .live_option_minute_source_v1 import validate_option_minute

MODEL = "HILEGA_MILEGA_EXACT_OPTION_ECONOMICS_RESEARCH_V1"
ENTRY_SEMANTICS = "NEXT_EXECUTABLE_1M_OPEN_AT_SIGNAL_BOUNDARY"
SELECTION_POLICY = "RESEARCH_ONLY_NO_CONTRACT_SELECTION"
DEFAULT_HORIZONS = (1, 3, 5, 10, 15)


@dataclass(frozen=True)
class HorizonEconomics:
    horizon_minutes: int
    exit_timestamp: str
    exit_close: float
    return_pct: float
    mfe_pct: float
    mae_pct: float


@dataclass(frozen=True)
class CandidateEconomics:
    strike: float
    side: str
    instrument_key: str
    relation_to_atm: int
    expiry: str
    status: str
    entry_timestamp: str
    entry_open: float | None
    horizons: tuple[HorizonEconomics, ...]
    issue: str | None = None


@dataclass(frozen=True)
class CandidateEconomicsSet:
    model: str
    status: str
    signal_bar: str
    signal_boundary: str
    entry_semantics: str
    selection_policy: str
    selected_instrument_key: str | None
    horizons_minutes: tuple[int, ...]
    candidates: tuple[CandidateEconomics, ...]
    issue: str | None = None

    def payload(self) -> dict:
        out = asdict(self)
        out["candidates"] = [
            {
                **asdict(c),
                "horizons": [asdict(h) for h in c.horizons],
            }
            for c in self.candidates
        ]
        return out


def _minute_key(value: datetime) -> datetime:
    return value.astimezone(IST).replace(second=0, microsecond=0)


def _pct(entry: float, value: float) -> float:
    return ((value / entry) - 1.0) * 100.0


def observe_exact_candidate_economics(
    *,
    signal_bar_ts: datetime,
    candidate_set: OptionCandidateSet,
    option_minutes: Callable[[str], Iterable],
    horizons_minutes: tuple[int, ...] = DEFAULT_HORIZONS,
) -> CandidateEconomicsSet:
    """Measure exact-option forward economics without selecting a contract.

    A 5m signal bar labelled HH:MM becomes known at HH:MM+5. Research entry is
    the exact OPEN of the 1m option candle starting at that causal boundary.
    Horizon N uses the CLOSE of the Nth one-minute candle after entry begins.
    Every minute from entry through the largest requested horizon must exist
    exactly and be healthy. There is no nearest-minute fallback, interpolation,
    later-contract substitution, quantity sizing, or order creation.
    """
    bar_ts = _minute_key(signal_bar_ts)
    boundary = bar_ts + timedelta(minutes=5)

    horizons = tuple(sorted(set(int(x) for x in horizons_minutes)))
    if not horizons or horizons[0] <= 0:
        raise ValueError("horizons_minutes must contain positive integers")

    if candidate_set.status != "AVAILABLE":
        return CandidateEconomicsSet(
            model=MODEL,
            status="BLOCKED",
            signal_bar=bar_ts.isoformat(),
            signal_boundary=boundary.isoformat(),
            entry_semantics=ENTRY_SEMANTICS,
            selection_policy=SELECTION_POLICY,
            selected_instrument_key=None,
            horizons_minutes=horizons,
            candidates=(),
            issue="CANDIDATE_SET_NOT_AVAILABLE",
        )

    max_h = max(horizons)
    expected_times = tuple(boundary + timedelta(minutes=i) for i in range(max_h))
    results: list[CandidateEconomics] = []
    overall_issues: list[str] = []

    for candidate in candidate_set.candidates:
        rows = list(option_minutes(candidate.instrument_key))
        by_ts: dict[datetime, object] = {}
        duplicate = False
        for row in rows:
            ts = _minute_key(row.timestamp)
            if ts in by_ts:
                duplicate = True
            by_ts[ts] = row

        issues: list[str] = []
        if duplicate:
            issues.append("DUPLICATE_MINUTE")

        selected_rows = []
        previous = None
        for ts in expected_times:
            row = by_ts.get(ts)
            if row is None:
                issues.append(f"MISSING_EXACT_MINUTE:{ts.isoformat()}")
                continue
            health = validate_option_minute(
                row,
                expected_instrument_key=candidate.instrument_key,
                previous_timestamp=previous,
            )
            if not health.allowed:
                issues.append(f"{ts.isoformat()}:{health.reason or health.state}")
                continue
            selected_rows.append(row)
            previous = row.timestamp

        if issues or len(selected_rows) != max_h:
            issue = ";".join(issues) if issues else "INCOMPLETE_EXACT_MINUTE_PATH"
            overall_issues.append(f"{candidate.instrument_key}:{issue}")
            results.append(
                CandidateEconomics(
                    strike=candidate.strike,
                    side=candidate.side,
                    instrument_key=candidate.instrument_key,
                    relation_to_atm=candidate.relation_to_atm,
                    expiry=candidate.expiry,
                    status="INCOMPLETE",
                    entry_timestamp=boundary.isoformat(),
                    entry_open=None,
                    horizons=(),
                    issue=issue,
                )
            )
            continue

        entry = float(selected_rows[0].open)
        if entry <= 0:
            issue = "NONPOSITIVE_ENTRY_OPEN"
            overall_issues.append(f"{candidate.instrument_key}:{issue}")
            results.append(
                CandidateEconomics(
                    strike=candidate.strike,
                    side=candidate.side,
                    instrument_key=candidate.instrument_key,
                    relation_to_atm=candidate.relation_to_atm,
                    expiry=candidate.expiry,
                    status="INCOMPLETE",
                    entry_timestamp=boundary.isoformat(),
                    entry_open=None,
                    horizons=(),
                    issue=issue,
                )
            )
            continue

        metrics: list[HorizonEconomics] = []
        for horizon in horizons:
            window = selected_rows[:horizon]
            last = window[-1]
            max_high = max(float(x.high) for x in window)
            min_low = min(float(x.low) for x in window)
            metrics.append(
                HorizonEconomics(
                    horizon_minutes=horizon,
                    exit_timestamp=_minute_key(last.timestamp).isoformat(),
                    exit_close=float(last.close),
                    return_pct=_pct(entry, float(last.close)),
                    mfe_pct=_pct(entry, max_high),
                    mae_pct=_pct(entry, min_low),
                )
            )

        results.append(
            CandidateEconomics(
                strike=candidate.strike,
                side=candidate.side,
                instrument_key=candidate.instrument_key,
                relation_to_atm=candidate.relation_to_atm,
                expiry=candidate.expiry,
                status="AVAILABLE",
                entry_timestamp=boundary.isoformat(),
                entry_open=entry,
                horizons=tuple(metrics),
                issue=None,
            )
        )

    status = "AVAILABLE" if not overall_issues else "INCOMPLETE"
    return CandidateEconomicsSet(
        model=MODEL,
        status=status,
        signal_bar=bar_ts.isoformat(),
        signal_boundary=boundary.isoformat(),
        entry_semantics=ENTRY_SEMANTICS,
        selection_policy=SELECTION_POLICY,
        selected_instrument_key=None,
        horizons_minutes=horizons,
        candidates=tuple(results),
        issue=";".join(overall_issues) if overall_issues else None,
    )
