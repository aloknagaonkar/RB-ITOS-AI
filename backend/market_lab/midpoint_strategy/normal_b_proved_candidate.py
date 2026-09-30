"""Observation-only NORMAL_B_PROVED three-tier exit candidate.

Consumes completed, contiguous one-minute bars and never sends orders. Floors
are checked against observed closes. The +50 target uses an explicit research
assumption of an exact fill on intrabar touch; minute OHLC cannot prove time.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite


@dataclass(frozen=True)
class Policy:
    primary_target_points: float = 50.0
    tier2_mfe_points: float = 30.0
    tier2_floor_points: float = 15.0
    tier3_mfe_points: float = 45.0
    tier3_closed_profit_offset: float = 10.0
    inactivity_minutes: int = 30

    def __post_init__(self):
        values = (self.primary_target_points, self.tier2_mfe_points,
                  self.tier2_floor_points, self.tier3_mfe_points,
                  self.tier3_closed_profit_offset)
        if not all(isfinite(x) and x > 0 for x in values):
            raise ValueError("Policy point values must be finite and positive")
        if not self.tier2_floor_points < self.tier2_mfe_points < self.tier3_mfe_points:
            raise ValueError("Require tier2 floor < tier2 MFE < tier3 MFE")
        if self.primary_target_points <= self.tier3_mfe_points:
            raise ValueError("Primary target must exceed tier3 threshold")
        if self.inactivity_minutes <= 0:
            raise ValueError("Inactivity minutes must be positive")


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    high: float
    low: float
    close: float


class NormalBProvedCandidate:
    observation_only = True
    execution_enabled = False
    paper_order_enabled = False
    quantity = None

    def __init__(self, *, entry_timestamp, entry_price, direction, midpoint,
                 policy=None):
        if direction not in ("BULLISH", "BEARISH"):
            raise ValueError("Unsupported direction")
        if entry_timestamp.tzinfo is None or entry_timestamp.second or entry_timestamp.microsecond:
            raise ValueError("Entry must be a timezone-aware exact minute")
        if not all(isfinite(x) for x in (entry_price, midpoint)):
            raise ValueError("Entry and midpoint must be finite")
        self.entry_timestamp = entry_timestamp
        self.entry_price = entry_price
        self.direction = direction
        self.midpoint = midpoint
        self.policy = policy or Policy()
        self.state = "WAITING_CLASSIFICATION"
        self.last_timestamp = entry_timestamp
        self.proof_timestamp = None
        self.classified_at = None
        self.mfe = 0.0
        self.last_mfe_at = None
        self.floor = None
        self.highest_closed_profit_tier3 = None
        self.inactivity_exit_due = None
        self.exit = None

    def points(self, price):
        return (price - self.entry_price) * (1 if self.direction == "BULLISH" else -1)

    def _evidence(self, bar, close_points):
        return {"timestamp": bar.timestamp.isoformat(), "state": self.state,
                "mfe_points": self.mfe, "close_points": close_points,
                "floor_points": self.floor,
                "highest_closed_profit_tier3": self.highest_closed_profit_tier3,
                "inactivity_exit_due": self.inactivity_exit_due.isoformat() if self.inactivity_exit_due else None,
                "observation_only": True, "execution_enabled": False,
                "paper_order_enabled": False, "quantity": None,
                "order_sent": False}

    def _close(self, bar, reason, pnl_points, valuation_price, basis):
        self.state = "CLOSED"
        self.exit = {**self._evidence(bar, self.points(bar.close)),
                     "state": "CLOSED", "reason": reason,
                     "signal_timestamp": bar.timestamp.isoformat(),
                     "valuation_price": valuation_price,
                     "underlying_close": bar.close, "pnl_points": pnl_points,
                     "valuation_basis": basis,
                     "intrabar_fill_time_known": False}
        return self.exit

    def on_bar(self, bar, *, classifier_result=None):
        if self.exit is not None:
            raise ValueError("Closed candidate cannot reenter")
        t = bar.timestamp
        if t.tzinfo is None or t.second or t.microsecond:
            raise ValueError("Bar must be a timezone-aware exact minute")
        if t != self.last_timestamp + timedelta(minutes=1):
            raise ValueError("Missing, duplicate or out-of-order minute")
        if not all(isfinite(x) for x in (bar.high, bar.low, bar.close)) or not bar.low <= bar.close <= bar.high:
            raise ValueError("Invalid OHLC")
        target_time = self.proof_timestamp + timedelta(minutes=10) if self.proof_timestamp else None
        if classifier_result is not None and (t != target_time or self.classified_at is not None or classifier_result not in ("NORMAL_B", "RUNNER_STRENGTHENING")):
            raise ValueError("Classifier must occur once at exact proof +10")
        if target_time == t and classifier_result is None:
            raise ValueError("Exact classifier evidence required")

        self.last_timestamp = t
        close_points = self.points(bar.close)
        excursion = self.points(bar.high if self.direction == "BULLISH" else bar.low)
        if excursion > self.mfe:
            self.mfe = excursion
            self.last_mfe_at = t
            self.inactivity_exit_due = None
        if self.proof_timestamp is None and self.mfe >= 20:
            self.proof_timestamp = t
        if classifier_result is not None:
            self.classified_at = t
            self.state = "NORMAL_B_PROVED" if classifier_result == "NORMAL_B" else "RUNNER_BASELINE"
        evidence = self._evidence(bar, close_points)
        if self.state not in ("NORMAL_B_PROVED", "NORMAL_B_PROVED_TIER2", "NORMAL_B_PROVED_TIER3"):
            return evidence
        # This candle completed before the new classification state existed.
        if t == self.classified_at:
            return evidence

        p = self.policy
        if excursion >= p.primary_target_points:
            target_price = self.entry_price + (p.primary_target_points if self.direction == "BULLISH" else -p.primary_target_points)
            return self._close(bar, "PRIMARY_TARGET_TOUCH", p.primary_target_points,
                               target_price, "ASSUMED_EXACT_TARGET_FILL")
        invalid = bar.close < self.midpoint if self.direction == "BULLISH" else bar.close > self.midpoint
        if invalid:
            return self._close(bar, "MIDPOINT_INVALIDATION", close_points,
                               bar.close, "OBSERVED_CANDLE_CLOSE")
        if self.inactivity_exit_due is not None and t == self.inactivity_exit_due:
            return self._close(bar, "NO_NEW_MFE_TIME_EXIT", close_points,
                               bar.close, "OBSERVED_CANDLE_CLOSE")

        # Strict crossings: exactly +30 is Tier 1; exactly +45 is Tier 2.
        if self.mfe > p.tier3_mfe_points:
            self.state = "NORMAL_B_PROVED_TIER3"
            self.highest_closed_profit_tier3 = max(
                self.highest_closed_profit_tier3 if self.highest_closed_profit_tier3 is not None else close_points,
                close_points)
            ratchet = self.highest_closed_profit_tier3 - p.tier3_closed_profit_offset
            self.floor = max(self.floor if self.floor is not None else p.tier2_floor_points,
                             p.tier2_floor_points, ratchet)
        elif self.mfe > p.tier2_mfe_points:
            self.state = "NORMAL_B_PROVED_TIER2"
            self.floor = p.tier2_floor_points

        # "Falls below" is strict: equality does not exit.
        if self.floor is not None and close_points < self.floor:
            reason = "TIER3_RATCHET_FLOOR_CLOSE" if self.state == "NORMAL_B_PROVED_TIER3" else "TIER2_PROTECTIVE_FLOOR_CLOSE"
            return self._close(bar, reason, close_points, bar.close,
                               "OBSERVED_CANDLE_CLOSE")

        clock_start = max(self.classified_at, self.last_mfe_at or self.classified_at)
        if self.inactivity_exit_due is None and t - clock_start >= timedelta(minutes=p.inactivity_minutes):
            self.inactivity_exit_due = t + timedelta(minutes=1)
        return self._evidence(bar, close_points)
