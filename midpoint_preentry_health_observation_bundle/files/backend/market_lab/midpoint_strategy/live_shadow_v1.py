from __future__ import annotations

import json
import os

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional

from market_lab.domain import IST

from .boundary_classifier import MidpointBoundaryClassifierV55, OTHER_FRESH_A
from .config import MidpointShadowConfig
from .family_b_detector import FamilyBObservation
from .extended_entry_candidates import CRearmCandidate, PMMidpointBECandidate
from .models import MidpointFamily, MidpointShadowState
from .family_b_shadow import FamilyBShadowRuntime
from .normal_b_proved_candidate import (
    Bar as NormalBProvedBar,
    NormalBProvedCandidate,
)
from .entry_health_live_v1 import (
    MidpointEntryHealthLiveV1,
    entry_health_label,
    evaluate_t5_candidates,
)
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
    normal_b_proved: NormalBProvedCandidate | None = None
    normal_b_proved_last_state: str | None = None
    normal_b_proved_unavailable: bool = False
    management_route: str = "STRUCTURAL_BASELINE"
    degraded_exit_candidate_timestamp: datetime | None = None
    t5_health_checked: bool = False
    entry_health_logged: bool = False
    generation: int = 0


@dataclass
class _SessionState:
    session_date: date
    references: dict[str, _ReferenceRuntime] = field(default_factory=dict)
    observations: list[FamilyBObservation] = field(default_factory=list)
    processed_minutes: set[datetime] = field(default_factory=set)
    latest_processed_minute: datetime | None = None
    quarantined_late_minutes: set[datetime] = field(default_factory=set)
    quarantined_revised_futures_minutes: set[datetime] = field(default_factory=set)
    futures_inputs: dict[datetime, tuple[float, float]] = field(default_factory=dict)
    futures_vwap: dict[datetime, tuple[float, float]] = field(default_factory=dict)
    futures_pv: float = 0.0
    futures_volume: float = 0.0
    latest_futures_minute: datetime | None = None
    active_reference_type: Optional[str] = None
    c_rearms: dict[str, CRearmCandidate] = field(default_factory=dict)
    c_runtimes: dict[str, MidpointFamilyBRuntime] = field(default_factory=dict)
    be_rearms: dict[str, CRearmCandidate] = field(default_factory=dict)
    be_rearm_runtimes: dict[str, MidpointFamilyBRuntime] = field(default_factory=dict)
    be_rearm_meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    pm_e_candidate: PMMidpointBECandidate | None = None
    pm_e_runtime: MidpointFamilyBRuntime | None = None


from .forward_oos_v62_1 import MidpointV621ForwardOOSCollector

class MidpointLiveShadowCoordinatorV1:
    """Observation-only Midpoint Strategy live-shadow coordinator."""

    def __init__(
        self,
        *,
        market_sources,
        audit_path: str | Path = "data/live-observation/midpoint-strategy-v1/audit.jsonl",
        config: MidpointShadowConfig | None = None,
    ) -> None:
        self.market_sources = market_sources
        self.config = config or MidpointShadowConfig()
        self.config.assert_safe()
        self.engine = AuditableFamilyBEngine(
            journal_path=audit_path,
            config=self.config,
        )
        self.boundary_classifier = MidpointBoundaryClassifierV55()
        self.entry_health = MidpointEntryHealthLiveV1()
        self.latest_entry_health_raw: dict | None = None
        self.state: _SessionState | None = None

        # V62.2 forward-OOS research adapter. Disabled unless explicitly enabled.
        # It is observational only and never changes strategy decisions or orders.
        self._audit_path = Path(audit_path)
        self._v621_collector = None
        self._v621_audit_offset = 0
        if os.getenv("MIDPOINT_V62_OOS_COLLECTOR_ENABLED", "0") == "1":
            ledger_path = Path(
                os.getenv(
                    "MIDPOINT_V62_OOS_LEDGER",
                    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
                    "midpoint-v62-forward-reentry-oos/reentry-oos-ledger-v62.csv",
                )
            )
            self._v621_collector = MidpointV621ForwardOOSCollector(ledger_path)
            if self._audit_path.exists():
                self._v621_audit_offset = self._audit_path.stat().st_size

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
        if self.state is not None and self.state.session_date != session_date:
            previous = self.state
            active_type = previous.active_reference_type
            rr = previous.references.get(active_type) if active_type else None
            lifecycle = rr.runtime.lifecycle if rr else None
            if rr and lifecycle and not rr.closed:
                last = previous.observations[-1] if previous.observations else None
                self.engine._audit(
                    runtime=rr.runtime,
                    timestamp=last.timestamp if last else lifecycle.entry_timestamp.isoformat(),
                    event_type="SESSION_END_UNRESOLVED",
                    direction=lifecycle.direction,
                    result="UNRESOLVED_VALUATION",
                    reason="NO_EXACT_SESSION_CLOSE_OBSERVATION",
                    state_before=lifecycle.state.value,
                    state_after="UNRESOLVED",
                    observation=last,
                    directional_points=self._directional_points(rr, last.close) if last else None,
                    evidence={"valuation_only": True, "order_sent": False,
                              "last_observed_timestamp": last.timestamp if last else None},
                )
                rr.closed = True
        self.state = _SessionState(session_date=session_date)

    def bootstrap(self, now: datetime) -> dict[str, Any]:
        local = now.astimezone(IST)
        self._reset_session(local.date())
        return self.process(now)

    def _futures_vwap_map(self, candles: list[Any], latest: datetime) -> dict[datetime, tuple[float, float]]:
        """Cumulative raw futures close-volume VWAP, exact minute only."""
        if self.state is not None:
            state = self.state
            seen: set[datetime] = set()
            available: set[datetime] = set()
            for c in sorted(candles, key=self._candle_ts):
                ts = self._candle_ts(c)
                if ts > latest:
                    continue
                close, volume = self._float(c, "close"), self._volume(c)
                if volume <= 0:
                    continue
                available.add(ts)
                if ts in seen:
                    state.quarantined_revised_futures_minutes.add(ts)
                    continue
                seen.add(ts)
                previous = state.futures_inputs.get(ts)
                if previous is not None:
                    if previous != (close, volume):
                        state.quarantined_revised_futures_minutes.add(ts)
                    continue
                if state.latest_futures_minute is not None and ts < state.latest_futures_minute:
                    state.quarantined_revised_futures_minutes.add(ts)
                    state.quarantined_late_minutes.add(ts)
                    continue
                state.futures_inputs[ts] = (close, volume)
                state.latest_futures_minute = ts
                state.futures_pv += close * volume
                state.futures_volume += volume
                state.futures_vwap[ts] = (close, state.futures_pv / state.futures_volume)
            return {ts: state.futures_vwap[ts] for ts in available if ts in state.futures_vwap}
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
        if self.state is not None:
            for key, candidate in self.state.c_rearms.items():
                if (
                    candidate.reference == rr.reference
                    and candidate.origin_entry_timestamp
                    == lifecycle.entry_timestamp
                ):
                    candidate.mark_origin_closed(
                        datetime.fromisoformat(obs.timestamp)
                    )
            for candidate in self.state.be_rearms.values():
                if (
                    candidate.reference == rr.reference
                    and candidate.origin_entry_timestamp
                    == lifecycle.entry_timestamp
                ):
                    candidate.mark_origin_closed(
                        datetime.fromisoformat(obs.timestamp)
                    )

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

    def _ensure_c_rearm(self, rr: _ReferenceRuntime) -> CRearmCandidate | None:
        if not self.config.family_c_enabled or self.state is None:
            return None
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None or rr.runtime.family not in {
            MidpointFamily.B, MidpointFamily.E
        }:
            return None
        key = rr.reference.reference_type
        candidate = self.state.c_rearms.get(key)
        if candidate is None:
            candidate = CRearmCandidate(
                reference=rr.reference,
                origin_family=rr.runtime.family.value,
                origin_entry_timestamp=lifecycle.entry_timestamp,
            )
            self.state.c_rearms[key] = candidate
            self.state.c_runtimes[key] = MidpointFamilyBRuntime(
                reference=rr.reference,
                family=MidpointFamily.C,
            )
        return candidate

    def _ensure_be_rearm(
        self, rr: _ReferenceRuntime
    ) -> tuple[str, CRearmCandidate] | None:
        if not self.config.be_rearm_enabled or self.state is None:
            return None
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None or rr.runtime.family not in {
            MidpointFamily.B,
            MidpointFamily.E,
            MidpointFamily.PM_B,
            MidpointFamily.PM_E,
        }:
            return None
        key = (
            f"{rr.reference.reference_type}:"
            f"{lifecycle.entry_timestamp.isoformat()}"
        )
        candidate = self.state.be_rearms.get(key)
        if candidate is None:
            candidate = CRearmCandidate(
                reference=rr.reference,
                origin_family=rr.runtime.family.value,
                origin_entry_timestamp=lifecycle.entry_timestamp,
            )
            self.state.be_rearms[key] = candidate
            self.state.be_rearm_runtimes[key] = MidpointFamilyBRuntime(
                reference=rr.reference,
                family=rr.runtime.family,
            )
            self.state.be_rearm_meta[key] = {
                "generation": rr.generation + 1,
                "origin_generation": rr.generation,
                "origin_family": rr.runtime.family.value,
                "origin_entry_timestamp": lifecycle.entry_timestamp.isoformat(),
            }
        return key, candidate

    def _observe_be_rearm_touch(
        self, rr: _ReferenceRuntime, obs: FamilyBObservation, underlying
    ) -> None:
        ensured = self._ensure_be_rearm(rr)
        if ensured is None or self.state is None:
            return
        key, candidate = ensured
        action = candidate.observe_active_bar(
            timestamp=datetime.fromisoformat(obs.timestamp),
            high=self._float(underlying, "high"),
            low=self._float(underlying, "low"),
        )
        if action is None:
            return
        runtime = self.state.be_rearm_runtimes[key]
        self.engine._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="BE_REARM_MIDPOINT_TOUCH_ARMED",
            direction=action.direction,
            result="ARMED",
            reason="INTRABAR_TOUCH_OF_ORIGINAL_MIDPOINT",
            observation=obs,
            evidence={
                **self.state.be_rearm_meta[key],
                "candidate_only": True,
                "order_sent": False,
            },
        )

    def _observe_c_touch(
        self, rr: _ReferenceRuntime, obs: FamilyBObservation, underlying
    ) -> None:
        candidate = self._ensure_c_rearm(rr)
        if candidate is None or self.state is None:
            return
        action = candidate.observe_active_bar(
            timestamp=datetime.fromisoformat(obs.timestamp),
            high=self._float(underlying, "high"),
            low=self._float(underlying, "low"),
        )
        if action is None:
            return
        runtime = self.state.c_runtimes[rr.reference.reference_type]
        self.engine._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type=action.event_type,
            direction=action.direction,
            result="ARMED",
            reason=action.reason,
            observation=obs,
            evidence={
                "origin_family": candidate.origin_family,
                "origin_entry_timestamp":
                    candidate.origin_entry_timestamp.isoformat(),
                "candidate_only": True,
                "order_sent": False,
            },
        )

    def _ensure_normal_b_proved_candidate(
        self,
        rr: _ReferenceRuntime,
    ) -> NormalBProvedCandidate:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None:
            raise ValueError("candidate requires active lifecycle")
        if rr.normal_b_proved is None:
            rr.normal_b_proved = NormalBProvedCandidate(
                entry_timestamp=lifecycle.entry_timestamp,
                entry_price=lifecycle.entry_underlying_close,
                direction=lifecycle.direction,
                midpoint=rr.reference.midpoint,
            )
            rr.normal_b_proved_last_state = rr.normal_b_proved.state
        return rr.normal_b_proved

    def _observe_normal_b_proved(
        self,
        rr: _ReferenceRuntime,
        obs: FamilyBObservation,
        underlying,
        *,
        classifier_result: str | None = None,
    ) -> None:
        """Advance the parallel candidate without changing baseline lifecycle."""
        if rr.normal_b_proved_unavailable:
            return
        candidate = self._ensure_normal_b_proved_candidate(rr)
        if candidate.state == "RUNNER_BASELINE" or candidate.exit is not None:
            return
        before = candidate.state
        try:
            result = candidate.on_bar(
                NormalBProvedBar(
                    timestamp=datetime.fromisoformat(obs.timestamp),
                    high=self._float(underlying, "high"),
                    low=self._float(underlying, "low"),
                    close=obs.close,
                ),
                classifier_result=classifier_result,
            )
        except ValueError as exc:
            rr.normal_b_proved_unavailable = True
            self.engine._audit(
                runtime=rr.runtime,
                timestamp=obs.timestamp,
                event_type="NORMAL_B_PROVED_UNAVAILABLE",
                direction=rr.runtime.lifecycle.direction,
                result="UNAVAILABLE",
                reason=type(exc).__name__,
                state_before=before,
                state_after="UNAVAILABLE",
                observation=obs,
                directional_points=self._directional_points(rr, obs.close),
                evidence={"candidate_error": str(exc), "order_sent": False},
            )
            return

        after = str(result["state"])
        rr.normal_b_proved_last_state = after
        event_type = None
        event_result = None
        reason = None
        if result.get("reason"):
            event_type = "NORMAL_B_PROVED_EXIT_CANDIDATE"
            event_result = "SHADOW_EXIT_CANDIDATE"
            reason = str(result["reason"])
        elif after != before and after == "NORMAL_B_PROVED":
            event_type = "NORMAL_B_PROVED_STARTED"
            event_result = "OBSERVING"
            reason = "PLUS20_PROVED_RUNNER_CLASSIFIED_NORMAL_B"
        elif after != before and after == "NORMAL_B_PROVED_TIER2":
            event_type = "NORMAL_B_PROVED_TIER2"
            event_result = "FLOOR_ACTIVE"
            reason = "MFE_CROSSED_ABOVE_30"
        elif after != before and after == "NORMAL_B_PROVED_TIER3":
            event_type = "NORMAL_B_PROVED_TIER3"
            event_result = "RATCHET_ACTIVE"
            reason = "MFE_CROSSED_ABOVE_45"
        if event_type is None:
            return

        candidate_points = result.get("pnl_points", result.get("close_points"))
        evidence = {
            key: value for key, value in result.items()
            if key not in {"timestamp", "state"}
        }
        evidence.update({
            "candidate_only": True,
            "baseline_lifecycle_unchanged": True,
            "action_intent": "SHADOW_VALUATION_ONLY",
            "order_sent": False,
        })
        self.engine._audit(
            runtime=rr.runtime,
            timestamp=obs.timestamp,
            event_type=event_type,
            direction=rr.runtime.lifecycle.direction,
            result=event_result,
            reason=reason,
            state_before=before,
            state_after=after,
            observation=obs,
            directional_points=candidate_points,
            evidence=evidence,
        )

    def _observe_new_entry_health(
        self,
        *,
        ts: datetime,
        obs: FamilyBObservation,
        previous_obs: FamilyBObservation | None,
        previous_raw: dict | None,
        entry_raw: dict | None,
    ) -> None:
        """Log causal T-1 and entry-close health for a newly active trade."""
        if not self.config.pre_entry_health_observation_enabled:
            return
        if self.state is None or self.state.active_reference_type is None:
            return
        rr = self.state.references.get(self.state.active_reference_type)
        lifecycle = rr.runtime.lifecycle if rr is not None else None
        if (
            rr is None or lifecycle is None or rr.entry_health_logged
            or lifecycle.entry_timestamp != ts
        ):
            return
        rr.entry_health_logged = True
        common = {
            "candidate_only": True,
            "entry_blocked": False,
            "baseline_lifecycle_unchanged": True,
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        }
        for event_type, raw, source_obs, basis in (
            ("PRE_ENTRY_HEALTH_SNAPSHOT", previous_raw, previous_obs,
             "PREVIOUS_COMPLETED_ONE_MINUTE_CANDLE"),
            ("ENTRY_HEALTH_SNAPSHOT", entry_raw, obs,
             "COMPLETED_ENTRY_CANDLE"),
        ):
            if raw is None or source_obs is None:
                snapshot = {"available": False, "warmup_bars": None}
            else:
                snapshot = self.entry_health.directional_snapshot(
                    raw, lifecycle.direction
                )
            label = entry_health_label(snapshot)
            evidence = {
                **common, **snapshot, **label,
                "snapshot_timestamp": (
                    source_obs.timestamp if source_obs is not None else None
                ),
                "snapshot_basis": basis,
            }
            self.engine._audit(
                runtime=rr.runtime,
                timestamp=obs.timestamp,
                event_type=event_type,
                direction=lifecycle.direction,
                result=label["health"],
                reason=(
                    "CAUSAL_DIRECTIONAL_HEALTH_OBSERVED"
                    if snapshot.get("available")
                    else "INDICATOR_WARMUP_INCOMPLETE"
                ),
                state_before=lifecycle.state.value,
                state_after=lifecycle.state.value,
                observation=source_obs,
                directional_points=(
                    self._directional_points(rr, source_obs.close)
                    if source_obs is not None else None
                ),
                evidence=evidence,
            )

    def _observe_t5_health(
        self,
        rr: _ReferenceRuntime,
        obs: FamilyBObservation,
        health_raw: dict | None,
    ) -> None:
        """Emit parallel T+5 evidence without mutating the canonical lifecycle."""
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None or rr.t5_health_checked:
            return
        current = datetime.fromisoformat(obs.timestamp)
        target = lifecycle.entry_timestamp + timedelta(minutes=5)
        if current < target:
            return
        rr.t5_health_checked = True
        points = self._directional_points(rr, obs.close)
        common = {
            "required_timestamp": target.isoformat(),
            "candidate_only": True,
            "baseline_lifecycle_unchanged": True,
            "action_intent": "SHADOW_VALUATION_ONLY",
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        }
        if current != target:
            self.engine._audit(
                runtime=rr.runtime, timestamp=obs.timestamp,
                event_type="T5_HEALTH_UNAVAILABLE", direction=lifecycle.direction,
                result="UNAVAILABLE", reason="EXACT_ENTRY_PLUS5_MINUTE_MISSING",
                state_before=lifecycle.state.value, state_after=lifecycle.state.value,
                observation=obs, directional_points=points, evidence=common,
            )
            return
        if lifecycle.plus20_timestamp is not None:
            self.engine._audit(
                runtime=rr.runtime, timestamp=obs.timestamp,
                event_type="T5_PROVED_BYPASS", direction=lifecycle.direction,
                result="BYPASSED", reason="PLUS20_PROOF_REACHED_ON_OR_BEFORE_T5",
                state_before=lifecycle.state.value, state_after=lifecycle.state.value,
                observation=obs, directional_points=points,
                evidence={**common, "plus20_timestamp": lifecycle.plus20_timestamp.isoformat()},
            )
            return
        if health_raw is None:
            snapshot = {"available": False, "warmup_bars": None}
        else:
            snapshot = self.entry_health.directional_snapshot(
                health_raw, lifecycle.direction
            )
        decision = evaluate_t5_candidates(snapshot)
        evidence = {**common, **snapshot, **decision, "valuation_price": obs.close,
                    "valuation_basis": "OBSERVED_COMPLETED_CANDLE_CLOSE"}
        if not decision["available"]:
            self.engine._audit(
                runtime=rr.runtime, timestamp=obs.timestamp,
                event_type="T5_HEALTH_UNAVAILABLE", direction=lifecycle.direction,
                result="UNAVAILABLE", reason="INDICATOR_WARMUP_INCOMPLETE",
                state_before=lifecycle.state.value, state_after=lifecycle.state.value,
                observation=obs, directional_points=points, evidence=evidence,
            )
            return
        self.engine._audit(
            runtime=rr.runtime, timestamp=obs.timestamp,
            event_type="T5_HEALTH_CHECK", direction=lifecycle.direction,
            result="OBSERVED", reason="EXACT_ENTRY_PLUS5_COMPLETED_CLOSE",
            state_before=lifecycle.state.value, state_after=lifecycle.state.value,
            observation=obs, directional_points=points, evidence=evidence,
        )
        if self.config.t5_two_of_three_candidate_enabled and decision["two_of_three"]:
            self.engine._audit(
                runtime=rr.runtime, timestamp=obs.timestamp,
                event_type="T5_TWO_OF_THREE_EXIT_CANDIDATE",
                direction=lifecycle.direction, result="SHADOW_EXIT_CANDIDATE",
                reason="TWO_OF_THREE_HEALTH_FAILURES",
                state_before=lifecycle.state.value, state_after=lifecycle.state.value,
                observation=obs, directional_points=points, evidence=evidence,
            )
        if self.config.t5_combined_edge_candidate_enabled and decision["combined_edge"]:
            self.engine._audit(
                runtime=rr.runtime, timestamp=obs.timestamp,
                event_type="T5_COMBINED_EDGE_EXIT_CANDIDATE",
                direction=lifecycle.direction, result="SHADOW_EXIT_CANDIDATE",
                reason="COMBINED_DIRECTIONAL_EDGE_NOT_POSITIVE",
                state_before=lifecycle.state.value, state_after=lifecycle.state.value,
                observation=obs, directional_points=points, evidence=evidence,
            )

    def _process_management(
        self,
        rr: _ReferenceRuntime,
        obs: FamilyBObservation,
        prev_obs: FamilyBObservation | None,
        underlying,
        health_raw: dict | None = None,
    ) -> bool:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None or rr.closed:
            return False

        if self.config.be_rearm_enabled:
            self._observe_be_rearm_touch(rr, obs, underlying)
        else:
            self._observe_c_touch(rr, obs, underlying)

        candidate = (
            self._ensure_normal_b_proved_candidate(rr)
            if self.config.normal_b_proved_candidate_enabled else None
        )
        current_ts = datetime.fromisoformat(obs.timestamp)
        candidate_target = (
            candidate.proof_timestamp + timedelta(minutes=10)
            if candidate is not None
            and candidate.proof_timestamp is not None
            and candidate.classified_at is None
            else None
        )
        candidate_waits_for_classifier = candidate_target == current_ts
        if candidate is not None and (
            candidate_target is not None
            and current_ts > candidate_target
            and candidate.classified_at is None
        ):
            rr.normal_b_proved_unavailable = True
            self.engine._audit(
                runtime=rr.runtime,
                timestamp=obs.timestamp,
                event_type="NORMAL_B_PROVED_UNAVAILABLE",
                direction=lifecycle.direction,
                result="UNAVAILABLE",
                reason="EXACT_PLUS20_PLUS10_MINUTE_MISSING",
                state_before=candidate.state,
                state_after="UNAVAILABLE",
                observation=obs,
                directional_points=self._directional_points(rr, obs.close),
                evidence={"required_timestamp": candidate_target.isoformat(),
                          "candidate_only": True, "order_sent": False},
            )
        elif candidate is not None and not candidate_waits_for_classifier:
            self._observe_normal_b_proved(rr, obs, underlying)

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
            self._observe_t5_health(rr, obs, health_raw)
            return False

        self._observe_t5_health(rr, obs, health_raw)

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
                rr.management_route = (
                    "RUNNER_DEGRADED_EXIT"
                    if lifecycle.runner_strengthening
                    else "NORMAL_B_PROVED_THREE_TIER"
                )
                self.engine._audit(
                    runtime=rr.runtime,
                    timestamp=obs.timestamp,
                    event_type="MANAGEMENT_ROUTE_SELECTED",
                    direction=lifecycle.direction,
                    result=rr.management_route,
                    reason=(
                        "EXACT_PLUS20_PLUS10_RUNNER_STRENGTHENING"
                        if lifecycle.runner_strengthening
                        else "EXACT_PLUS20_PLUS10_NORMAL_B"
                    ),
                    state_before=lifecycle.state.value,
                    state_after=lifecycle.state.value,
                    observation=obs,
                    directional_points=points,
                    evidence={
                        "exclusive_route": True,
                        "candidate_only": True,
                        "baseline_lifecycle_unchanged": True,
                        "order_sent": False,
                    },
                )
                if self.config.normal_b_proved_candidate_enabled:
                    self._observe_normal_b_proved(
                        rr,
                        obs,
                        underlying,
                        classifier_result=(
                            "RUNNER_STRENGTHENING"
                            if lifecycle.runner_strengthening else "NORMAL_B"
                        ),
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
                if (
                    self.config.degraded_exit_candidate_enabled
                    and rr.management_route == "RUNNER_DEGRADED_EXIT"
                    and rr.degraded_exit_candidate_timestamp is None
                ):
                    rr.degraded_exit_candidate_timestamp = current_ts
                    self.engine._audit(
                        runtime=rr.runtime,
                        timestamp=obs.timestamp,
                        event_type="DEGRADED_EXIT_CANDIDATE_TRIGGERED",
                        direction=lifecycle.direction,
                        result="SHADOW_EXIT_CANDIDATE",
                        reason="FIRST_DEGRADED_STARTED_COMPLETED_CLOSE",
                        state_before="RUNNER_STRENGTHENING",
                        state_after="CANDIDATE_CLOSED",
                        observation=obs,
                        directional_points=points,
                        evidence={
                            "management_route": rr.management_route,
                            "signal_timestamp": obs.timestamp,
                            "option_valuation_timestamp": (
                                current_ts + timedelta(minutes=1)
                            ).isoformat(),
                            "option_valuation_basis": "NEXT_EXACT_OPTION_MINUTE_OPEN",
                            "candidate_only": True,
                            "baseline_lifecycle_unchanged": True,
                            "no_candidate_reentry": True,
                            "action_intent": "SHADOW_VALUATION_ONLY",
                            "order_sent": False,
                        },
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

    def _v621_read_new_audit_events(self) -> list[dict]:
        if self._v621_collector is None or not self._audit_path.exists():
            return []

        events: list[dict] = []
        with self._audit_path.open("rb") as fh:
            fh.seek(self._v621_audit_offset)
            payload = fh.read()
            self._v621_audit_offset = fh.tell()

        for raw in payload.splitlines():
            if not raw.strip():
                continue
            try:
                events.append(json.loads(raw.decode("utf-8")))
            except Exception:
                # Research sidecar must never interrupt live-shadow processing.
                continue
        return events

    def _v621_observe_completed_minute(self, *, ts: datetime, underlying) -> None:
        if self._v621_collector is None:
            return

        events = self._v621_read_new_audit_events()

        # Feed non-terminal audit events first so a newly-created re-entry exists
        # before future candles are evaluated. Then feed this completed candle.
        # Feed STRUCTURAL_TERMINAL last so R1/R2 can still react to the terminal
        # candle's completed OHLC before the research case is finalized.
        terminal_events = []
        for event in events:
            if event.get("event_type") == "STRUCTURAL_TERMINAL":
                terminal_events.append(event)
            else:
                self._v621_collector.on_audit_event(event)

        self._v621_collector.on_completed_underlying_candle(
            timestamp=ts.isoformat(),
            high=self._float(underlying, "high"),
            low=self._float(underlying, "low"),
            close=self._float(underlying, "close"),
        )

        for event in terminal_events:
            self._v621_collector.on_audit_event(event)

    def _build_pm_e_reference_if_ready(
        self, *, ts: datetime, underlying_by_ts: dict[datetime, Any]
    ) -> None:
        if (
            not self.config.pm_e_enabled
            or self.state is None
            or self.state.pm_e_candidate is not None
            or ts.time() != time(13, 14)
        ):
            return
        start = ts.replace(hour=12, minute=45)
        minutes = [start + timedelta(minutes=index) for index in range(30)]
        if not all(minute in underlying_by_ts for minute in minutes):
            return
        rows = [underlying_by_ts[minute] for minute in minutes]
        high = max(self._float(row, "high") for row in rows)
        low = min(self._float(row, "low") for row in rows)
        open_price = self._float(rows[0], "open")
        close_price = self._float(rows[-1], "close")
        reference = ReferenceStructure(
            session_date=self.state.session_date.isoformat(),
            reference_type="GREEN" if close_price >= open_price else "RED",
            start_timestamp=start.isoformat(),
            end_timestamp=ts.isoformat(),
            high=high,
            low=low,
        )
        self.state.pm_e_candidate = PMMidpointBECandidate(
            session_date=self.state.session_date.isoformat(),
            reference_start=start,
            reference_end=ts,
            high=high,
            low=low,
        )
        self.state.pm_e_runtime = MidpointFamilyBRuntime(
            reference=reference, family=MidpointFamily.PM_E
        )
        self.engine._audit(
            runtime=self.state.pm_e_runtime,
            timestamp=ts.isoformat(),
            event_type="PM_REFERENCE_LOCKED",
            direction=None,
            result="LOCKED",
            reason="EXACT_1245_TO_1314_COMPLETED_WINDOW",
            evidence={
                "reference_row_count": 30,
                "reference_high": high,
                "reference_low": low,
                "reference_midpoint": (high + low) / 2.0,
                "candidate_only": True,
                "order_sent": False,
            },
        )

    def _start_be_rearm_entry(
        self,
        *,
        key: str,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
        owner: str,
        reason: str,
    ) -> None:
        if self.state is None or owner not in {"B", "E"}:
            raise ValueError("B/E rearm entry requires canonical B or E owner")
        if runtime.lifecycle is not None:
            raise ValueError("B/E rearm lifecycle already active")
        family = MidpointFamily.B if owner == "B" else MidpointFamily.E
        runtime.family = family
        runtime.watch = None
        runtime.lifecycle = FamilyBShadowRuntime(
            direction=runtime.reference.direction,
            entry_timestamp=datetime.fromisoformat(obs.timestamp),
            entry_underlying_close=obs.close,
            family=family,
            state=MidpointShadowState.ACTIVE,
        )
        meta = self.state.be_rearm_meta[key]
        self.engine._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type=f"{owner}_REARM_ENTRY",
            direction=runtime.reference.direction,
            result="SHADOW_ENTRY",
            reason=reason,
            state_before="BE_REARM_BOUNDARY_CLASSIFIED",
            state_after="ACTIVE",
            observation=obs,
            directional_points=0.0,
            evidence={
                **meta,
                "qualification_owner": owner,
                "rearm_type": "MIDPOINT_TOUCH_REVALIDATION",
                "action_intent": "SHADOW_ENTRY",
                "order_sent": False,
            },
        )

    def _start_be_rearm_watch(
        self,
        *,
        key: str,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
    ) -> None:
        if self.state is None:
            return
        runtime.family = MidpointFamily.B
        runtime.watch = self.engine.detector.start_watch(
            runtime.reference, obs, self.state.observations[-12:]
        )
        self.engine._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="B_REARM_WATCH_STARTED",
            direction=runtime.reference.direction,
            result="STARTED" if runtime.watch.active else "NOT_STARTED",
            reason="FRESH_BOUNDARY_CLASSIFIED_B",
            observation=obs,
            evidence={**self.state.be_rearm_meta[key], "order_sent": False},
        )

    def _evaluate_be_rearm_watch(
        self,
        *,
        key: str,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
    ) -> str:
        if self.state is None or runtime.watch is None:
            raise ValueError("active B rearm watch required")
        decision = self.engine.detector.evaluate(
            runtime.watch, obs, self.state.observations[-12:]
        )
        self.engine._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="B_REARM_CONFIRMATION_CHECK",
            direction=runtime.reference.direction,
            result=decision.result,
            reason=decision.reason,
            observation=obs,
            evidence={
                **self.state.be_rearm_meta[key],
                "full_candidate_a": decision.full_candidate_a,
                "directional_vwap_diff": decision.directional_vwap_diff,
                "prior_window_crossed_threshold": (
                    decision.prior_window_crossed_threshold
                ),
                "still_beyond_original_boundary": (
                    decision.still_beyond_original_boundary
                ),
                "structure_valid": decision.structure_valid,
                "minutes_since_boundary_break": (
                    decision.minutes_since_boundary_break
                ),
                "order_sent": False,
            },
        )
        if decision.result == "ENTRY":
            runtime.watch = None
            self._start_be_rearm_entry(
                key=key,
                runtime=runtime,
                obs=obs,
                owner="B",
                reason="DELAYED_FULL_CANDIDATE_A_AFTER_MIDPOINT_REARM",
            )
        return decision.result

    def _process_be_rearms(
        self,
        *,
        obs: FamilyBObservation,
        prev_obs: FamilyBObservation,
        terminal_this_minute: bool,
    ) -> None:
        if not self.config.be_rearm_enabled or self.state is None:
            return
        for key, candidate in list(self.state.be_rearms.items()):
            runtime = self.state.be_rearm_runtimes[key]
            watch_key = f"BE_REARM:{key}"
            rr = self.state.references.get(watch_key)
            if (
                rr is not None
                and runtime.watch is not None
                and runtime.lifecycle is None
                and runtime.watch.active
                and self.state.active_reference_type is None
                and not terminal_this_minute
            ):
                result = self._evaluate_be_rearm_watch(
                    key=key, runtime=runtime, obs=obs
                )
                if result == "ENTRY":
                    self.state.active_reference_type = watch_key
                    rr.running_close_mfe = 0.0
                continue
            if runtime.watch is not None or runtime.lifecycle is not None:
                continue
            action = candidate.observe_after_close(
                timestamp=datetime.fromisoformat(obs.timestamp),
                previous_close=prev_obs.close,
                close=obs.close,
            )
            if action is None:
                continue
            decision = self.boundary_classifier.classify(
                reference=candidate.reference,
                boundary_observation=obs,
                history=self.state.observations[-12:],
            )
            self.engine._audit(
                runtime=runtime,
                timestamp=obs.timestamp,
                event_type="BE_REARM_BOUNDARY_CLASSIFIED",
                direction=action.direction,
                result=decision.owner,
                reason=decision.reason,
                observation=obs,
                evidence={
                    **self.state.be_rearm_meta[key],
                    "midpoint_touch_timestamp": (
                        candidate.midpoint_touch_timestamp.isoformat()
                    ),
                    "origin_closed_timestamp": (
                        candidate.origin_closed_timestamp.isoformat()
                    ),
                    "fresh_boundary_break": True,
                    "candidate_a_at_boundary": decision.candidate_a_at_boundary,
                    "order_sent": False,
                },
            )
            generation = int(self.state.be_rearm_meta[key]["generation"])
            self.state.references[watch_key] = _ReferenceRuntime(
                reference=candidate.reference,
                runtime=runtime,
                generation=generation,
            )
            blocked = terminal_this_minute or (
                self.state.active_reference_type is not None
            )
            if blocked:
                self.engine._audit(
                    runtime=runtime,
                    timestamp=obs.timestamp,
                    event_type="BE_REARM_ENTRY_BLOCKED",
                    direction=action.direction,
                    result="NO_ENTRY",
                    reason=(
                        "SAME_CANDLE_REARM_BLOCKED"
                        if terminal_this_minute else "ANOTHER_REFERENCE_ACTIVE"
                    ),
                    observation=obs,
                    evidence={**self.state.be_rearm_meta[key], "order_sent": False},
                )
            elif decision.owner == MidpointFamily.E.value:
                self._start_be_rearm_entry(
                    key=key,
                    runtime=runtime,
                    obs=obs,
                    owner="E",
                    reason="MATURE_DIRECTIONAL_VWAP_AFTER_MIDPOINT_REARM",
                )
                self.state.active_reference_type = watch_key
            elif decision.owner == MidpointFamily.B.value:
                self._start_be_rearm_watch(key=key, runtime=runtime, obs=obs)
            else:
                self.engine._audit(
                    runtime=runtime,
                    timestamp=obs.timestamp,
                    event_type="BE_REARM_ENTRY_REJECTED",
                    direction=action.direction,
                    result="NO_ENTRY",
                    reason="FRESH_CANDIDATE_A_AT_BOUNDARY",
                    observation=obs,
                    evidence={**self.state.be_rearm_meta[key], "order_sent": False},
                )

    def _start_pm_b_watch(
        self,
        *,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
    ) -> None:
        runtime.family = MidpointFamily.PM_B
        runtime.watch = self.engine.detector.start_watch(
            runtime.reference, obs, self.state.observations[-12:]
        )
        self.engine._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="PM_B_WATCH_STARTED",
            direction=runtime.reference.direction,
            result="STARTED" if runtime.watch.active else "NOT_STARTED",
            reason="PM_BOUNDARY_CLASSIFIED_B",
            observation=obs,
            evidence={"qualification_owner": "B", "order_sent": False},
        )

    def _evaluate_pm_b_watch(
        self,
        *,
        runtime: MidpointFamilyBRuntime,
        obs: FamilyBObservation,
    ) -> str:
        if runtime.watch is None:
            raise ValueError("active PM_B watch required")
        decision = self.engine.detector.evaluate(
            runtime.watch, obs, self.state.observations[-12:]
        )
        self.engine._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type="PM_B_CONFIRMATION_CHECK",
            direction=runtime.reference.direction,
            result=decision.result,
            reason=decision.reason,
            observation=obs,
            evidence={
                "qualification_owner": "B",
                "full_candidate_a": decision.full_candidate_a,
                "directional_vwap_diff": decision.directional_vwap_diff,
                "prior_window_crossed_threshold": (
                    decision.prior_window_crossed_threshold
                ),
                "still_beyond_original_boundary": (
                    decision.still_beyond_original_boundary
                ),
                "structure_valid": decision.structure_valid,
                "minutes_since_boundary_break": (
                    decision.minutes_since_boundary_break
                ),
                "order_sent": False,
            },
        )
        if decision.result == "ENTRY":
            runtime.watch = None
            self.engine.start_extended_entry(
                runtime,
                obs,
                family=MidpointFamily.PM_B,
                qualification_owner="B",
                reason="PM_DELAYED_FULL_CANDIDATE_A",
                state_before="PM_B_WATCH",
            )
        return decision.result

    def _process_extended_entries(
        self,
        *,
        ts: datetime,
        obs: FamilyBObservation,
        prev_obs: FamilyBObservation | None,
        terminal_this_minute: bool,
    ) -> None:
        if self.state is None or prev_obs is None:
            return

        self._process_be_rearms(
            obs=obs,
            prev_obs=prev_obs,
            terminal_this_minute=terminal_this_minute,
        )

        if self.config.family_c_enabled:
            for source_key, candidate in list(self.state.c_rearms.items()):
                runtime = self.state.c_runtimes[source_key]
                watch_key = f"C:{source_key}"
                rr = self.state.references.get(watch_key)
                if (
                    rr is not None
                    and runtime.watch is not None
                    and runtime.lifecycle is None
                    and runtime.watch.active
                    and self.state.active_reference_type is None
                    and not terminal_this_minute
                ):
                    result = self.engine.evaluate_extended_watch(
                        runtime, obs, self.state.observations[-12:]
                    )
                    if result == "ENTRY":
                        self.state.active_reference_type = watch_key
                        rr.running_close_mfe = 0.0
                    continue
                if runtime.watch is not None or runtime.lifecycle is not None:
                    continue
                action = candidate.observe_after_close(
                    timestamp=ts,
                    previous_close=prev_obs.close,
                    close=obs.close,
                )
                if action is None:
                    continue
                decision = self.boundary_classifier.classify(
                    reference=candidate.reference,
                    boundary_observation=obs,
                    history=self.state.observations[-12:],
                )
                self.engine._audit(
                    runtime=runtime,
                    timestamp=obs.timestamp,
                    event_type="C_BOUNDARY_CLASSIFIED",
                    direction=action.direction,
                    result=decision.owner,
                    reason=decision.reason,
                    observation=obs,
                    evidence={
                        "midpoint_touch_timestamp":
                            candidate.midpoint_touch_timestamp.isoformat(),
                        "origin_closed_timestamp":
                            candidate.origin_closed_timestamp.isoformat(),
                        "fresh_boundary_break": True,
                        "candidate_a_at_boundary":
                            decision.candidate_a_at_boundary,
                        "order_sent": False,
                    },
                )
                self.state.references[watch_key] = _ReferenceRuntime(
                    reference=candidate.reference, runtime=runtime
                )
                blocked = terminal_this_minute or (
                    self.state.active_reference_type is not None
                )
                if blocked:
                    self.engine._audit(
                        runtime=runtime,
                        timestamp=obs.timestamp,
                        event_type="C_ENTRY_BLOCKED",
                        direction=action.direction,
                        result="NO_ENTRY",
                        reason=(
                            "SAME_CANDLE_REVERSAL_BLOCKED"
                            if terminal_this_minute
                            else "ANOTHER_REFERENCE_ACTIVE"
                        ),
                        observation=obs,
                        evidence={"order_sent": False},
                    )
                elif decision.owner == MidpointFamily.E.value:
                    self.engine.start_extended_entry(
                        runtime,
                        obs,
                        family=MidpointFamily.C,
                        qualification_owner="E",
                    )
                    self.state.active_reference_type = watch_key
                elif decision.owner == MidpointFamily.B.value:
                    self.engine.start_extended_watch(
                        runtime,
                        obs,
                        self.state.observations[-12:],
                        family=MidpointFamily.C,
                    )
                else:
                    self.engine._audit(
                        runtime=runtime,
                        timestamp=obs.timestamp,
                        event_type="C_ENTRY_REJECTED",
                        direction=action.direction,
                        result="NO_ENTRY",
                        reason="FRESH_CANDIDATE_A_AT_BOUNDARY",
                        observation=obs,
                        evidence={"order_sent": False},
                    )

        candidate = self.state.pm_e_candidate
        runtime = self.state.pm_e_runtime
        if not self.config.pm_e_enabled or candidate is None or runtime is None:
            return

        pm_key = "PM_B"
        pm_rr = self.state.references.get(pm_key)
        if (
            pm_rr is not None
            and runtime.watch is not None
            and runtime.lifecycle is None
            and runtime.watch.active
            and self.state.active_reference_type is None
            and not terminal_this_minute
        ):
            if ts.time() >= time(15, 15):
                runtime.watch.active = False
                self.engine._audit(
                    runtime=runtime,
                    timestamp=obs.timestamp,
                    event_type="PM_ENTRY_WINDOW_EXPIRED",
                    direction=runtime.reference.direction,
                    result="NO_ENTRY",
                    reason="NO_PM_ENTRY_AT_OR_AFTER_1515",
                    observation=obs,
                    evidence={
                        "entry_cutoff": "15:15",
                        "pending_owner": "B",
                        "order_sent": False,
                    },
                )
                return
            result = self._evaluate_pm_b_watch(runtime=runtime, obs=obs)
            if result == "ENTRY":
                self.state.active_reference_type = pm_key
                pm_rr.running_close_mfe = 0.0
            return
        if runtime.watch is not None or runtime.lifecycle is not None:
            return

        actions = candidate.observe(
            timestamp=ts, previous_close=prev_obs.close, close=obs.close
        )
        for action in actions:
            if action.event_type == "PM_MIDPOINT_BREAK":
                runtime.reference = candidate.directional_reference(action.direction)
                self.engine._audit(
                    runtime=runtime,
                    timestamp=obs.timestamp,
                    event_type=action.event_type,
                    direction=action.direction,
                    result="CONFIRMED_CLOSE",
                    reason=action.reason,
                    observation=obs,
                    evidence={
                        "midpoint_break_timestamp": obs.timestamp,
                        "midpoint_break_direction": action.direction,
                        "reference_midpoint": candidate.midpoint,
                        "order_sent": False,
                    },
                )
                continue
            if action.event_type == "PM_ENTRY_WINDOW_EXPIRED":
                self.engine._audit(
                    runtime=runtime,
                    timestamp=obs.timestamp,
                    event_type=action.event_type,
                    direction=action.direction,
                    result="NO_ENTRY",
                    reason=action.reason,
                    observation=obs,
                    evidence={"entry_cutoff": "15:15", "order_sent": False},
                )
                continue
            if action.event_type != "PM_BOUNDARY_BREAK":
                raise AssertionError(f"unsupported PM action: {action.event_type}")

            reference = candidate.directional_reference()
            runtime.reference = reference
            decision = self.boundary_classifier.classify(
                reference=reference,
                boundary_observation=obs,
                history=self.state.observations[-12:],
            )
            self.engine._audit(
                runtime=runtime,
                timestamp=obs.timestamp,
                event_type="PM_BOUNDARY_CLASSIFIED",
                direction=action.direction,
                result=decision.owner,
                reason=decision.reason,
                observation=obs,
                evidence={
                    "midpoint_break_timestamp": (
                        (
                            candidate.bearish_midpoint_break_timestamp
                            if action.direction == "BEARISH"
                            else candidate.bullish_midpoint_break_timestamp
                        ).isoformat()
                    ),
                    "boundary_break_timestamp": (
                        candidate.boundary_break_timestamp.isoformat()
                    ),
                    "candidate_a_at_boundary": decision.candidate_a_at_boundary,
                    "prior_window_crossed_threshold": (
                        decision.prior_window_crossed_threshold
                    ),
                    "raw_futures_vwap_diff": decision.raw_futures_vwap_diff,
                    "directional_vwap_diff": decision.directional_vwap_diff,
                    "order_sent": False,
                },
            )
            blocked_reason = None
            if terminal_this_minute:
                blocked_reason = "SAME_CANDLE_TERMINAL_BLOCKED"
            elif self.state.active_reference_type is not None:
                blocked_reason = "ANOTHER_REFERENCE_ACTIVE"
            if blocked_reason is not None:
                self.engine._audit(
                    runtime=runtime,
                    timestamp=obs.timestamp,
                    event_type="PM_ENTRY_BLOCKED",
                    direction=action.direction,
                    result="NO_ENTRY",
                    reason=blocked_reason,
                    observation=obs,
                    evidence={"owner": decision.owner, "order_sent": False},
                )
                continue

            if decision.owner == MidpointFamily.E.value:
                key = "PM_E"
                runtime.family = MidpointFamily.PM_E
                self.state.references[key] = _ReferenceRuntime(
                    reference=reference, runtime=runtime
                )
                self.engine.start_extended_entry(
                    runtime,
                    obs,
                    family=MidpointFamily.PM_E,
                    qualification_owner="E",
                )
                self.state.active_reference_type = key
            elif decision.owner == MidpointFamily.B.value:
                runtime.family = MidpointFamily.PM_B
                self.state.references[pm_key] = _ReferenceRuntime(
                    reference=reference, runtime=runtime
                )
                self._start_pm_b_watch(runtime=runtime, obs=obs)
            else:
                self.engine._audit(
                    runtime=runtime,
                    timestamp=obs.timestamp,
                    event_type="PM_ENTRY_REJECTED",
                    direction=action.direction,
                    result="NO_ENTRY",
                    reason="FRESH_CANDIDATE_A_AT_BOUNDARY",
                    observation=obs,
                    evidence={"owner": decision.owner, "order_sent": False},
                )

    def _process_minute(
        self,
        *,
        ts: datetime,
        underlying,
        futures_close: float,
        futures_vwap: float,
        underlying_by_ts: dict[datetime, Any],
        futures_open: float | None = None,
        futures_volume: float | None = None,
    ) -> None:
        assert self.state is not None

        self._build_reference_if_ready(ts=ts, underlying_by_ts=underlying_by_ts)
        self._build_pm_e_reference_if_ready(
            ts=ts, underlying_by_ts=underlying_by_ts
        )

        obs = FamilyBObservation(
            timestamp=ts.isoformat(),
            close=self._float(underlying, "close"),
            futures_price=futures_close,
            futures_vwap=futures_vwap,
        )
        prev_obs = self.state.observations[-1] if self.state.observations else None
        self.state.observations.append(obs)
        preentry_health_raw = self.latest_entry_health_raw
        health_raw = self.entry_health.update(
            timestamp=ts,
            open_=self._float(underlying, "open"),
            high=self._float(underlying, "high"),
            low=self._float(underlying, "low"),
            close=self._float(underlying, "close"),
            futures_open=futures_open,
            futures_close=futures_close,
            futures_vwap=futures_vwap,
            futures_volume=futures_volume,
        )
        self.latest_entry_health_raw = health_raw

        terminal_this_minute = False

        active_type = self.state.active_reference_type
        if active_type is not None:
            active_rr = self.state.references.get(active_type)
            if active_rr is not None and active_rr.runtime.lifecycle is not None:
                terminal_this_minute = self._process_management(
                    active_rr, obs, prev_obs, underlying, health_raw
                )
                if active_rr.closed:
                    self.state.active_reference_type = None

        # V57.1 parity rule:
        # A structural terminal does not suppress opposite-structure
        # observation on the same completed 1m candle. Same-candle
        # reversal entry remains prohibited below.
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
                    history=self.state.observations[-12:],
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
                    if terminal_this_minute:
                        self.engine._audit(
                            runtime=rr.runtime,
                            timestamp=obs.timestamp,
                            event_type="E_ENTRY_BLOCKED",
                            direction=rr.reference.direction,
                            result="NO_ENTRY",
                            reason="SAME_CANDLE_REVERSAL_BLOCKED",
                            observation=obs,
                            evidence={
                                "family_selected": "E",
                                "same_candle_structural_terminal": True,
                                "order_sent": False,
                            },
                        )
                        continue

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
                        self.state.observations[-12:],
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
                and not terminal_this_minute
            ):
                result = self.engine.evaluate_b_watch(
                    rr.runtime,
                    obs,
                    self.state.observations[-12:],
                )
                if result == "ENTRY":
                    self.state.active_reference_type = ref_type
                    rr.running_close_mfe = 0.0

        self._process_extended_entries(
            ts=ts,
            obs=obs,
            prev_obs=prev_obs,
            terminal_this_minute=terminal_this_minute,
        )
        self._observe_new_entry_health(
            ts=ts,
            obs=obs,
            previous_obs=prev_obs,
            previous_raw=preentry_health_raw,
            entry_raw=health_raw,
        )

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
        futures_by_ts: dict[datetime, Any] = {}
        for candle in sorted(futures, key=self._candle_ts):
            candle_ts = self._candle_ts(candle)
            if candle_ts <= latest:
                futures_by_ts.setdefault(candle_ts, candle)

        common = sorted(set(underlying_by_ts).intersection(futures_map))

        processed_now = 0
        for ts in common:
            if ts in self.state.processed_minutes:
                continue
            if self.state.latest_processed_minute is not None and ts < self.state.latest_processed_minute:
                self.state.quarantined_late_minutes.add(ts)
                continue
            if ts.time() < time(9, 15):
                self.state.processed_minutes.add(ts)
                continue

            f_close, f_vwap = futures_map[ts]
            future = futures_by_ts.get(ts)
            self._process_minute(
                ts=ts,
                underlying=underlying_by_ts[ts],
                futures_close=f_close,
                futures_vwap=f_vwap,
                underlying_by_ts=underlying_by_ts,
                futures_open=(self._float(future, "open") if future else None),
                futures_volume=(self._volume(future) if future else None),
            )
            self._v621_observe_completed_minute(
                ts=ts,
                underlying=underlying_by_ts[ts],
            )
            self.state.processed_minutes.add(ts)
            self.state.latest_processed_minute = ts
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
            "quarantined_late_minutes": len(self.state.quarantined_late_minutes),
            "quarantined_revised_futures_minutes": len(self.state.quarantined_revised_futures_minutes),
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
