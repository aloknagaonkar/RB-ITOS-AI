from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .audit import AuditEvent, JsonlAuditJournal, deterministic_event_id
from .config import MidpointShadowConfig
from .family_b_detector import (
    FamilyBDelayedDetector,
    FamilyBObservation,
    FamilyBWatch,
)
from .family_b_shadow import FamilyBShadowManager, FamilyBShadowRuntime
from .models import MidpointShadowState
from .structure import ReferenceStructure


@dataclass
class MidpointFamilyBRuntime:
    reference: ReferenceStructure
    watch: Optional[FamilyBWatch] = None
    lifecycle: Optional[FamilyBShadowRuntime] = None
    rescue_directional_vwap: Optional[float] = None


class AuditableFamilyBEngine:
    """Family-B detector + management + immutable audit evidence.

    This engine is observation only. It never creates an order.
    """

    def __init__(
        self,
        *,
        journal_path: str | Path,
        config: Optional[MidpointShadowConfig] = None,
    ):
        self.config = config or MidpointShadowConfig()
        self.config.assert_safe()
        self.detector = FamilyBDelayedDetector()
        self.manager = FamilyBShadowManager(self.config)
        self.journal = JsonlAuditJournal(journal_path)

    def _audit(
        self,
        *,
        runtime: MidpointFamilyBRuntime,
        timestamp: str,
        event_type: str,
        direction: Optional[str],
        result: Optional[str] = None,
        reason: Optional[str] = None,
        state_before: Optional[str] = None,
        state_after: Optional[str] = None,
        observation: Optional[FamilyBObservation] = None,
        directional_points: Optional[float] = None,
        evidence: Optional[dict] = None,
        ordinal: int = 0,
    ) -> None:
        ref = runtime.reference
        obs = observation
        event = AuditEvent(
            event_id=deterministic_event_id(
                session_date=ref.session_date,
                family="B",
                event_timestamp=timestamp,
                event_type=event_type,
                direction=direction,
                ordinal=ordinal,
            ),
            session_date=ref.session_date,
            strategy=self.config.strategy_name,
            version=self.config.version,
            family="B",
            event_timestamp=timestamp,
            event_type=event_type,
            direction=direction,
            state_before=state_before,
            state_after=state_after,
            result=result,
            reason=reason,
            underlying_price=obs.close if obs else None,
            directional_points=directional_points,
            reference_type=ref.reference_type,
            reference_high=ref.high,
            reference_low=ref.low,
            midpoint=ref.midpoint,
            original_boundary=ref.boundary,
            futures_price=obs.futures_price if obs else None,
            futures_vwap=obs.futures_vwap if obs else None,
            directional_vwap_value=(
                self.detector.directional_vwap_diff(ref, obs)
                if obs else None
            ),
            source_candle_timestamp=obs.timestamp if obs else None,
            evidence=evidence or {},
            observation_only=self.config.observation_only,
            execution_enabled=self.config.execution_enabled,
            paper_order_enabled=self.config.paper_order_enabled,
            quantity=self.config.quantity,
        )
        self.journal.append(event)

    def start_b_watch(
        self,
        runtime: MidpointFamilyBRuntime,
        boundary_obs: FamilyBObservation,
        history: list[FamilyBObservation],
    ) -> None:
        watch = self.detector.start_watch(
            runtime.reference, boundary_obs, history
        )
        runtime.watch = watch
        self._audit(
            runtime=runtime,
            timestamp=boundary_obs.timestamp,
            event_type="B_WATCH_STARTED",
            direction=runtime.reference.direction,
            result="STARTED" if watch.active else "NOT_STARTED",
            reason=(
                "ORIGINAL_EVENT_CANDIDATE_A_FALSE"
                if watch.active else
                "ORIGINAL_EVENT_ALREADY_FULL_CANDIDATE_A"
            ),
            observation=boundary_obs,
            evidence={
                "original_full_candidate_a": watch.original_full_candidate_a,
                "max_delay_minutes": self.detector.MAX_DELAY_MINUTES,
            },
        )

    def evaluate_b_watch(
        self,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
        history: list[FamilyBObservation],
    ) -> str:
        if runtime.watch is None:
            raise ValueError("Family B watch not started")

        d = self.detector.evaluate(runtime.watch, obs, history)

        self._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="B_CONFIRMATION_CHECK",
            direction=runtime.reference.direction,
            result=d.result,
            reason=d.reason,
            observation=obs,
            evidence={
                "full_candidate_a": d.full_candidate_a,
                "directional_vwap_diff": d.directional_vwap_diff,
                "prior_window_crossed_threshold":
                    d.prior_window_crossed_threshold,
                "still_beyond_original_boundary":
                    d.still_beyond_original_boundary,
                "structure_valid": d.structure_valid,
                "minutes_since_boundary_break":
                    d.minutes_since_boundary_break,
            },
        )

        if d.result == "ENTRY":
            runtime.lifecycle = FamilyBShadowRuntime(
                direction=runtime.reference.direction,
                entry_timestamp=datetime.fromisoformat(obs.timestamp),
                entry_underlying_close=obs.close,
                state=MidpointShadowState.ACTIVE,
            )
            self._audit(
                runtime=runtime,
                timestamp=obs.timestamp,
                event_type="B_ENTRY",
                direction=runtime.reference.direction,
                result="SHADOW_ENTRY",
                reason="B_DELAYED_FULL_CANDIDATE_A",
                state_before="B_WATCH",
                state_after="ACTIVE",
                observation=obs,
                directional_points=0.0,
                evidence={
                    "action_intent": "SHADOW_ENTRY",
                    "order_sent": False,
                },
            )
        return d.result

    def mark_plus20(
        self,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
    ) -> None:
        if runtime.lifecycle is None:
            raise ValueError("no active B lifecycle")
        rt = runtime.lifecycle
        state_before = rt.state.value
        self.manager.mark_plus20(rt, datetime.fromisoformat(obs.timestamp))
        points = self.manager.directional_points(
            rt.direction, rt.entry_underlying_close, obs.close
        )
        self._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="PLUS20_PROOF",
            direction=rt.direction,
            result="PROVED",
            reason="DIRECTIONAL_POINTS_REACHED_PLUS20",
            state_before=state_before,
            state_after=rt.state.value,
            observation=obs,
            directional_points=points,
        )

    def classify_runner(
        self,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
        *,
        net_directional_progress_from_plus20: float,
        directional_futures_vwap_change: float,
    ) -> None:
        if runtime.lifecycle is None:
            raise ValueError("no active B lifecycle")
        rt = runtime.lifecycle
        before = rt.state.value
        sig = self.manager.classify_runner(
            rt,
            datetime.fromisoformat(obs.timestamp),
            net_directional_progress_from_plus20,
            directional_futures_vwap_change,
        )
        self._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="RUNNER_CLASSIFICATION",
            direction=rt.direction,
            result=sig.reason,
            reason=sig.reason,
            state_before=before,
            state_after=rt.state.value,
            observation=obs,
            evidence={
                "net_directional_progress_from_plus20":
                    net_directional_progress_from_plus20,
                "directional_futures_vwap_change":
                    directional_futures_vwap_change,
                "condition_progress_positive":
                    net_directional_progress_from_plus20 > 0,
                "condition_vwap_change_positive":
                    directional_futures_vwap_change > 0,
            },
        )

    def mark_degraded(
        self,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
        *,
        degraded_target_move: float,
        drawdown_from_running_mfe_close: float,
        prior_minute_directional_vwap_change: float,
    ) -> None:
        if runtime.lifecycle is None:
            raise ValueError("no active B lifecycle")
        rt = runtime.lifecycle
        before = rt.state.value
        self.manager.mark_degraded(
            rt,
            datetime.fromisoformat(obs.timestamp),
            degraded_target_move,
        )
        self._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="DEGRADED_STARTED",
            direction=rt.direction,
            result="DEGRADED",
            reason="DRAWDOWN_AND_VWAP_WEAKENING",
            state_before=before,
            state_after=rt.state.value,
            observation=obs,
            evidence={
                "degraded_target_move": degraded_target_move,
                "drawdown_from_running_mfe_close":
                    drawdown_from_running_mfe_close,
                "prior_minute_directional_vwap_change":
                    prior_minute_directional_vwap_change,
                "condition_drawdown_positive":
                    drawdown_from_running_mfe_close > 0,
                "condition_prior_minute_vwap_change_negative":
                    prior_minute_directional_vwap_change < 0,
            },
        )

    def mark_recovery(
        self,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
    ) -> None:
        if runtime.lifecycle is None:
            raise ValueError("no active B lifecycle")
        rt = runtime.lifecycle
        self.manager.mark_recovery(rt, datetime.fromisoformat(obs.timestamp))
        self._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="DEGRADED_TARGET_RECOVERED",
            direction=rt.direction,
            result="RECOVERED",
            reason="DIRECTIONAL_CLOSE_RETAKE",
            state_before=rt.state.value,
            state_after=rt.state.value,
            observation=obs,
            evidence={
                "degraded_target_move": rt.degraded_target_move,
            },
        )

    def evaluate_cap20(
        self,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
    ) -> bool:
        if runtime.lifecycle is None:
            raise ValueError("no active B lifecycle")
        rt = runtime.lifecycle
        current_points = self.manager.directional_points(
            rt.direction, rt.entry_underlying_close, obs.close
        )
        current_move = current_points
        before = rt.state.value

        sig = self.manager.maybe_cap20_rescue(
            rt,
            datetime.fromisoformat(obs.timestamp),
            current_directional_points=current_points,
            current_directional_move=current_move,
        )

        if sig is None:
            recovery_age = None
            if rt.recovery_timestamp:
                recovery_age = (
                    datetime.fromisoformat(obs.timestamp)
                    - rt.recovery_timestamp
                ).total_seconds() / 60.0

            self._audit(
                runtime=runtime,
                timestamp=obs.timestamp,
                event_type="CAP20_CHECK",
                direction=rt.direction,
                result="NO_ACTION",
                reason="CAP20_CONDITIONS_NOT_ALL_MET",
                state_before=before,
                state_after=rt.state.value,
                observation=obs,
                directional_points=current_points,
                evidence={
                    "degraded_target_move": rt.degraded_target_move,
                    "current_directional_move": current_move,
                    "minutes_since_recovery": recovery_age,
                    "condition_rebreak": (
                        rt.degraded_target_move is not None
                        and current_move < rt.degraded_target_move
                    ),
                    "condition_age_ge_10": (
                        recovery_age is not None and recovery_age >= 10
                    ),
                    "condition_points_le_20": current_points <= 20,
                },
            )
            return False

        runtime.rescue_directional_vwap = self.detector.directional_vwap_diff(
            runtime.reference, obs
        )
        self._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="CAP20_RESCUE_TRIGGERED",
            direction=rt.direction,
            result="SHADOW_EXIT",
            reason="CAP20_RESCUE",
            state_before=before,
            state_after=rt.state.value,
            observation=obs,
            directional_points=current_points,
            evidence={
                "degraded_target_move": rt.degraded_target_move,
                "action_intent": "SHADOW_EXIT",
                "order_sent": False,
            },
        )
        return True

    def evaluate_reentry(
        self,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
    ) -> bool:
        if runtime.lifecycle is None:
            raise ValueError("no active B lifecycle")
        if runtime.rescue_directional_vwap is None:
            return False

        rt = runtime.lifecycle
        current_move = self.manager.directional_points(
            rt.direction, rt.entry_underlying_close, obs.close
        )
        dv_now = self.detector.directional_vwap_diff(
            runtime.reference, obs
        )
        before = rt.state.value

        sig = self.manager.maybe_post_rescue_reentry(
            rt,
            datetime.fromisoformat(obs.timestamp),
            current_directional_move=current_move,
            directional_futures_vwap_now=dv_now,
            directional_futures_vwap_at_rescue=
                runtime.rescue_directional_vwap,
        )

        within_window = False
        minutes_since_rescue = None
        if rt.rescue_timestamp:
            minutes_since_rescue = (
                datetime.fromisoformat(obs.timestamp)
                - rt.rescue_timestamp
            ).total_seconds() / 60.0
            within_window = (
                minutes_since_rescue
                <= self.config.post_rescue_reentry_window_minutes
            )

        if sig is None:
            self._audit(
                runtime=runtime,
                timestamp=obs.timestamp,
                event_type="POST_RESCUE_REENTRY_CHECK",
                direction=rt.direction,
                result="NO_ACTION",
                reason="REENTRY_CONDITIONS_NOT_ALL_MET",
                state_before=before,
                state_after=rt.state.value,
                observation=obs,
                evidence={
                    "minutes_since_rescue": minutes_since_rescue,
                    "within_20m_window": within_window,
                    "current_directional_move": current_move,
                    "degraded_target_move": rt.degraded_target_move,
                    "target_retaken": (
                        rt.degraded_target_move is not None
                        and current_move > rt.degraded_target_move
                    ),
                    "directional_vwap_now": dv_now,
                    "directional_vwap_at_rescue":
                        runtime.rescue_directional_vwap,
                    "vwap_recovered":
                        dv_now > runtime.rescue_directional_vwap,
                    "reentry_count": rt.reentry_count,
                },
            )
            return False

        self._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="POST_CAP20_REENTRY_TRIGGERED",
            direction=rt.direction,
            result="SHADOW_REENTRY",
            reason="TARGET_RETAKE_AND_VWAP_RECOVERY",
            state_before=before,
            state_after=rt.state.value,
            observation=obs,
            evidence={
                "minutes_since_rescue": minutes_since_rescue,
                "within_20m_window": within_window,
                "current_directional_move": current_move,
                "degraded_target_move": rt.degraded_target_move,
                "directional_vwap_now": dv_now,
                "directional_vwap_at_rescue":
                    runtime.rescue_directional_vwap,
                "reentry_count": rt.reentry_count,
                "action_intent": "SHADOW_REENTRY",
                "order_sent": False,
            },
        )
        return True
