"""Pure, fail-closed ranking of five frozen CE or PE contracts.

This module has no broker adapter. A policy must be approved from separate
research before a caller can use its selected contract for Sandbox execution.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

MODEL = "HILEGA_STRIKE_SELECTOR_V1"
ROLES = (-2, -1, 0, 1, 2)


@dataclass(frozen=True)
class StrikePolicy:
    version: str
    strategy_version: str
    approved: bool
    ranked_ce_roles: tuple[int, ...]
    ranked_pe_roles: tuple[int, ...]
    max_spread_pct: float
    min_bid_quantity: int
    min_ask_quantity: int
    min_volume: int
    max_signal_age_seconds: int
    max_quote_age_seconds: int
    max_one_lot_premium_rupees: float

    @classmethod
    def load(cls, path: str | Path, *, require_approval: bool = True) -> "StrikePolicy":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        raw["ranked_ce_roles"] = tuple(raw["ranked_ce_roles"])
        raw["ranked_pe_roles"] = tuple(raw["ranked_pe_roles"])
        policy = cls(**raw)
        if not isinstance(policy.version, str) or not policy.version.strip() or not isinstance(policy.strategy_version, str) or not policy.strategy_version.strip() or type(policy.approved) is not bool or (require_approval and policy.approved is not True):
            raise ValueError("STRIKE_POLICY_NOT_APPROVED")
        if (any(type(r) is not int for r in policy.ranked_ce_roles + policy.ranked_pe_roles)
                or len(policy.ranked_ce_roles) != len(ROLES) or set(policy.ranked_ce_roles) != set(ROLES)
                or len(policy.ranked_pe_roles) != len(ROLES) or set(policy.ranked_pe_roles) != set(ROLES)):
            raise ValueError("STRIKE_POLICY_MUST_RANK_FIVE_ROLES")
        limits = (
                policy.max_spread_pct, policy.min_bid_quantity, policy.min_ask_quantity,
                policy.max_signal_age_seconds, policy.max_quote_age_seconds,
                policy.max_one_lot_premium_rupees)
        if any(isinstance(x, bool) or not isinstance(x, (int, float))
               or not math.isfinite(x) or x <= 0 for x in limits):
            raise ValueError("INVALID_STRIKE_POLICY_LIMIT")
        if isinstance(policy.min_volume, bool) or not isinstance(policy.min_volume, int) or policy.min_volume < 0:
            raise ValueError("INVALID_STRIKE_POLICY_VOLUME")
        return policy


def _time(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return stamp


def rank_strikes(*, policy: StrikePolicy, strategy_version: str, direction: str,
                 signal_time: str, evaluated_at: str,
                 candidates: Iterable[dict[str, Any]], lots: int = 1,
                 observation_only: bool = False) -> dict[str, Any]:
    """Return a frozen decision. All quote values must be captured after the signal."""
    if (not policy.approved and not observation_only) or strategy_version != policy.strategy_version:
        raise ValueError("STRIKE_POLICY_VERSION_NOT_APPROVED_FOR_STRATEGY")
    if direction not in {"BULLISH", "BEARISH"}:
        raise ValueError("UNKNOWN_DIRECTION")
    if type(lots) is not int or lots != 1:
        raise ValueError("RANKED_MODE_REQUIRES_EXACTLY_ONE_LOT")
    now, signal = _time(evaluated_at), _time(signal_time)
    age = (now - signal).total_seconds()
    if age < 0 or age > policy.max_signal_age_seconds:
        return dict(model=MODEL, policy_version=policy.version, status="NO_TRADE",
                    strategy_version=strategy_version, signal_time=signal_time,
                    evaluated_at=evaluated_at, direction=direction,
                    reason="SIGNAL_STALE_OR_FUTURE", selected=None,
                    candidates=[dict(r, eligible=False, rejection_reasons=["SIGNAL_STALE_OR_FUTURE"]) for r in candidates])
    rows = [dict(row) for row in candidates]
    side = "CE" if direction == "BULLISH" else "PE"
    if len(rows) != 5 or {r.get("role") for r in rows} != set(ROLES):
        raise ValueError("EXACT_FIVE_CANDIDATES_REQUIRED")
    if {r.get("option_type") for r in rows} != {side} or len({r.get("expiry") for r in rows}) != 1:
        raise ValueError("CANDIDATE_SIDE_OR_EXPIRY_MISMATCH")
    if not rows[0].get("expiry") or any(not r.get("instrument_key") for r in rows):
        raise ValueError("CANDIDATE_IDENTITY_MISSING")
    if len({r.get("instrument_key") for r in rows}) != 5:
        raise ValueError("DUPLICATE_CANDIDATE_INSTRUMENT")
    preference = policy.ranked_ce_roles if side == "CE" else policy.ranked_pe_roles
    order = {role: n + 1 for n, role in enumerate(preference)}
    ranked = []
    for row in rows:
        issues = []
        try:
            bid, ask = float(row["bid_price"]), float(row["ask_price"])
            for field in ("bid_quantity", "ask_quantity", "volume", "lot_size"):
                if isinstance(row[field], bool) or float(row[field]) != int(row[field]):
                    raise ValueError("INTEGER_QUOTE_QUANTITY_REQUIRED")
            bid_qty, ask_qty = int(row["bid_quantity"]), int(row["ask_quantity"])
            volume, lot = int(row["volume"]), int(row["lot_size"])
            quote_time = _time(str(row["quote_time"]))
            quote_age = (now - quote_time).total_seconds()
            if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask <= bid:
                issues.append("INVALID_BID_ASK")
            if quote_time < signal or quote_age < 0 or quote_age > policy.max_quote_age_seconds:
                issues.append("STALE_OR_FUTURE_QUOTE")
            if bid_qty < max(lot, policy.min_bid_quantity) or ask_qty < max(lot, policy.min_ask_quantity):
                issues.append("INSUFFICIENT_TOP_OF_BOOK_DEPTH")
            if bid_qty < 0 or ask_qty < 0 or volume < policy.min_volume:
                issues.append("LOW_VOLUME")
            if lot <= 0 or ask * lot > policy.max_one_lot_premium_rupees:
                issues.append("PREMIUM_BUDGET_EXCEEDED")
            spread_pct = 100 * (ask - bid) / ask if ask > 0 else None
            if spread_pct is None or spread_pct > policy.max_spread_pct:
                issues.append("SPREAD_TOO_WIDE")
        except (KeyError, TypeError, ValueError, OverflowError):
            issues.append("QUOTE_EVIDENCE_INCOMPLETE")
            spread_pct = None
        ranked.append({**row, "rank": order[row["role"]], "spread_pct": spread_pct,
                       "eligible": not issues, "rejection_reasons": issues})
    ranked.sort(key=lambda row: row["rank"])
    selected = next((row for row in ranked if row["eligible"]), None)
    return dict(model=MODEL, policy_version=policy.version,
                observation_only=observation_only, execution_approved=policy.approved and not observation_only,
                policy=asdict(policy), strategy_version=strategy_version,
                signal_time=signal_time, evaluated_at=evaluated_at,
                direction=direction, status="SELECTED" if selected else "NO_TRADE",
                reason="RANKED_ELIGIBLE_CONTRACT" if selected else "NO_ELIGIBLE_CONTRACT",
                selected=dict(selected) if selected else None, candidates=ranked)
