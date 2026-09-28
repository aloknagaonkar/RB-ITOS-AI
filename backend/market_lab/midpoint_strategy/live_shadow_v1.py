from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional

from market_lab.domain import IST

from .boundary_classifier import MidpointBoundaryClassifierV55, OTHER_FRESH_A
from .config import MidpointShadowConfig
from .family_b_detector import FamilyBObservation
from .models import MidpointFamily, MidpointShadowState
from .runtime import AuditableFamilyBEngine, MidpointFamilyBRuntime
from .structure import ReferenceStructure, boundary_broken, midpoint_broken

STRATEGY_ID = "MIDPOINT_STRATEGY_SHADOW_V1"
MODEL = "MIDPOINT_STRATEGY_LIVE_SHADOW_V1"


@dataclass
class _ReferenceRuntime:
    reference: ReferenceStructure
    runtime: MidpointFamilyBRuntime
    midpoint_seen: bool = False
    boundary_seen: bool = False
    plus20_points: Optional[float] = None
    plus20_directional_vwap: Optional[float] = None
    running_close_mfe: float = 0.0
    closed: bool = False


@dataclass
class _SessionState:
    session_date: date
    references: dict[str, _ReferenceRuntime] = field(default_factory=dict)
    observations: list[FamilyBObservation] = field(default_factory=list)
    processed_minutes: set[datetime] = field(default_factory=set)
    active_reference_type: Optional[str] = None


class MidpointLiveShadowCoordinatorV1:
    """Observation-only Midpoint Strategy live-shadow coordinator."""

    def __init__(
        self,
        *,
        market_sources,
        audit_path: str | Path = "data/live-observation/midpoint-strategy-v1/audit.jsonl",
    ) -> None:
        self.market_sources = market_sources
        self.config = MidpointShadowConfig()
        self.config.assert_safe()
        self.engine = AuditableFamilyBEngine(
            journal_path=audit_path,
            config=self.config,
        )
        self.boundary_classifier = MidpointBoundaryClassifierV55()
        self.state: _SessionState | None = None

    @staticmethod
    def _latest_complete_minute(now: datetime) -> datetime:
        local = now.astimezone(IST).replace(second=0, microsecond=0)
        return local - timedelta(minutes=1)

    @staticmethod
    def _candle_ts(candle) -> datetime:
        return candle.timestamp.astimezone(IST).replace(second=0, microsecond=0)

    @staticmethod
    def _float(candle, name: str) -> float:
        return float(getattr(candle, name))

    @staticmethod
    def _volume(candle) -> float:
        value = getattr(candle, "volume", None)
        return 0.0 if value is None else float(value)

    def _reset_session(self, session_date: date) -> None:
        self.state = _SessionState(session_date=session_date)

    def bootstrap(self, now: datetime) -> dict[str, Any]:
        local = now.astimezone(IST)
        self._reset_session(local.date())
        return self.process(now)

    def _futures_vwap_map(self, candles: list[Any], latest: datetime) -> dict[datetime, tuple[float, float]]:
        """Cumulative raw futures close-volume VWAP, exact minute only."""
        out: dict[datetime, tuple[float, float]] = {}
        pv = 0.0
        vol = 0.0
        for c in sorted(candles, key=self._candle_ts):
            ts = self._candle_ts(c)
            if ts > latest:
                continue
            close = self._float(c, "close")
            volume = self._volume(c)
            if volume <= 0:
                continue
            pv += close * volume
            vol += volume
            out[ts] = (close, pv / vol)
        return out

    def _build_reference_if_ready(
        self,
        *,
        ts: datetime,
        underlying_by_ts: dict[datetime, Any],
    ) -> None:
        assert self.state is not None
        if ts.time() < time(9, 24):
            return
        if ts.minute % 5 != 4:
            return

        group_start = ts.replace(minute=(ts.minute // 5) * 5)
        if group_start.time() < time(9, 20):
            return

        minutes = [group_start + timedelta(minutes=i) for i in range(5)]
        if not all(m in underlying_by_ts for m in minutes):
            return

        rows = [underlying_by_ts[m] for m in minutes]
        open_ = self._float(rows[0], "open")
        close = self._float(rows[-1], "close")
        if close == open_:
            return

        ref_type = "RED" if close < open_ else "GREEN"
        if ref_type in self.state.references:
            return

        high = max(self._float(r, "high") for r in rows)
        low = min(self._float(r, "low") for r in rows)

        ref = ReferenceStructure(
            session_date=self.state.session_date.isoformat(),
            reference_type=ref_type,
            start_timestamp=group_start.isoformat(),
            end_timestamp=ts.isoformat(),
            high=high,
            low=low,
        )
        runtime = MidpointFamilyBRuntime(reference=ref)
        self.state.references[ref_type] = _ReferenceRuntime(
            reference=ref,
            runtime=runtime,
        )

        self.engine._audit(
            runtime=runtime,
            timestamp=ts.isoformat(),
            event_type="OPENING_REFERENCE_CREATED",
            direction=ref.direction,
            result="CREATED",
            reason=f"FIRST_{ref_type}_5M_AFTER_0915_IGNORE",
            evidence={
                "reference_type": ref_type,
                "reference_start": group_start.isoformat(),
                "reference_end": ts.isoformat(),
                "reference_high": high,
                "reference_low": low,
                "midpoint": ref.midpoint,
                "boundary": ref.boundary,
            },
        )

    def _directional_points(self, rr: _ReferenceRuntime, close: float) -> float:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None:
            raise ValueError("directional points requested before entry")
        return self.engine.manager.directional_points(
            lifecycle.direction,
            lifecycle.entry_underlying_close,
            close,
        )

    def _favorable_points(self, rr: _ReferenceRuntime, underlying) -> float:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None:
            raise ValueError("favorable points requested before entry")
        px = (
            self._float(underlying, "high")
            if lifecycle.direction == "BULLISH"
            else self._float(underlying, "low")
        )
        return self.engine.manager.directional_points(
            lifecycle.direction,
            lifecycle.entry_underlying_close,
            px,
        )

    def _terminal_invalidated(self, rr: _ReferenceRuntime, close: float) -> bool:
        # Canonical Family-B terminal: adverse midpoint close.
        if rr.reference.reference_type == "RED":
            return close > rr.reference.midpoint
        return close < rr.reference.midpoint

    def _close_terminal(
        self,
        rr: _ReferenceRuntime,
        obs: FamilyBObservation,
        reason: str,
    ) -> None:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None or rr.closed:
            return

        points = self._directional_points(rr, obs.close)
        before = lifecycle.state.value
        lifecycle.state = MidpointShadowState.CLOSED
        rr.closed = True

        self.engine._audit(
            runtime=rr.runtime,
            timestamp=obs.timestamp,
            event_type="STRUCTURAL_TERMINAL",
            direction=lifecycle.direction,
            result="SHADOW_CLOSE",
            reason=reason,
            state_before=before,
            state_after=lifecycle.state.value,
            observation=obs,
            directional_points=points,
            evidence={
                "action_intent": "SHADOW_CLOSE",
                "order_sent": False,
            },
        )

    def _process_management(
        self,
        rr: _ReferenceRuntime,
        obs: FamilyBObservation,
        prev_obs: FamilyBObservation | None,
        underlying,
    ) -> bool:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None or rr.closed:
            return False

        if self._terminal_invalidated(rr, obs.close):
            self._close_terminal(rr, obs, "MIDPOINT_INVALIDATION")
            return True

        points = self._directional_points(rr, obs.close)
        favorable_points = self._favorable_points(rr, underlying)
        rr.running_close_mfe = max(rr.running_close_mfe, favorable_points)

        # Canonical +20 proof uses favorable 1m high/low excursion.
        if lifecycle.plus20_timestamp is None and favorable_points >= 20.0:
            self.engine.mark_plus20(rr.runtime, obs)
            rr.plus20_points = 20.0
            rr.plus20_directional_vwap = self.engine.detector.directional_vwap_diff(
                rr.reference, obs
            )
            return False

        if (
            lifecycle.plus20_timestamp is not None
            and lifecycle.classifier_timestamp is None
        ):
            target = lifecycle.plus20_timestamp + timedelta(minutes=10)
            current_ts = datetime.fromisoformat(obs.timestamp)
            if current_ts == target:
                if rr.plus20_points is None or rr.plus20_directional_vwap is None:
                    raise AssertionError("plus20 evidence missing")
                current_dv = self.engine.detector.directional_vwap_diff(
                    rr.reference, obs
                )
                self.engine.classify_runner(
                    rr.runtime,
                    obs,
                    net_directional_progress_from_plus20=points - rr.plus20_points,
                    directional_futures_vwap_change=current_dv - rr.plus20_directional_vwap,
                )
            elif current_ts > target:
                self.engine._audit(
                    runtime=rr.runtime,
                    timestamp=obs.timestamp,
                    event_type="RUNNER_CLASSIFICATION_UNAVAILABLE",
                    direction=lifecycle.direction,
                    result="NO_CLASSIFICATION",
                    reason="EXACT_PLUS20_PLUS10_MINUTE_MISSING",
                    state_before=lifecycle.state.value,
                    state_after=lifecycle.state.value,
                    observation=obs,
                    directional_points=points,
                    evidence={"required_timestamp": target.isoformat()},
                )
                lifecycle.classifier_timestamp = target
            return False

        if not lifecycle.runner_strengthening:
            return False

        current_dv = self.engine.detector.directional_vwap_diff(rr.reference, obs)
        prev_dv = (
            self.engine.detector.directional_vwap_diff(rr.reference, prev_obs)
            if prev_obs is not None else None
        )

        if lifecycle.degraded_timestamp is None and prev_dv is not None:
            drawdown = rr.running_close_mfe - points
            prior_minute_dv_change = current_dv - prev_dv
            if drawdown > 0 and prior_minute_dv_change < 0:
                self.engine.mark_degraded(
                    rr.runtime,
                    obs,
                    degraded_target_move=points,
                    drawdown_from_running_mfe_close=drawdown,
                    prior_minute_directional_vwap_change=prior_minute_dv_change,
                )
                return False

        if (
            lifecycle.degraded_timestamp is not None
            and lifecycle.recovery_timestamp is None
            and lifecycle.degraded_target_move is not None
            and points > lifecycle.degraded_target_move
        ):
            self.engine.mark_recovery(rr.runtime, obs)
            return False

        if lifecycle.recovery_timestamp is not None and lifecycle.rescue_timestamp is None:
            self.engine.evaluate_cap20(rr.runtime, obs)
            if lifecycle.rescue_timestamp is not None:
                return False

        if lifecycle.rescue_timestamp is not None and lifecycle.reentry_count == 0:
            self.engine.evaluate_reentry(rr.runtime, obs)

        return False

    def _process_minute(
        self,
        *,
        ts: datetime,
        underlying,
        futures_close: float,
        futures_vwap: float,
        underlying_by_ts: dict[datetime, Any],
    ) -> None:
        assert self.state is not None

        self._build_reference_if_ready(ts=ts, underlying_by_ts=underlying_by_ts)

        obs = FamilyBObservation(
            timestamp=ts.isoformat(),
            close=self._float(underlying, "close"),
            futures_price=futures_close,
            futures_vwap=futures_vwap,
        )
        prev_obs = self.state.observations[-1] if self.state.observations else None
        self.state.observations.append(obs)

        terminal_this_minute = False

        active_type = self.state.active_reference_type
        if active_type is not None:
            active_rr = self.state.references.get(active_type)
            if active_rr is not None and active_rr.runtime.lifecycle is not None:
                terminal_this_minute = self._process_management(
                    active_rr, obs, prev_obs, underlying
                )
                if active_rr.closed:
                    self.state.active_reference_type = None

        if terminal_this_minute:
            return

        for ref_type in ("RED", "GREEN"):
            rr = self.state.references.get(ref_type)
            if rr is None or rr.closed:
                continue

            another_active = (
                self.state.active_reference_type is not None
                and self.state.active_reference_type != ref_type
            )

            if ts <= datetime.fromisoformat(rr.reference.end_timestamp):
                continue

            if not rr.midpoint_seen and midpoint_broken(rr.reference, obs.close):
                rr.midpoint_seen = True
                self.engine._audit(
                    runtime=rr.runtime,
                    timestamp=obs.timestamp,
                    event_type="MIDPOINT_BREAK",
                    direction=rr.reference.direction,
                    result="CONFIRMED_CLOSE",
                    reason="ONE_MINUTE_CLOSE_BEYOND_MIDPOINT",
                    observation=obs,
                )

            if (
                rr.midpoint_seen
                and not rr.boundary_seen
                and boundary_broken(rr.reference, obs.close)
            ):
                rr.boundary_seen = True
                self.engine._audit(
                    runtime=rr.runtime,
                    timestamp=obs.timestamp,
                    event_type="BOUNDARY_BREAK",
                    direction=rr.reference.direction,
                    result="CONFIRMED_CLOSE",
                    reason="ONE_MINUTE_CLOSE_BEYOND_ORIGINAL_BOUNDARY",
                    observation=obs,
                )

                decision = self.boundary_classifier.classify(
                    reference=rr.reference,
                    boundary_observation=obs,
                    history=self.state.observations,
                )

                if decision.owner == MidpointFamily.E.value:
                    rr.runtime.family = MidpointFamily.E
                else:
                    rr.runtime.family = MidpointFamily.B

                self.engine._audit(
                    runtime=rr.runtime,
                    timestamp=obs.timestamp,
                    event_type="BOUNDARY_CLASSIFIED",
                    direction=rr.reference.direction,
                    result=decision.owner,
                    reason=decision.reason,
                    observation=obs,
                    evidence={
                        "family_selected": decision.owner,
                        "candidate_a_at_boundary": decision.candidate_a_at_boundary,
                        "prior_window_crossed_threshold": decision.prior_window_crossed_threshold,
                        "raw_futures_vwap_diff": decision.raw_futures_vwap_diff,
                        "directional_vwap_diff": decision.directional_vwap_diff,
                    },
                )

                if decision.owner == MidpointFamily.E.value:
                    if not self.config.family_e_enabled:
                        self.engine._audit(
                            runtime=rr.runtime,
                            timestamp=obs.timestamp,
                            event_type="E_SELECTED_BUT_DISABLED",
                            direction=rr.reference.direction,
                            result="NO_ENTRY",
                            reason="FAMILY_E_DISABLED",
                            observation=obs,
                        )
                        continue

                    if another_active:
                        self.engine._audit(
                            runtime=rr.runtime,
                            timestamp=obs.timestamp,
                            event_type="E_ENTRY_BLOCKED",
                            direction=rr.reference.direction,
                            result="NO_ENTRY",
                            reason="ANOTHER_REFERENCE_ACTIVE",
                            observation=obs,
                        )
                        continue

                    self.engine.start_e_entry(rr.runtime, obs)
                    self.state.active_reference_type = ref_type
                    rr.running_close_mfe = 0.0
                    continue

                if decision.owner == MidpointFamily.B.value:
                    self.engine.start_b_watch(
                        rr.runtime,
                        obs,
                        self.state.observations,
                    )
                    continue

                if decision.owner == OTHER_FRESH_A:
                    self.engine._audit(
                        runtime=rr.runtime,
                        timestamp=obs.timestamp,
                        event_type="BOUNDARY_OWNER_OTHER",
                        direction=rr.reference.direction,
                        result="NO_B_OR_E_ENTRY",
                        reason="FRESH_CANDIDATE_A_AT_BOUNDARY",
                        observation=obs,
                    )
                    continue

                raise AssertionError(f"unsupported boundary owner: {decision.owner}")

            if (
                rr.boundary_seen
                and rr.runtime.watch is not None
                and rr.runtime.lifecycle is None
                and rr.runtime.watch.active
                and not another_active
            ):
                result = self.engine.evaluate_b_watch(
                    rr.runtime,
                    obs,
                    self.state.observations,
                )
                if result == "ENTRY":
                    self.state.active_reference_type = ref_type
                    rr.running_close_mfe = 0.0

    def process(self, now: datetime) -> dict[str, Any]:
        local = now.astimezone(IST)
        if self.state is None or self.state.session_date != local.date():
            self._reset_session(local.date())

        latest = self._latest_complete_minute(local)

        underlying = self.market_sources.nifty_intraday_1m(now=local)
        futures = self.market_sources.nifty_futures_intraday_1m(now=local)

        underlying_by_ts = {
            self._candle_ts(c): c
            for c in underlying
            if self._candle_ts(c) <= latest
        }
        futures_map = self._futures_vwap_map(futures, latest)

        common = sorted(set(underlying_by_ts).intersection(futures_map))

        processed_now = 0
        for ts in common:
            if ts in self.state.processed_minutes:
                continue
            if ts.time() < time(9, 15):
                self.state.processed_minutes.add(ts)
                continue

            f_close, f_vwap = futures_map[ts]
            self._process_minute(
                ts=ts,
                underlying=underlying_by_ts[ts],
                futures_close=f_close,
                futures_vwap=f_vwap,
                underlying_by_ts=underlying_by_ts,
            )
            self.state.processed_minutes.add(ts)
            processed_now += 1

        active = self.state.active_reference_type
        active_state = None
        if active:
            rr = self.state.references.get(active)
            if rr and rr.runtime.lifecycle:
                active_state = rr.runtime.lifecycle.state.value

        return {
            "model": MODEL,
            "strategy_id": STRATEGY_ID,
            "session_date": self.state.session_date.isoformat(),
            "latest_complete_minute": latest.isoformat(),
            "processed_now": processed_now,
            "processed_total": len(self.state.processed_minutes),
            "reference_types": sorted(self.state.references),
            "active_reference_type": active,
            "active_state": active_state,
            "safety": {
                "observation_only": self.config.observation_only,
                "execution_enabled": self.config.execution_enabled,
                "paper_order_enabled": self.config.paper_order_enabled,
                "quantity": self.config.quantity,
            },
        }
