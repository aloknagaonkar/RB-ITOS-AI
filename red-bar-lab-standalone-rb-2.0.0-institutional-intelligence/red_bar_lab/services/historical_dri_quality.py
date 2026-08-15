from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence
import pandas as pd


@dataclass(frozen=True)
class DRIQualityConfig:
    min_option_premium: float = 10.0
    max_strike_distance_points: float = 600.0
    max_strike_distance_pct: float = 0.025
    max_bid_ask_spread_pct: float = 30.0
    same_direction_cooldown_minutes: int = 20


@dataclass(frozen=True)
class CandidateQualityResult:
    accepted: tuple
    rejected_count: int
    reasons: tuple[str, ...]


def _number(value):
    try:
        if value is None:
            return None
        number = float(value)
        if pd.isna(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def _contract_value(candidate, *names):
    contract = getattr(candidate, "contract", None)
    for owner in (candidate, contract):
        if owner is None:
            continue
        for name in names:
            value = getattr(owner, name, None)
            number = _number(value)
            if number is not None:
                return number
    return None


def filter_tradable_candidates(
    candidates: Sequence,
    *,
    spot: float,
    config: DRIQualityConfig | None = None,
) -> CandidateQualityResult:
    cfg = config or DRIQualityConfig()
    accepted = []
    reasons: list[str] = []
    max_distance = max(
        float(cfg.max_strike_distance_points),
        abs(float(spot)) * float(cfg.max_strike_distance_pct),
    )

    for candidate in candidates:
        local_reasons: list[str] = []
        strike = _contract_value(candidate, "strike", "strike_price")
        premium = _number(getattr(candidate, "ltp", None))
        bid = _contract_value(candidate, "bid", "bid_price", "best_bid")
        ask = _contract_value(candidate, "ask", "ask_price", "best_ask")

        if strike is not None and abs(strike - float(spot)) > max_distance:
            local_reasons.append("EXTREME_OTM")
        if premium is None or premium < float(cfg.min_option_premium):
            local_reasons.append("PREMIUM_BELOW_MINIMUM")
        if (
            bid is not None
            and ask is not None
            and bid > 0
            and ask >= bid
        ):
            midpoint = (bid + ask) / 2.0
            spread_pct = ((ask - bid) / midpoint) * 100.0 if midpoint else 999.0
            if spread_pct > float(cfg.max_bid_ask_spread_pct):
                local_reasons.append("BID_ASK_SPREAD_TOO_WIDE")

        if local_reasons:
            reasons.extend(local_reasons)
            continue
        accepted.append(candidate)

    return CandidateQualityResult(
        accepted=tuple(accepted),
        rejected_count=max(0, len(candidates) - len(accepted)),
        reasons=tuple(sorted(set(reasons))),
    )


class SameDirectionReentryGate:
    def __init__(self, cooldown_minutes: int = 20) -> None:
        self.cooldown = pd.Timedelta(minutes=int(cooldown_minutes))
        self._last_taken: dict[str, pd.Timestamp] = {}

    def reason(self, direction: str, moment) -> str | None:
        direction = str(direction or "").upper()
        timestamp = pd.Timestamp(moment)
        previous = self._last_taken.get(direction)
        if previous is None:
            return None
        if timestamp - previous < self.cooldown:
            return "SAME_DIRECTION_REENTRY_COOLDOWN"
        return None

    def record_taken(self, direction: str, moment) -> None:
        self._last_taken[str(direction or "").upper()] = pd.Timestamp(moment)

    def reset_opposite(self, new_direction: str) -> None:
        direction = str(new_direction or "").upper()
        opposite = "BEARISH" if direction == "BULLISH" else "BULLISH"
        self._last_taken.pop(opposite, None)


def calibration_eligible(row) -> bool:
    if getattr(row, "outcome_result", None) in (None, "UNKNOWN"):
        return False
    blocker = str(getattr(row, "blocker", "") or "")
    attribution = str(getattr(row, "learning_attribution", "") or "")
    if "GAP" in blocker or "GAP" in attribution:
        return False
    if blocker in {
        "NO_RANK1_OPTION_AT_TIMESTAMP",
        "NO_TRADABLE_RANK1_OPTION",
    }:
        return False
    return True
