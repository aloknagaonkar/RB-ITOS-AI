from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class MarketSession:
    code: str
    label: str
    entry_allowed: bool


class MarketSessionManager:
    """Classify the Indian cash/index session without creating trading signals."""

    @staticmethod
    def classify(moment: datetime | None = None) -> MarketSession:
        now = moment or datetime.now(IST)
        if now.tzinfo is None:
            now = now.replace(tzinfo=IST)
        else:
            now = now.astimezone(IST)
        if now.weekday() >= 5:
            return MarketSession("CLOSED", "Weekend / Closed", False)
        t = now.time()
        if t < time(9, 15):
            return MarketSession("PRE_OPEN", "Pre-open", False)
        if t < time(9, 30):
            return MarketSession("OPENING", "Opening phase", True)
        if t < time(11, 30):
            return MarketSession("MORNING", "Morning trend", True)
        if t < time(13, 30):
            return MarketSession("MIDDAY", "Mid-session", True)
        if t < time(14, 45):
            return MarketSession("AFTERNOON", "Afternoon", True)
        if t < time(15, 25):
            return MarketSession("CLOSING", "Closing phase", True)
        return MarketSession("CLOSED", "Post-close", False)


@dataclass(frozen=True)
class CandidateLifecycleEvaluation:
    candidate_id: str
    signal_id: str
    candidate_symbol: str | None
    instrument_token: int | None
    state: str
    health_score: float
    age_seconds: float
    created_session: str
    current_session: str
    market_drift: str
    duplicate: bool
    reason: str
    action: str
    replacement_required: bool
    replacement_signal_id: str | None = None

    @property
    def active(self) -> bool:
        return self.state in {"NEW", "VALID", "AGING"} and not self.duplicate


class CandidateLifecycleManager:
    """Evaluate whether a candidate is currently eligible for execution.

    Signal age and session transitions are informational. A candidate is either
    still eligible for evaluation or is finalized as NOT_ELIGIBLE with an exact
    reason. The lifecycle never parks candidates in EXPIRED/replacement states.
    """

    def __init__(self, *, freshness_seconds: int = 180, hard_expiry_seconds: int | None = None):
        self.freshness_seconds = max(30, int(freshness_seconds))
        # Retained for constructor compatibility; age does not expire candidates.
        self.hard_expiry_seconds = max(
            self.freshness_seconds,
            int(hard_expiry_seconds or self.freshness_seconds * 5),
        )

    @staticmethod
    def _clamp(value: float) -> float:
        return round(max(0.0, min(100.0, float(value))), 2)

    def evaluate(
        self,
        *,
        signal_id: str,
        confirmation_timestamp: str | None,
        now: datetime,
        candidate=None,
        duplicate: bool = False,
        replacement_signal_id: str | None = None,
    ) -> CandidateLifecycleEvaluation:
        current_session = MarketSessionManager.classify(now).code
        try:
            ts = datetime.fromisoformat(str(confirmation_timestamp))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            else:
                ts = ts.astimezone(IST)
            age = max(0.0, (now.astimezone(IST) - ts).total_seconds())
            created_session = MarketSessionManager.classify(ts).code
        except Exception:
            age = float(self.freshness_seconds + 1)
            created_session = "UNKNOWN"

        symbol = None
        token = None
        rule_score = 50.0
        technical_score = 50.0
        drift_count = 0
        if candidate is not None:
            symbol = str(candidate.contract.tradingsymbol)
            token = int(candidate.contract.instrument_token)
            rule_score = float(candidate.total_score)
            technical_parts = [
                float(candidate.vwap_score) / 10.0 * 100.0,
                float(candidate.ema_score) / 10.0 * 100.0,
                float(candidate.momentum_score) / 10.0 * 100.0,
            ]
            technical_score = sum(technical_parts) / len(technical_parts)
            drift_count = sum(x <= 0.0 for x in technical_parts)

        health = self._clamp(rule_score * 0.75 + technical_score * 0.25)
        drift = "CONFIRMED" if drift_count >= 3 else "ELEVATED" if drift_count == 2 else "LOW"

        state = "VALID"
        reason = "CURRENT_CANDIDATE"
        action = "EVALUATE"

        if age <= min(60, self.freshness_seconds * 0.34):
            state = "NEW"
        elif age >= self.freshness_seconds * 0.67:
            state = "AGING"

        # Current evidence, not age, decides eligibility. Lost VWAP + EMA +
        # momentum finalizes this candidate immediately; a later Red Bar creates
        # a new independent candidate instead of replacing/reactivating this one.
        if candidate is not None and drift == "CONFIRMED" and age >= 60:
            state = "NOT_ELIGIBLE"
            reason = "MARKET_DRIFT_CONFIRMED VWAP+EMA+MOMENTUM_LOST"
            action = "REJECT_CANDIDATE"
        elif duplicate:
            state = "NOT_ELIGIBLE"
            reason = "DUPLICATE_EXISTING_POSITION_OR_QUEUE"
            action = "MANAGE_EXISTING_POSITION"

        candidate_id = f"CAND-{signal_id}-{token if token is not None else 'SIGNAL'}"
        return CandidateLifecycleEvaluation(
            candidate_id=candidate_id,
            signal_id=signal_id,
            candidate_symbol=symbol,
            instrument_token=token,
            state=state,
            health_score=health,
            age_seconds=round(age, 2),
            created_session=created_session,
            current_session=current_session,
            market_drift=drift,
            duplicate=bool(duplicate),
            reason=reason,
            action=action,
            replacement_required=False,
            replacement_signal_id=None,
        )
