from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .config import MidpointShadowConfig
from .models import MidpointFamily, MidpointShadowState, MidpointSignal


@dataclass
class FamilyBShadowRuntime:
    """Management state for an already-qualified Family-B event.

    IMPORTANT:
    The canonical B entry detector remains the existing/frozen research
    implementation. This class intentionally owns only the shadow-live
    management layer so that B entry semantics are not silently changed.
    """

    direction: str
    entry_timestamp: datetime
    entry_underlying_close: float
    # V54: management is shared by B and E. Default keeps all existing B callers unchanged.
    family: MidpointFamily = MidpointFamily.B

    plus20_timestamp: Optional[datetime] = None
    classifier_timestamp: Optional[datetime] = None
    runner_strengthening: bool = False

    degraded_timestamp: Optional[datetime] = None
    degraded_target_move: Optional[float] = None

    recovery_timestamp: Optional[datetime] = None
    rescue_timestamp: Optional[datetime] = None
    rescue_directional_points: Optional[float] = None

    reentry_timestamp: Optional[datetime] = None
    reentry_count: int = 0

    cap20_rebreak_evaluated: bool = False

    state: MidpointShadowState = MidpointShadowState.ACTIVE


class FamilyBShadowManager:
    """Frozen management rules for the initial Midpoint shadow-live rollout.

    This does NOT generate orders.
    It produces observation-only state transitions/signals.
    """

    def __init__(self, config: Optional[MidpointShadowConfig] = None):
        self.config = config or MidpointShadowConfig()
        self.config.assert_safe()

    @staticmethod
    def directional_points(direction: str, entry: float, current: float) -> float:
        if direction == "BULLISH":
            return current - entry
        if direction == "BEARISH":
            return entry - current
        raise ValueError(f"unsupported direction: {direction}")

    def mark_plus20(
        self,
        rt: FamilyBShadowRuntime,
        timestamp: datetime,
    ) -> MidpointSignal:
        rt.plus20_timestamp = timestamp
        return MidpointSignal(
            strategy=self.config.strategy_name,
            family=rt.family,
            direction=rt.direction,
            timestamp=timestamp,
            state=rt.state,
            reason="PLUS20_PROOF",
        )

    def classify_runner(
        self,
        rt: FamilyBShadowRuntime,
        timestamp: datetime,
        net_directional_progress_from_plus20: float,
        directional_futures_vwap_change: float,
    ) -> MidpointSignal:
        rt.classifier_timestamp = timestamp
        rt.runner_strengthening = (
            net_directional_progress_from_plus20 > 0
            and directional_futures_vwap_change > 0
        )
        if rt.runner_strengthening:
            rt.state = MidpointShadowState.RUNNER_STRENGTHENING
            reason = "RUNNER_STRENGTHENING"
        else:
            reason = "NORMAL_B"

        return MidpointSignal(
            strategy=self.config.strategy_name,
            family=rt.family,
            direction=rt.direction,
            timestamp=timestamp,
            state=rt.state,
            reason=reason,
            metadata={
                "net_directional_progress_from_plus20":
                    net_directional_progress_from_plus20,
                "directional_futures_vwap_change":
                    directional_futures_vwap_change,
            },
        )

    def mark_degraded(
        self,
        rt: FamilyBShadowRuntime,
        timestamp: datetime,
        degraded_target_move: float,
    ) -> MidpointSignal:
        rt.degraded_timestamp = timestamp
        rt.degraded_target_move = degraded_target_move
        rt.state = MidpointShadowState.DEGRADED
        return MidpointSignal(
            strategy=self.config.strategy_name,
            family=rt.family,
            direction=rt.direction,
            timestamp=timestamp,
            state=rt.state,
            reason="DEGRADED",
            metadata={"degraded_target_move": degraded_target_move},
        )

    def mark_recovery(
        self,
        rt: FamilyBShadowRuntime,
        timestamp: datetime,
    ) -> MidpointSignal:
        rt.recovery_timestamp = timestamp
        return MidpointSignal(
            strategy=self.config.strategy_name,
            family=rt.family,
            direction=rt.direction,
            timestamp=timestamp,
            state=rt.state,
            reason="DEGRADED_TARGET_RECOVERED",
        )

    def maybe_cap20_rescue(
        self,
        rt: FamilyBShadowRuntime,
        timestamp: datetime,
        current_directional_points: float,
        current_directional_move: float,
    ) -> Optional[MidpointSignal]:
        if not self.config.cap20_rescue_enabled:
            return None
        if not rt.runner_strengthening:
            return None
        if rt.recovery_timestamp is None or rt.degraded_target_move is None:
            return None

        if timestamp < rt.recovery_timestamp + timedelta(minutes=10):
            return None

        if rt.cap20_rebreak_evaluated:
            return None

        # Canonical CAP20: first eligible post-recovery rebreak only.
        if current_directional_move < rt.degraded_target_move:
            rt.cap20_rebreak_evaluated = True
            if current_directional_points <= 20:
                rt.rescue_timestamp = timestamp
                rt.rescue_directional_points = current_directional_points
                rt.state = MidpointShadowState.CAP20_RESCUED
                return MidpointSignal(
                    strategy=self.config.strategy_name,
                    family=rt.family,
                    direction=rt.direction,
                    timestamp=timestamp,
                    state=rt.state,
                    reason="CAP20_RESCUE",
                    underlying_points=current_directional_points,
                    metadata={
                        "degraded_target_move": rt.degraded_target_move,
                    },
                )

        return None

    def maybe_post_rescue_reentry(
        self,
        rt: FamilyBShadowRuntime,
        timestamp: datetime,
        current_directional_move: float,
        directional_futures_vwap_now: float,
        directional_futures_vwap_at_rescue: float,
    ) -> Optional[MidpointSignal]:
        if not self.config.post_rescue_reentry_enabled:
            return None
        if rt.rescue_timestamp is None or rt.degraded_target_move is None:
            return None
        if rt.reentry_count >= self.config.max_post_rescue_reentries:
            return None

        if timestamp > (
            rt.rescue_timestamp
            + timedelta(minutes=self.config.post_rescue_reentry_window_minutes)
        ):
            return None

        # Frozen re-entry rule from V47/V48:
        # 1m CLOSE retakes degraded target
        # AND directional futures-VWAP > rescue-time level.
        if (
            current_directional_move > rt.degraded_target_move
            and directional_futures_vwap_now
                > directional_futures_vwap_at_rescue
        ):
            rt.reentry_timestamp = timestamp
            rt.reentry_count += 1
            rt.state = MidpointShadowState.REENTERED
            return MidpointSignal(
                strategy=self.config.strategy_name,
                family=rt.family,
                direction=rt.direction,
                timestamp=timestamp,
                state=rt.state,
                reason="POST_CAP20_REENTRY",
                metadata={
                    "reentry_count": rt.reentry_count,
                    "degraded_target_move": rt.degraded_target_move,
                },
            )

        return None
