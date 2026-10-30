from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

MODEL = "HILEGA_MILEGA_PE_OPTION_CANDIDATE_V1"
SIDE = "PE"
SELECTION_POLICY = "UNDECIDED_CANDIDATE_SET_ONLY"


class PEOptionCandidateError(RuntimeError):
    pass


@dataclass(frozen=True)
class PEOptionCandidate:
    strike: float
    side: str
    instrument_key: str
    relation_to_atm: int
    expiry: str


@dataclass(frozen=True)
class PEOptionCandidateSet:
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
    candidates: tuple[PEOptionCandidate, ...]
    issue: str | None = None

    def payload(self) -> dict:
        out = asdict(self)
        out["candidates"] = [asdict(x) for x in self.candidates]
        return out


def round_half_up_to_step(value: float, step: float) -> float:
    if value <= 0 or step <= 0:
        raise PEOptionCandidateError("INVALID_SPOT_OR_STRIKE_STEP")
    q = (Decimal(str(value)) / Decimal(str(step))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return float(q * Decimal(str(step)))


def _normalize_contracts(rows: Iterable[dict], *, expiry: date) -> dict[tuple[float, str], str]:
    idx: dict[tuple[float, str], str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_expiry = row.get("expiry")
        if row_expiry not in (None, expiry.isoformat()):
            continue
        side = str(row.get("instrument_type") or row.get("option_type") or row.get("side") or "").upper()
        side = {"CALL": "CE", "PUT": "PE"}.get(side, side)
        if side not in {"CE", "PE"}:
            continue
        try:
            strike = float(row.get("strike_price", row.get("strike")))
        except Exception:
            continue
        key = str(row.get("instrument_key") or "").strip()
        if not key:
            continue
        ident = (strike, side)
        if ident in idx and idx[ident] != key:
            raise PEOptionCandidateError("DUPLICATE_OPTION_CONTRACT_IDENTITY")
        idx[ident] = key
    return idx


def build_bearish_pe_candidate_set(
    *,
    signal_spot: float,
    expiry: date,
    contracts: Iterable[dict],
    strike_step: float = 50.0,
    wings: int = 2,
) -> PEOptionCandidateSet:
    """Build exact ATM±2 PE candidates for a bearish Hilega signal.

    No single PE is selected. No nearest strike, interpolation, premium targeting,
    quantity sizing, paper order, or real order exists in this module.
    """
    if wings < 0:
        raise PEOptionCandidateError("INVALID_WINGS")
    atm = round_half_up_to_step(signal_spot, strike_step)
    idx = _normalize_contracts(contracts, expiry=expiry)
    candidates: list[PEOptionCandidate] = []
    missing: list[str] = []
    for offset in range(-wings, wings + 1):
        strike = float(atm + offset * strike_step)
        key = idx.get((strike, SIDE))
        if key is None:
            label = int(strike) if strike.is_integer() else strike
            missing.append(f"{label}_{SIDE}")
            continue
        candidates.append(
            PEOptionCandidate(
                strike=strike,
                side=SIDE,
                instrument_key=key,
                relation_to_atm=offset,
                expiry=expiry.isoformat(),
            )
        )

    status = "AVAILABLE" if not missing else "INCOMPLETE"
    return PEOptionCandidateSet(
        model=MODEL,
        status=status,
        expiry=expiry.isoformat(),
        signal_spot=float(signal_spot),
        atm=atm,
        strike_step=float(strike_step),
        wings=int(wings),
        side=SIDE,
        selection_policy=SELECTION_POLICY,
        selected_instrument_key=None,
        candidates=tuple(candidates),
        issue=None if not missing else "EXACT_CONTRACTS_MISSING:" + ",".join(missing),
    )
