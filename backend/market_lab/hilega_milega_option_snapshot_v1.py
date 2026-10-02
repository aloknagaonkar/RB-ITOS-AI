from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable

from .domain import IST
from .hilega_milega_option_candidate_v1 import OptionCandidateSet
from .live_option_minute_source_v1 import validate_option_minute

MODEL = "HILEGA_MILEGA_OPTION_CANDIDATE_MARKET_SNAPSHOT_V1"
SNAPSHOT_SEMANTICS = "SIGNAL_BOUNDARY_LAST_COMPLETED_1M"
SELECTION_POLICY = "UNDECIDED_CANDIDATE_SET_ONLY"


@dataclass(frozen=True)
class CandidateMinuteSnapshot:
    strike: float
    side: str
    instrument_key: str
    relation_to_atm: int
    expiry: str
    minute_timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None


@dataclass(frozen=True)
class CandidateMarketSnapshotSet:
    model: str
    status: str
    signal_bar: str
    signal_boundary: str
    expected_option_minute: str
    snapshot_semantics: str
    selection_policy: str
    selected_instrument_key: str | None
    snapshots: tuple[CandidateMinuteSnapshot, ...]
    issue: str | None = None

    def payload(self) -> dict:
        out = asdict(self)
        out["snapshots"] = [asdict(x) for x in self.snapshots]
        return out


def observe_exact_candidate_market_snapshot(
    *,
    signal_bar_ts: datetime,
    candidate_set: OptionCandidateSet,
    option_minutes: Callable[[str], Iterable],
) -> CandidateMarketSnapshotSet:
    """Observe exact candidate premiums at the causal 5m signal boundary.

    A signal bar labelled HH:MM closes at HH:MM+5. Upstox 1m candles are
    start-labelled, so the last fully completed minute available at that
    decision boundary is HH:MM+4. No nearest-minute fallback is permitted.
    This is market observation only: no option is selected and no order is
    created.
    """
    bar_ts = signal_bar_ts.astimezone(IST)
    boundary = bar_ts + timedelta(minutes=5)
    expected = boundary - timedelta(minutes=1)

    if candidate_set.status != "AVAILABLE":
        return CandidateMarketSnapshotSet(
            model=MODEL,
            status="BLOCKED",
            signal_bar=bar_ts.isoformat(),
            signal_boundary=boundary.isoformat(),
            expected_option_minute=expected.isoformat(),
            snapshot_semantics=SNAPSHOT_SEMANTICS,
            selection_policy=SELECTION_POLICY,
            selected_instrument_key=None,
            snapshots=(),
            issue="CANDIDATE_SET_NOT_AVAILABLE",
        )

    snapshots: list[CandidateMinuteSnapshot] = []
    issues: list[str] = []
    for candidate in candidate_set.candidates:
        rows = list(option_minutes(candidate.instrument_key))
        matches = [
            row for row in rows
            if row.timestamp.astimezone(IST).replace(second=0, microsecond=0) == expected
        ]
        if len(matches) != 1:
            issues.append(f"{candidate.instrument_key}:EXACT_MINUTE_MATCH_COUNT={len(matches)}")
            continue
        row = matches[0]
        health = validate_option_minute(
            row,
            expected_instrument_key=candidate.instrument_key,
            previous_timestamp=None,
        )
        if not health.allowed:
            issues.append(f"{candidate.instrument_key}:{health.reason or health.state}")
            continue
        snapshots.append(
            CandidateMinuteSnapshot(
                strike=candidate.strike,
                side=candidate.side,
                instrument_key=candidate.instrument_key,
                relation_to_atm=candidate.relation_to_atm,
                expiry=candidate.expiry,
                minute_timestamp=expected.isoformat(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume) if row.volume is not None else None,
            )
        )

    if issues:
        return CandidateMarketSnapshotSet(
            model=MODEL,
            status="INCOMPLETE",
            signal_bar=bar_ts.isoformat(),
            signal_boundary=boundary.isoformat(),
            expected_option_minute=expected.isoformat(),
            snapshot_semantics=SNAPSHOT_SEMANTICS,
            selection_policy=SELECTION_POLICY,
            selected_instrument_key=None,
            snapshots=tuple(snapshots),
            issue=";".join(issues),
        )

    return CandidateMarketSnapshotSet(
        model=MODEL,
        status="AVAILABLE",
        signal_bar=bar_ts.isoformat(),
        signal_boundary=boundary.isoformat(),
        expected_option_minute=expected.isoformat(),
        snapshot_semantics=SNAPSHOT_SEMANTICS,
        selection_policy=SELECTION_POLICY,
        selected_instrument_key=None,
        snapshots=tuple(snapshots),
        issue=None,
    )
