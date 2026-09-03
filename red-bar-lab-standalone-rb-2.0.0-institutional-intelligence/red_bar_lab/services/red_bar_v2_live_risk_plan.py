"""Price a live Red Bar V2 admission's stop, before the order exists.

Gate 5 of the agreed entry table -- *a priceable stop, with risk inside the
8-60 point band* -- has until now only ever run in research. Live, an admitted
signal went to the option ladder with no index-level stop at all: the premium
stop is deliberately excluded for V2 rows, so risk was whatever the option did.
Two entries a day would be sized off a 4-point invalidation and a 90-point one
and both would be called one trade.

This module answers the one question the live path needs, using exactly the
helpers the research loop uses, so the two cannot drift:

    can this admission be given a stop, and is the resulting risk tradable?

It deliberately stops there. Walking the position to its exit is the other half
of the policy and belongs to ``PaperExitEngine``; a verdict here is about
whether the entry may be taken, never about how it ends.

The verdict is computed at admission -- the moment the qualifying close printed,
priced from bars truncated at that minute -- and then frozen onto the signal
row. Recomputing it at order time would price the stop off candles that printed
after the decision, which is the same lookahead ``_bars_known_at`` exists to
prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from red_bar_lab.domain.red_bar_v2 import (
    Direction,
    RiskPlan,
    RiskPlanRejected,
    TriggerResolution,
    build_risk_plan,
    entry_candle_stop,
    find_stop_trigger,
)
from red_bar_lab.services.red_bar_v2_derived_exits import (
    MISSING_EVIDENCE,
    _align_to_index,
    _bars_known_at,
    _to_datetime,
    _vwap_known_at,
    one_minute_bars,
    replay_frame,
)

#: The plan was built and its risk sits inside the band. The only tradable code.
RISK_PLAN_OK = "RISK_PLAN_OK"

#: Neither candle series was usable, so the question could not be asked. Treated
#: as *not* a strategy verdict: the caller decides whether missing data blocks an
#: entry, and the live default is to let the admission through rather than let a
#: feed outage masquerade as a risk rejection.
RISK_PLAN_UNAVAILABLE = "RISK_PLAN_UNAVAILABLE"


@dataclass(frozen=True)
class LiveRiskPlanVerdict:
    """What the live gate decided, and the numbers it decided it on.

    Every field is carried so the ladder screen can show the arithmetic rather
    than a verdict: entry, stop, the distance between them, and which candle the
    stop came from. ``tradable`` is the only field the entry path reads.
    """

    tradable: bool
    code: str
    detail: str
    direction: str | None = None
    entry_timestamp: str | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    risk_points: float | None = None
    stop_trigger: str | None = None
    trigger_timestamp: str | None = None
    trail_activation_price: float | None = None
    minimum_risk_points: float | None = None
    maximum_risk_points: float | None = None

    @property
    def evidence_only(self) -> bool:
        """True when the verdict carries no strategy opinion, only an outage."""
        return self.code == RISK_PLAN_UNAVAILABLE

    def as_dict(self) -> dict[str, object]:
        return {
            "risk_plan_tradable": bool(self.tradable),
            "risk_plan_code": self.code,
            "risk_plan_detail": self.detail,
            "risk_plan_direction": self.direction,
            "risk_plan_entry_timestamp": self.entry_timestamp,
            "risk_plan_entry_price": self.entry_price,
            "risk_stop_price": self.stop_price,
            "risk_points": self.risk_points,
            "risk_stop_trigger": self.stop_trigger,
            "risk_trigger_timestamp": self.trigger_timestamp,
            "risk_trail_activation_price": self.trail_activation_price,
            "risk_minimum_points": self.minimum_risk_points,
            "risk_maximum_points": self.maximum_risk_points,
        }


def _unavailable(detail: str) -> LiveRiskPlanVerdict:
    return LiveRiskPlanVerdict(
        tradable=True,
        code=RISK_PLAN_UNAVAILABLE,
        detail=detail,
    )


def _plan_verdict(
    plan: RiskPlan,
    *,
    minimum_risk_points: float | None,
    maximum_risk_points: float | None,
) -> LiveRiskPlanVerdict:
    return LiveRiskPlanVerdict(
        tradable=True,
        code=RISK_PLAN_OK,
        detail=(
            f"stop {plan.stop_price:.2f} from {plan.trigger.value}"
            f" risk {plan.risk_points:.2f}pts"
        ),
        direction=plan.direction.value,
        entry_timestamp=plan.entry_timestamp.isoformat(),
        entry_price=round(plan.entry_price, 2),
        stop_price=round(plan.stop_price, 2),
        risk_points=round(plan.risk_points, 2),
        stop_trigger=plan.trigger.value,
        trigger_timestamp=plan.trigger_timestamp.isoformat(),
        trail_activation_price=round(plan.trail_activation_price, 2),
        minimum_risk_points=minimum_risk_points,
        maximum_risk_points=maximum_risk_points,
    )


def evaluate_live_red_bar_v2_risk_plan(
    *,
    event: Any,
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    minimum_risk_points: float | None = None,
    maximum_risk_points: float | None = None,
    reward_multiple: float | None = None,
    trail_activation_r: float | None = None,
    trigger_resolution: TriggerResolution = TriggerResolution.LATEST,
) -> LiveRiskPlanVerdict:
    """Decide whether a live admission can be given a tradable stop.

    ``event`` is the replay's own ``CANDIDATE_ADMISSION`` event, so the entry
    price, the reference level and the reference timestamp are the strategy's
    own -- not re-derived here, where they could disagree with what was admitted.

    A missing or empty candle frame returns ``RISK_PLAN_UNAVAILABLE`` with
    ``tradable=True``. That asymmetry is deliberate: the gate exists to refuse
    entries whose invalidation level is too near or too far, and a data outage is
    evidence about the feed rather than about this trade. Rejections that *are*
    strategy verdicts -- NO_TRIGGER_CANDLE, STOP_ON_WRONG_SIDE, RISK_BELOW_FLOOR,
    RISK_ABOVE_CAP -- all return ``tradable=False``.
    """
    if index_candles is None or futures_candles is None:
        return _unavailable("index or futures candles absent")
    if getattr(index_candles, "empty", True) or getattr(futures_candles, "empty", True):
        return _unavailable("index or futures candles empty")

    entry_price = event.details.get("index_close")
    reference_timestamp = event.details.get("reference_timestamp")
    reference_midpoint = event.details.get("reference_midpoint")
    if entry_price is None or reference_timestamp is None or reference_midpoint is None:
        # The same code the research loop uses for the same hole, so a day's
        # rejected plans reconcile across the two paths by code alone.
        return LiveRiskPlanVerdict(
            tradable=False,
            code=MISSING_EVIDENCE,
            detail="admission carries no index_close/reference level to price",
            direction=str(getattr(event, "direction", "") or "") or None,
        )

    frame = replay_frame(index_candles)
    futures_frame = replay_frame(futures_candles)
    if frame.empty or futures_frame.empty:
        return _unavailable("candles held no usable rows after normalisation")

    entry_timestamp = _align_to_index(
        frame.index, _to_datetime(event.timestamp)
    )
    policy: dict[str, Any] = {}
    if reward_multiple is not None:
        policy["reward_multiple"] = reward_multiple
    if minimum_risk_points is not None:
        policy["minimum_risk_points"] = minimum_risk_points
    if maximum_risk_points is not None:
        policy["maximum_risk_points"] = maximum_risk_points
    if trail_activation_r is not None:
        policy["trail_activation_r"] = trail_activation_r

    try:
        direction = Direction(event.direction)
    except ValueError:
        return LiveRiskPlanVerdict(
            tradable=False,
            code=MISSING_EVIDENCE,
            detail=f"unknown direction {event.direction!r}",
        )

    try:
        trigger = find_stop_trigger(
            direction=direction,
            index_bars=_bars_known_at(frame, entry_timestamp),
            futures_bars=_bars_known_at(futures_frame, entry_timestamp),
            futures_vwap=_vwap_known_at(futures_frame, entry_timestamp),
            reference_midpoint=float(reference_midpoint),
            reference_timestamp=_align_to_index(
                frame.index, _to_datetime(reference_timestamp)
            ),
            entry_timestamp=entry_timestamp,
            resolution=trigger_resolution,
        )
        if trigger is None:
            # Strictly before the entry stamp: the admission is stamped one
            # minute after the candle whose close produced it, so the bar
            # carrying the stamp has not closed yet at this moment. See
            # ``entry_candle_stop``.
            trigger = entry_candle_stop(
                index_bars_1m=one_minute_bars(
                    frame.loc[frame.index < entry_timestamp]
                ),
                entry_timestamp=entry_timestamp,
            )
        plan = build_risk_plan(
            direction=direction,
            entry_timestamp=entry_timestamp,
            entry_price=float(entry_price),
            trigger_candle=trigger,
            **policy,
        )
    except RiskPlanRejected as rejected:
        return LiveRiskPlanVerdict(
            tradable=False,
            code=rejected.rejection.value,
            detail=rejected.detail,
            direction=direction.value,
            entry_timestamp=entry_timestamp.isoformat(),
            entry_price=round(float(entry_price), 2),
            minimum_risk_points=minimum_risk_points,
            maximum_risk_points=maximum_risk_points,
        )

    return _plan_verdict(
        plan,
        minimum_risk_points=minimum_risk_points,
        maximum_risk_points=maximum_risk_points,
    )


__all__ = [
    "RISK_PLAN_OK",
    "RISK_PLAN_UNAVAILABLE",
    "LiveRiskPlanVerdict",
    "evaluate_live_red_bar_v2_risk_plan",
]
