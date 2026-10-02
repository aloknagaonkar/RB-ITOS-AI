from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

MODEL = "HILEGA_MILEGA_OPTION_CANDIDATE_V1"
SIDE = "CE"
SELECTION_POLICY = "UNDECIDED_CANDIDATE_SET_ONLY"


class OptionCandidateError(RuntimeError):
    pass


@dataclass(frozen=True)
class OptionCandidate:
    strike: float
    side: str
    instrument_key: str
    relation_to_atm: int
    expiry: str


@dataclass(frozen=True)
class OptionCandidateSet:
    model: str
    status: str
    expiry: str
    signal_spot: float
    atm: float
    strike_step: float
    wings: int
    side: str
    selection_policy: str
    selected_instrument_key: str | None
    candidates: tuple[OptionCandidate, ...]
    issue: str | None = None

    def payload(self) -> dict:
        out = asdict(self)
        out["candidates"] = [asdict(x) for x in self.candidates]
        return out


def round_half_up_to_step(value: float, step: float) -> float:
    if value <= 0 or step <= 0:
        raise OptionCandidateError("INVALID_SPOT_OR_STRIKE_STEP")
    q = (Decimal(str(value)) / Decimal(str(step))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(q * Decimal(str(step)))


def _normalize_contracts(rows: Iterable[dict], *, expiry: date) -> dict[tuple[float, str], str]:
    idx: dict[tuple[float, str], str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_expiry = row.get("expiry")
        if row_expiry not in (None, expiry.isoformat()):
            continue
        side = str(row.get("instrument_type") or row.get("option_type") or "").upper()
        side = {"CALL": "CE", "PUT": "PE"}.get(side, side)
        if side not in {"CE", "PE"}:
            continue
        try:
            strike = float(row["strike_price"])
        except Exception:
            continue
        key = str(row.get("instrument_key") or "").strip()
        if not key:
            continue
        ident = (strike, side)
        if ident in idx and idx[ident] != key:
            raise OptionCandidateError("DUPLICATE_OPTION_CONTRACT_IDENTITY")
        idx[ident] = key
    return idx


def build_bullish_ce_candidate_set(
    *,
    signal_spot: float,
    expiry: date,
    contracts: Iterable[dict],
    strike_step: float = 50.0,
    wings: int = 2,
) -> OptionCandidateSet:
    """Build an exact CE candidate set around signal-time ATM.

    This module deliberately does NOT choose one contract. It is the option
    selection foundation only. There is no nearest-contract fallback, premium
    targeting, interpolation, synthetic contract or order creation here.
    """
    if wings < 0:
        raise OptionCandidateError("INVALID_WINGS")
    atm = round_half_up_to_step(signal_spot, strike_step)
    idx = _normalize_contracts(contracts, expiry=expiry)
    candidates: list[OptionCandidate] = []
    missing: list[str] = []
    for offset in range(-wings, wings + 1):
        strike = float(atm + offset * strike_step)
        key = idx.get((strike, SIDE))
        if key is None:
            label = int(strike) if strike.is_integer() else strike
            missing.append(f"{label}_{SIDE}")
            continue
        candidates.append(
            OptionCandidate(
                strike=strike,
                side=SIDE,
                instrument_key=key,
                relation_to_atm=offset,
                expiry=expiry.isoformat(),
            )
        )
    if missing:
        return OptionCandidateSet(
            model=MODEL,
            status="INCOMPLETE",
            expiry=expiry.isoformat(),
            signal_spot=float(signal_spot),
            atm=atm,
            strike_step=float(strike_step),
            wings=int(wings),
            side=SIDE,
            selection_policy=SELECTION_POLICY,
            selected_instrument_key=None,
            candidates=tuple(candidates),
            issue="EXACT_CONTRACTS_MISSING:" + ",".join(missing),
        )
    return OptionCandidateSet(
        model=MODEL,
        status="AVAILABLE",
        expiry=expiry.isoformat(),
        signal_spot=float(signal_spot),
        atm=atm,
        strike_step=float(strike_step),
        wings=int(wings),
        side=SIDE,
        selection_policy=SELECTION_POLICY,
        selected_instrument_key=None,
        candidates=tuple(candidates),
        issue=None,
    )
