from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable

from .domain import IST
from .hilega_milega_pe_option_candidate_v1 import PEOptionCandidate as OptionCandidate, PEOptionCandidateSet as OptionCandidateSet
from .live_option_minute_source_v1 import validate_option_minute

MODEL = "HILEGA_MILEGA_PE_OPTION_SHADOW_LIFECYCLE_V1"
SELECTION_POLICY = "ALL_ATM_PLUS_MINUS_2_PE_SHADOW"
ENTRY_SEMANTICS = "EXACT_1M_OPEN_AT_SIGNAL_BOUNDARY"
EXIT_SEMANTICS = "EXACT_1M_OPEN_AT_CAUSAL_EXIT_BOUNDARY"
OBSERVATION_ONLY = True
EXECUTION_ENABLED = False
PAPER_ORDER_ENABLED = False


@dataclass(frozen=True)
class ShadowOptionLegSnapshot:
    strike: float
    side: str
    instrument_key: str
    relation_to_atm: int
    expiry: str
    entry_timestamp: str
    entry_open: float
    latest_completed_minute: str | None
    latest_close: float | None
    current_points: float | None
    current_return_pct: float | None
    mfe_points: float | None
    mfe_pct: float | None
    mae_points: float | None
    mae_pct: float | None
    exit_timestamp: str | None = None
    exit_open: float | None = None
    realized_points: float | None = None
    realized_return_pct: float | None = None


@dataclass(frozen=True)
class ShadowOptionLifecycleSnapshot:
    model: str
    status: str
    signal_bar: str
    signal_boundary: str
    signal_spot: float
    source: str | None
    expiry: str
    atm: float
    selection_policy: str
    shadow_selected_instrument_keys: tuple[str, ...]
    active: bool
    latest_completed_minute: str | None
    exit_reason: str | None
    legs: tuple[ShadowOptionLegSnapshot, ...]
    issue: str | None = None
    pending_exit_boundary: str | None = None

    def payload(self) -> dict:
        out = asdict(self)
        out["legs"] = [asdict(x) for x in self.legs]
        out["shadow_selected_instrument_keys"] = list(self.shadow_selected_instrument_keys)
        out.update({
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "order_created": False,
            "quantity": None,
        })
        return out


def _minute_key(value: datetime) -> datetime:
    return value.astimezone(IST).replace(second=0, microsecond=0)


def _pct(entry: float, value: float) -> float:
    return ((value / entry) - 1.0) * 100.0


class HilegaMilegaPEOptionShadowLifecycleV1:
    """Track all exact ATM±2 PE contracts for one Hilega signal in shadow only.

    This is intentionally not an execution engine and not a strike optimizer.
    All five exact PE contracts are shadow-selected together so their live
    economics can be observed without hindsight. Entry uses the exact 1m OPEN
    at the causal signal boundary (5m label + 5 minutes). Updates consume only
    fully completed option minutes. Exit uses the exact option-minute OPEN at
    the causal strategy-exit boundary. No nearest-minute/strike fallback,
    interpolation, synthetic premium, quantity or order creation is allowed.
    """

    def __init__(self) -> None:
        self._snapshot: ShadowOptionLifecycleSnapshot | None = None
        self._candidate_set: OptionCandidateSet | None = None

    @property
    def snapshot(self) -> ShadowOptionLifecycleSnapshot | None:
        return self._snapshot

    @property
    def active(self) -> bool:
        # Strategy-exited observations MUST NOT remain economically active.
        return bool(self._snapshot and self._snapshot.status == "ACTIVE" and self._snapshot.active)

    @property
    def pending_exit(self) -> bool:
        return bool(self._snapshot and self._snapshot.status == "PENDING_EXACT_EXIT")

    @classmethod
    def from_audited_active_snapshot(cls, payload: dict) -> "HilegaMilegaPEOptionShadowLifecycleV1":
        """Restore ONLY an audited complete five-leg identity, never invent an entry.

        The frozen audited instrument keys and entry premiums are reused; live
        contract-master changes cannot silently substitute another strike/key.
        """
        if payload.get("status") not in ("ACTIVE", "PENDING_EXACT_EXIT"):
            raise ValueError("RESTORE_REQUIRES_AUDITED_ACTIVE_OR_PENDING_SNAPSHOT")
        legs = tuple(ShadowOptionLegSnapshot(**{
            k: row.get(k) for k in ShadowOptionLegSnapshot.__dataclass_fields__
        }) for row in payload.get("legs", []))
        if sorted(leg.relation_to_atm for leg in legs) != [-2, -1, 0, 1, 2]:
            raise ValueError("RESTORE_REQUIRES_EXACT_FIVE_AUDITED_LEGS")
        if any(not leg.instrument_key or leg.entry_open is None or leg.entry_open <= 0 for leg in legs):
            raise ValueError("RESTORE_INVALID_AUDITED_ENTRY")
        if payload.get("selection_policy") != SELECTION_POLICY:
            raise ValueError("RESTORE_WRONG_SELECTION_POLICY")
        candidate_set = OptionCandidateSet(
            model="HILEGA_MILEGA_PE_OPTION_CANDIDATE_V1", status="AVAILABLE",
            expiry=payload["expiry"], signal_spot=payload["signal_spot"],
            atm=payload["atm"], strike_step=50.0, wings=2, side="PE",
            selection_policy="UNDECIDED_CANDIDATE_SET_ONLY", selected_instrument_key=None,
            candidates=tuple(OptionCandidate(leg.strike, leg.side, leg.instrument_key,
                leg.relation_to_atm, leg.expiry) for leg in legs),
        )
        obj = cls()
        obj._candidate_set = candidate_set
        obj._snapshot = ShadowOptionLifecycleSnapshot(
            model=MODEL, status=payload["status"],
            signal_bar=payload["signal_bar"], signal_boundary=payload["signal_boundary"],
            signal_spot=payload["signal_spot"], source=payload.get("source"),
            expiry=payload["expiry"], atm=payload["atm"],
            selection_policy=SELECTION_POLICY,
            shadow_selected_instrument_keys=tuple(leg.instrument_key for leg in legs),
            active=payload["status"] == "ACTIVE",
            latest_completed_minute=payload.get("latest_completed_minute"),
            exit_reason=payload.get("exit_reason"), legs=legs,
            issue=payload.get("issue"),
            pending_exit_boundary=payload.get("pending_exit_boundary"),
        )
        if obj.pending_exit and not obj._snapshot.pending_exit_boundary:
            raise ValueError("RESTORE_PENDING_EXIT_BOUNDARY_REQUIRED")
        return obj

    @staticmethod
    def _rows_by_ts(rows: Iterable) -> tuple[dict[datetime, object], bool]:
        by_ts: dict[datetime, object] = {}
        duplicate = False
        for row in rows:
            ts = _minute_key(row.timestamp)
            if ts in by_ts:
                duplicate = True
            by_ts[ts] = row
        return by_ts, duplicate

    def start(
        self,
        *,
        signal_bar_ts: datetime,
        signal_spot: float,
        source: str | None,
        candidate_set: OptionCandidateSet,
        option_minutes: Callable[[str], Iterable],
    ) -> ShadowOptionLifecycleSnapshot:
        bar_ts = _minute_key(signal_bar_ts)
        boundary = bar_ts + timedelta(minutes=5)

        if candidate_set.status != "AVAILABLE":
            self._snapshot = ShadowOptionLifecycleSnapshot(
                model=MODEL,
                status="BLOCKED",
                signal_bar=bar_ts.isoformat(),
                signal_boundary=boundary.isoformat(),
                signal_spot=float(signal_spot),
                source=source,
                expiry=candidate_set.expiry,
                atm=float(candidate_set.atm),
                selection_policy=SELECTION_POLICY,
                shadow_selected_instrument_keys=(),
                active=False,
                latest_completed_minute=None,
                exit_reason=None,
                legs=(),
                issue=candidate_set.issue or "CANDIDATE_SET_NOT_AVAILABLE",
            )
            self._candidate_set = None
            return self._snapshot

        # Current PE shadow policy requires the full ATM±2 universe.
        relations = tuple(sorted(x.relation_to_atm for x in candidate_set.candidates))
        if relations != (-2, -1, 0, 1, 2):
            self._snapshot = ShadowOptionLifecycleSnapshot(
                model=MODEL,
                status="BLOCKED",
                signal_bar=bar_ts.isoformat(),
                signal_boundary=boundary.isoformat(),
                signal_spot=float(signal_spot),
                source=source,
                expiry=candidate_set.expiry,
                atm=float(candidate_set.atm),
                selection_policy=SELECTION_POLICY,
                shadow_selected_instrument_keys=(),
                active=False,
                latest_completed_minute=None,
                exit_reason=None,
                legs=(),
                issue=f"ATM_PLUS_MINUS_2_SET_REQUIRED:{relations}",
            )
            self._candidate_set = None
            return self._snapshot

        legs: list[ShadowOptionLegSnapshot] = []
        issues: list[str] = []
        for candidate in candidate_set.candidates:
            by_ts, duplicate = self._rows_by_ts(option_minutes(candidate.instrument_key))
            if duplicate:
                issues.append(f"{candidate.instrument_key}:DUPLICATE_MINUTE")
                continue
            row = by_ts.get(boundary)
            if row is None:
                issues.append(f"{candidate.instrument_key}:MISSING_ENTRY_MINUTE:{boundary.isoformat()}")
                continue
            health = validate_option_minute(
                row,
                expected_instrument_key=candidate.instrument_key,
                previous_timestamp=None,
            )
            if not health.allowed:
                issues.append(f"{candidate.instrument_key}:{health.reason or health.state}")
                continue
            entry_open = float(row.open)
            if entry_open <= 0:
                issues.append(f"{candidate.instrument_key}:NONPOSITIVE_ENTRY_OPEN")
                continue
            legs.append(
                ShadowOptionLegSnapshot(
                    strike=candidate.strike,
                    side=candidate.side,
                    instrument_key=candidate.instrument_key,
                    relation_to_atm=candidate.relation_to_atm,
                    expiry=candidate.expiry,
                    entry_timestamp=boundary.isoformat(),
                    entry_open=entry_open,
                    latest_completed_minute=None,
                    latest_close=None,
                    current_points=None,
                    current_return_pct=None,
                    mfe_points=None,
                    mfe_pct=None,
                    mae_points=None,
                    mae_pct=None,
                )
            )

        if issues or len(legs) != 5:
            self._snapshot = ShadowOptionLifecycleSnapshot(
                model=MODEL,
                status="INCOMPLETE",
                signal_bar=bar_ts.isoformat(),
                signal_boundary=boundary.isoformat(),
                signal_spot=float(signal_spot),
                source=source,
                expiry=candidate_set.expiry,
                atm=float(candidate_set.atm),
                selection_policy=SELECTION_POLICY,
                shadow_selected_instrument_keys=tuple(x.instrument_key for x in legs),
                active=False,
                latest_completed_minute=None,
                exit_reason=None,
                legs=tuple(legs),
                issue=";".join(issues) if issues else "INCOMPLETE_ATM_PLUS_MINUS_2_ENTRY",
            )
            # Exact candidate identity is frozen; retry only this original
            # boundary when the missing minute has become completed data.
            self._candidate_set = candidate_set
            return self._snapshot

        self._candidate_set = candidate_set
        self._snapshot = ShadowOptionLifecycleSnapshot(
            model=MODEL,
            status="ACTIVE",
            signal_bar=bar_ts.isoformat(),
            signal_boundary=boundary.isoformat(),
            signal_spot=float(signal_spot),
            source=source,
            expiry=candidate_set.expiry,
            atm=float(candidate_set.atm),
            selection_policy=SELECTION_POLICY,
            shadow_selected_instrument_keys=tuple(x.instrument_key for x in legs),
            active=True,
            latest_completed_minute=None,
            exit_reason=None,
            legs=tuple(legs),
            issue=None,
        )
        return self._snapshot

    def update(
        self,
        *,
        through_completed_minute: datetime,
        option_minutes: Callable[[str], Iterable],
    ) -> ShadowOptionLifecycleSnapshot | None:
        if not self.active or self._snapshot is None or self._candidate_set is None:
            return self._snapshot

        through = _minute_key(through_completed_minute)
        boundary = datetime.fromisoformat(self._snapshot.signal_boundary).astimezone(IST)
        if through < boundary:
            return self._snapshot

        expected = []
        ts = boundary
        while ts <= through:
            expected.append(ts)
            ts += timedelta(minutes=1)

        new_legs: list[ShadowOptionLegSnapshot] = []
        issues: list[str] = []
        leg_by_key = {x.instrument_key: x for x in self._snapshot.legs}
        for candidate in self._candidate_set.candidates:
            prior_leg = leg_by_key[candidate.instrument_key]
            by_ts, duplicate = self._rows_by_ts(option_minutes(candidate.instrument_key))
            if duplicate:
                issues.append(f"{candidate.instrument_key}:DUPLICATE_MINUTE")
                continue

            path = []
            previous = None
            for minute in expected:
                row = by_ts.get(minute)
                if row is None:
                    issues.append(f"{candidate.instrument_key}:MISSING_EXACT_MINUTE:{minute.isoformat()}")
                    continue
                health = validate_option_minute(
                    row,
                    expected_instrument_key=candidate.instrument_key,
                    previous_timestamp=previous,
                )
                if not health.allowed:
                    issues.append(f"{candidate.instrument_key}:{minute.isoformat()}:{health.reason or health.state}")
                    continue
                path.append(row)
                previous = row.timestamp

            if len(path) != len(expected):
                continue
            entry = prior_leg.entry_open
            latest = path[-1]
            max_high = max(float(x.high) for x in path)
            min_low = min(float(x.low) for x in path)
            latest_close = float(latest.close)
            new_legs.append(
                ShadowOptionLegSnapshot(
                    strike=prior_leg.strike,
                    side=prior_leg.side,
                    instrument_key=prior_leg.instrument_key,
                    relation_to_atm=prior_leg.relation_to_atm,
                    expiry=prior_leg.expiry,
                    entry_timestamp=prior_leg.entry_timestamp,
                    entry_open=entry,
                    latest_completed_minute=_minute_key(latest.timestamp).isoformat(),
                    latest_close=latest_close,
                    current_points=latest_close - entry,
                    current_return_pct=_pct(entry, latest_close),
                    mfe_points=max_high - entry,
                    mfe_pct=_pct(entry, max_high),
                    mae_points=min_low - entry,
                    mae_pct=_pct(entry, min_low),
                )
            )

        if issues or len(new_legs) != 5:
            return ShadowOptionLifecycleSnapshot(
                model=MODEL,
                status="INCOMPLETE_UPDATE",
                signal_bar=self._snapshot.signal_bar,
                signal_boundary=self._snapshot.signal_boundary,
                signal_spot=self._snapshot.signal_spot,
                source=self._snapshot.source,
                expiry=self._snapshot.expiry,
                atm=self._snapshot.atm,
                selection_policy=SELECTION_POLICY,
                shadow_selected_instrument_keys=self._snapshot.shadow_selected_instrument_keys,
                active=True,
                latest_completed_minute=self._snapshot.latest_completed_minute,
                exit_reason=None,
                legs=self._snapshot.legs,
                issue=";".join(issues) if issues else "INCOMPLETE_EXACT_MINUTE_PATH",
            )

        self._snapshot = ShadowOptionLifecycleSnapshot(
            model=MODEL,
            status="ACTIVE",
            signal_bar=self._snapshot.signal_bar,
            signal_boundary=self._snapshot.signal_boundary,
            signal_spot=self._snapshot.signal_spot,
            source=self._snapshot.source,
            expiry=self._snapshot.expiry,
            atm=self._snapshot.atm,
            selection_policy=SELECTION_POLICY,
            shadow_selected_instrument_keys=self._snapshot.shadow_selected_instrument_keys,
            active=True,
            latest_completed_minute=through.isoformat(),
            exit_reason=None,
            legs=tuple(new_legs),
            issue=None,
        )
        return self._snapshot

    def close(
        self,
        *,
        exit_boundary: datetime,
        exit_reason: str,
        option_minutes: Callable[[str], Iterable],
    ) -> ShadowOptionLifecycleSnapshot | None:
        if self.pending_exit:
            if _minute_key(exit_boundary).isoformat() != self._snapshot.pending_exit_boundary or exit_reason != self._snapshot.exit_reason:
                raise ValueError("PENDING_EXACT_EXIT_IS_IMMUTABLE")
        elif not self.active:
            return self._snapshot
        if self._snapshot is None or self._candidate_set is None:
            return self._snapshot

        boundary = _minute_key(exit_boundary)
        entry_boundary = datetime.fromisoformat(self._snapshot.signal_boundary)
        if boundary <= entry_boundary:
            raise ValueError("EXIT_BOUNDARY_MUST_FOLLOW_ENTRY_BOUNDARY")
        leg_by_key = {x.instrument_key: x for x in self._snapshot.legs}
        new_legs: list[ShadowOptionLegSnapshot] = []
        issues: list[str] = []
        for candidate in self._candidate_set.candidates:
            prior_leg = leg_by_key[candidate.instrument_key]
            by_ts, duplicate = self._rows_by_ts(option_minutes(candidate.instrument_key))
            if duplicate:
                issues.append(f"{candidate.instrument_key}:DUPLICATE_MINUTE")
                continue
            row = by_ts.get(boundary)
            if row is None:
                issues.append(f"{candidate.instrument_key}:MISSING_EXIT_MINUTE:{boundary.isoformat()}")
                continue
            health = validate_option_minute(
                row,
                expected_instrument_key=candidate.instrument_key,
                previous_timestamp=None,
            )
            if not health.allowed:
                issues.append(f"{candidate.instrument_key}:{health.reason or health.state}")
                continue
            exit_open = float(row.open)
            new_legs.append(
                ShadowOptionLegSnapshot(
                    **{
                        **asdict(prior_leg),
                        "exit_timestamp": boundary.isoformat(),
                        "exit_open": exit_open,
                        "realized_points": exit_open - prior_leg.entry_open,
                        "realized_return_pct": _pct(prior_leg.entry_open, exit_open),
                    }
                )
            )

        if issues or len(new_legs) != 5:
            self._snapshot = ShadowOptionLifecycleSnapshot(
                model=MODEL,
                status="PENDING_EXACT_EXIT",
                signal_bar=self._snapshot.signal_bar,
                signal_boundary=self._snapshot.signal_boundary,
                signal_spot=self._snapshot.signal_spot,
                source=self._snapshot.source,
                expiry=self._snapshot.expiry,
                atm=self._snapshot.atm,
                selection_policy=SELECTION_POLICY,
                shadow_selected_instrument_keys=self._snapshot.shadow_selected_instrument_keys,
                active=False,
                latest_completed_minute=self._snapshot.latest_completed_minute,
                exit_reason=exit_reason,
                legs=self._snapshot.legs,
                issue=";".join(issues) if issues else "INCOMPLETE_EXACT_EXIT",
                pending_exit_boundary=boundary.isoformat(),
            )
            return self._snapshot

        self._snapshot = ShadowOptionLifecycleSnapshot(
            model=MODEL,
            status="CLOSED",
            signal_bar=self._snapshot.signal_bar,
            signal_boundary=self._snapshot.signal_boundary,
            signal_spot=self._snapshot.signal_spot,
            source=self._snapshot.source,
            expiry=self._snapshot.expiry,
            atm=self._snapshot.atm,
            selection_policy=SELECTION_POLICY,
            shadow_selected_instrument_keys=self._snapshot.shadow_selected_instrument_keys,
            active=False,
            latest_completed_minute=self._snapshot.latest_completed_minute,
            exit_reason=exit_reason,
            legs=tuple(new_legs),
            issue=None,
        )
        return self._snapshot

    def retry_pending_exit(self, *, option_minutes: Callable[[str], Iterable]) -> ShadowOptionLifecycleSnapshot | None:
        if not self.pending_exit or self._snapshot is None:
            return self._snapshot
        return self.close(
            exit_boundary=datetime.fromisoformat(self._snapshot.pending_exit_boundary),
            exit_reason=self._snapshot.exit_reason,
            option_minutes=option_minutes,
        )

    def retry_missing_entry(self, *, option_minutes: Callable[[str], Iterable]) -> ShadowOptionLifecycleSnapshot:
        if self._snapshot is None or self._snapshot.status != "INCOMPLETE" or self._candidate_set is None:
            raise ValueError("NO_RETRIABLE_EXACT_ENTRY")
        old = self._snapshot
        return self.start(
            signal_bar_ts=datetime.fromisoformat(old.signal_bar),
            signal_spot=old.signal_spot,
            source=old.source,
            candidate_set=self._candidate_set,
            option_minutes=option_minutes,
        )
