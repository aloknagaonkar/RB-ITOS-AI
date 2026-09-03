from __future__ import annotations

from red_bar_lab.observability import record_strategy_subcheck

from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable

import pandas as pd

from red_bar_lab.execution.red_bar_v2_admission_policy import (
    AdmissionCode,
    evaluate_candidate_admission,
)
from red_bar_lab.execution.trade_state_observer import observe_trade_state
from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    RedBarV2FuturesSnapshot,
    RedBarV2VwapSourceHealth,
    build_red_bar_v2_futures_snapshot,
)
from red_bar_lab.services.red_bar_v2_canonical.evidence_producer import (
    build_legacy_v2_decision_evidence,
    evidence_to_event_details,
)
from red_bar_lab.services.red_bar_v2_historical_replay import (
    RedBarV2ReplayResult,
    ReplayEvent,
    _event_is_due,
    _normalise,
    _trade_row,
)
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2Reference,
    RedBarV2State,
    annotate_reference_vwap_position,
    build_red_bar_v2_reference,
    evaluate_midpoint_upgrade,
)
from red_bar_lab.strategy.red_bar_v2_futures import (
    evaluate_initial_direction_futures,
    evaluate_reversal_direction_futures,
    evaluate_working_reference_direction_futures,
)
from red_bar_lab.strategy.red_bar_v2_working_reference import (
    RedBarV2WorkingReference,
    build_working_reference,
    select_governing_reference,
)


def replay_red_bar_v2_day_with_futures_vwap(
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    *,
    instrument_key: str,
    vwap_instrument_key: str,
    exit_timestamps: Iterable[datetime | pd.Timestamp] = (),
    database: Any | None = None,
    run_id: str | None = None,
) -> tuple[RedBarV2ReplayResult, RedBarV2VwapSourceHealth]:
    """Replay Red Bar V2 with index RSI/midpoint and genuine futures VWAP."""
    frame = _normalise(index_candles)
    futures_frame = _normalise(futures_candles)
    exits = sorted(pd.Timestamp(value) for value in exit_timestamps)
    events: list[ReplayEvent] = []
    trade_rows: list[dict[str, object]] = []
    processed_candidates: set[str] = set()
    consumed_reversals: set[str] = set()
    processed_5m_contexts: set[str] = set()
    initial_processed = False
    pending_reversal: RedBarV2DirectionDecision | None = None
    pending_reversal_snapshot: RedBarV2FuturesSnapshot | None = None
    pending_reversal_health: RedBarV2VwapSourceHealth | None = None
    current_direction: str | None = None
    provisional_state: RedBarV2State | None = None
    waiting_for_red_bar_touch = False
    reentry_touch_state: str | None = None
    # The deputy that governs the space outside the red bar's band after an exit.
    # ``working_search_after`` is the exit moment the search runs from, and is
    # cleared the moment control returns to the red bar, so a deputy is never
    # revived by a later excursion -- only a fresh exit starts a fresh search.
    working_reference: RedBarV2WorkingReference | None = None
    working_search_after: pd.Timestamp | None = None
    working_search_direction: str | None = None
    reference = None
    exit_index = 0
    admitted = 0
    blocked = 0
    closed = 0
    latest_health: RedBarV2VwapSourceHealth | None = None

    # Observational rule-state accumulators (no effect on strategy logic).
    rule_reference: dict[str, object] | None = None
    annotated_reference: RedBarV2Reference | None = None
    initial_evaluations = 0
    initial_last_evaluated: str | None = None
    initial_last_result: str | None = None
    initial_last_reason: str | None = None
    initial_direction: str | None = None
    initial_established_at: str | None = None
    initial_admitted: bool | None = None
    reversal_5m_evaluations = 0
    reversal_detections = 0
    reversal_last_at: str | None = None
    reversal_last_direction: str | None = None
    # The grade, not the midpoint flag. Every admitted reversal now clears the
    # midpoint, so that flag can no longer tell CONFIRMED from PROVISIONAL.
    reversal_last_strength: str | None = None
    upgrade_count = 0
    upgrade_last_at: str | None = None
    upgrade_last_direction: str | None = None
    reentry_validated = 0
    reentry_failed = 0
    reentry_last_outcome: str | None = None
    reentry_last_outcome_at: str | None = None
    reentry_waiting_since: str | None = None
    reentry_last_touch_at: str | None = None
    reentry_last_touch_direction: str | None = None
    reentry_last_vwap_confirmed: bool | None = None
    reentry_last_direction: str | None = None
    working_established_at: str | None = None
    working_entries = 0
    working_discards = 0
    working_last_discarded_at: str | None = None
    last_admitted_at: str | None = None
    last_admission_code: str | None = None
    last_block_code: str | None = None
    last_block_reason: str | None = None
    last_block_at: str | None = None
    last_evaluation_iso: str | None = None

    for candle_timestamp in frame.index:
        evaluation_time = pd.Timestamp(candle_timestamp) + pd.Timedelta(minutes=1)
        last_evaluation_iso = evaluation_time.isoformat()

        while exit_index < len(exits) and exits[exit_index] <= evaluation_time:
            active = next((row for row in reversed(trade_rows) if row["status"] == "ACTIVE"), None)
            if active is not None:
                active["status"] = "CLOSED"
                active["exit_timestamp"] = exits[exit_index].to_pydatetime()
                active["updated_at"] = exits[exit_index].to_pydatetime()
                closed += 1
                events.append(ReplayEvent(
                    timestamp=exits[exit_index].to_pydatetime(),
                    event_type="TRADE_CLOSED",
                    direction=current_direction,
                    option_side=str(active.get("option_side") or "") or None,
                    admission_code=None,
                    candidate_allowed=None,
                    trade_id=str(active["trade_id"]),
                    details={"source": "REPLAY_EXIT_FIXTURE"},
                ))
                # A closed trade must not reverse immediately. A later
                # completed 1m candle must touch the fixed midpoint before the
                # normal initial-direction rules can create another entry.
                #
                # That wait used to be the only way out of a closed trade, which
                # left the strategy flat through any move that never came back to
                # the midpoint. Start a deputy search alongside it: the first
                # completed 5-minute candle of the opposite colour after this
                # moment can govern the space price has run off to, and the two
                # mechanisms cover disjoint locations, so neither can pre-empt the
                # other. The direction is read before ``current_direction`` is
                # cleared below; an exit with no recorded direction starts no
                # search rather than guessing one.
                working_search_direction = (
                    "BEARISH"
                    if current_direction == "BULLISH"
                    else "BULLISH"
                    if current_direction == "BEARISH"
                    else None
                )
                working_search_after = (
                    exits[exit_index] if working_search_direction is not None else None
                )
                working_reference = None
                waiting_for_red_bar_touch = True
                current_direction = None
                provisional_state = None
                pending_reversal = None
                pending_reversal_snapshot = None
                pending_reversal_health = None
                # Re-entry touch state: which level the system is
                # currently waiting for confirmation on.
                reentry_touch_state = "waiting_midpoint"
                reentry_waiting_since = exits[exit_index].to_pydatetime().isoformat()
                reentry_last_vwap_confirmed = None
            exit_index += 1

        if annotated_reference is None:
            reference = build_red_bar_v2_reference(
                frame,
                instrument_key=instrument_key,
                evaluation_time=evaluation_time,
            )
            if reference is None:
                continue
            # Attach the informational futures-VWAP position of the red bar
            # itself. `build_red_bar_v2_reference` is deterministic across the
            # session -- it always returns the first red 5m bar at or after
            # 09:20, and completing more candles cannot change an earlier row --
            # so annotating once and reusing is equivalent to recomputing on
            # every candle, minus a session-VWAP pass per candle.
            annotated_reference = annotate_reference_vwap_position(
                reference, futures_frame
            )
        reference = annotated_reference
        if rule_reference is None:
            rule_reference = {
                "timestamp": reference.reference_timestamp.isoformat(),
                "open": reference.reference_open,
                "high": reference.reference_high,
                "low": reference.reference_low,
                "close": reference.reference_close,
                "midpoint": reference.midpoint,
                # Informational: gates no decision, see
                # `annotate_reference_vwap_position`.
                "vwap_value": reference.reference_vwap_value,
                "vwap_comparison_price": reference.reference_vwap_comparison_price,
                "vwap_position": reference.reference_vwap_position,
                "vwap_timestamp": (
                    reference.reference_vwap_timestamp.isoformat()
                    if reference.reference_vwap_timestamp is not None
                    else None
                ),
            }

        trade_state = observe_trade_state(trade_rows, instrument_key=instrument_key)
        decision: RedBarV2DirectionDecision | None = None
        decision_snapshot: RedBarV2FuturesSnapshot | None = None
        decision_health: RedBarV2VwapSourceHealth | None = None
        # The level the decision was actually judged against. It is the red bar on
        # every path but the deputy's, and the evidence row has to describe the
        # level that was in force or it documents a comparison nobody made.
        decision_reference: object = reference

        # Precedence by location, recomputed from this close with no latch. The
        # deputy is consulted first only because it governs a region the red bar
        # does not; where the red bar governs, this block does nothing but drop a
        # deputy that has lost its authority.
        #
        # The gate is the live search, not ``waiting_for_red_bar_touch``. A failed
        # re-entry switches that wait off while leaving the strategy flat, and
        # tying the deputy to it would let a disagreeing futures VWAP -- which this
        # path never reads -- retire a structural level that is still valid. The
        # search is started by an exit and ended by an admission or a hand-back,
        # which is exactly the window the deputy is meant to cover.
        deputy_decision: RedBarV2DirectionDecision | None = None
        deputy_snapshot: RedBarV2FuturesSnapshot | None = None
        deputy_health: RedBarV2VwapSourceHealth | None = None
        deputy_governs = False
        if working_search_after is not None:
            close_price = float(frame.loc[candle_timestamp]["close"])
            # Retry the promotion once per completed five-minute slot. The search
            # returns the first qualifying candle after the exit, and a completed
            # bucket cannot be rewritten by later candles, so one success is final
            # and the frame is only re-read while the search keeps failing.
            if working_reference is None and evaluation_time.minute % 5 == 0:
                working_reference = build_working_reference(
                    frame,
                    instrument_key=instrument_key,
                    evaluation_time=evaluation_time,
                    red_bar=reference,
                    after=working_search_after,
                    required_direction=working_search_direction,
                )
                if working_reference is not None:
                    working_established_at = evaluation_time.isoformat()
            _, governing_name = select_governing_reference(
                reference, working_reference, close_price
            )
            if governing_name == "WORKING":
                deputy_governs = True
                deputy_snapshot, deputy_health = build_red_bar_v2_futures_snapshot(
                    frame,
                    futures_frame,
                    instrument_key=instrument_key,
                    vwap_instrument_key=vwap_instrument_key,
                    timeframe="1M",
                    evaluation_time=evaluation_time,
                    expected_timestamp=candle_timestamp,
                )
                latest_health = deputy_health
                candidate = evaluate_working_reference_direction_futures(
                    working_reference,
                    deputy_snapshot,
                    red_bar=reference,
                )
                if _event_is_due(candidate, evaluation_time):
                    deputy_decision = candidate
            elif working_reference is not None:
                # The close is back inside the red bar's band, or out the far side
                # of it. Control returns to the senior reference, and the deputy is
                # discarded rather than parked: a level that a later excursion could
                # revive is the latch this design exists to avoid.
                working_reference = None
                working_search_after = None
                working_search_direction = None
                working_discards += 1
                working_last_discarded_at = evaluation_time.isoformat()

        if deputy_governs:
            # Only one reference is in force, so the red bar's midpoint-touch wait
            # does not also run on this candle -- this close is not in its band.
            decision = deputy_decision
            decision_snapshot = deputy_snapshot
            decision_health = deputy_health
            decision_reference = working_reference
        elif waiting_for_red_bar_touch:
            row = frame.loc[candle_timestamp]
            candle_low = float(row["low"])
            candle_high = float(row["high"])
            touched_midpoint = candle_low <= reference.midpoint <= candle_high
            # Re-entry touch + next-candle VWAP confirm.
            # 1) Check if this 5m candle's VWAP-aligned close confirms the
            #    direction that the touch established. A touch of any
            #    level is enough to start the wait; the next 5m candle
            #    must close on the signal's side of the underlying
            #    futures VWAP.
            vwap_in_direction = (
                _reentry_vwap_confirms(row, reference, futures_frame)
            )
            if touched_midpoint:
                reentry_last_touch_at = evaluation_time.isoformat()
                touch_close = float(row["close"])
                if touch_close > reference.midpoint:
                    reentry_last_touch_direction = "BULLISH"
                elif touch_close < reference.midpoint:
                    reentry_last_touch_direction = "BEARISH"
                else:
                    reentry_last_touch_direction = None
            if touched_midpoint and vwap_in_direction is not None:
                # Both confirmed in this 5m candle -> allow re-entry.
                if vwap_in_direction is True:
                    snapshot, decision_health = build_red_bar_v2_futures_snapshot(
                        frame,
                        futures_frame,
                        instrument_key=instrument_key,
                        vwap_instrument_key=vwap_instrument_key,
                        timeframe="1M",
                        evaluation_time=evaluation_time,
                        expected_timestamp=candle_timestamp,
                    )
                    latest_health = decision_health
                    reentry = evaluate_initial_direction_futures(reference, snapshot)
                    if _event_is_due(reentry, evaluation_time):
                        decision = reentry
                        decision_snapshot = snapshot
                        decision = replace(
                            decision,
                            reentry_state="validated",
                            reentry_alignment_passed=True,
                        )
                        reentry_validated += 1
                        reentry_last_outcome = "VALIDATED"
                        reentry_last_outcome_at = evaluation_time.isoformat()
                        reentry_last_vwap_confirmed = True
                        reentry_last_direction = decision.direction
                        # Re-entry validation: re-entry allowed.
                        if database is not None:
                            try:
                                reentry_candle_iso = (
                                    pd.Timestamp(candle_timestamp)
                                    .to_pydatetime()
                                    .isoformat()
                                )
                                record_strategy_subcheck(
                                    database,
                                    run_id=run_id,
                                    step_name="reentry_validation",
                                    artifacts={
                                        "state": "validated",
                                        "touch_candle": reentry_candle_iso,
                                        "touch_level": reentry_touch_state,
                                        "direction": (
                                            decision.direction
                                            if decision
                                            else None
                                        ),
                                    },
                                )
                            except Exception:
                                pass
                        waiting_for_red_bar_touch = False
                        reentry_touch_state = None
                # Else: VWAP not in same direction; continue waiting.
                elif touched_midpoint and vwap_in_direction is False:
                    # Touch on midpoint was confirmed but next-candle VWAP
                    # was in the opposite direction -> re-entry failed.
                    if database is not None:
                        try:
                            reentry_candle_iso = (
                                pd.Timestamp(candle_timestamp)
                                .to_pydatetime()
                                .isoformat()
                            )
                            record_strategy_subcheck(
                                database,
                                run_id=run_id,
                                step_name="reentry_validation",
                                status="ERROR",
                                artifacts={
                                    "state": "failed",
                                    "touch_candle": reentry_candle_iso,
                                    "touch_level": reentry_touch_state,
                                    "vwap_confirms": False,
                                },
                                error_message=(
                                    "Next-candle underlying close was on the "
                                    "opposite side of futures VWAP from the touch."
                                ),
                            )
                        except Exception:
                            pass
                    reentry_failed += 1
                    reentry_last_outcome = "FAILED"
                    reentry_last_outcome_at = evaluation_time.isoformat()
                    reentry_last_vwap_confirmed = False
                    waiting_for_red_bar_touch = False
                    reentry_touch_state = None
                elif touched_midpoint:
                    # Only the touch happened on this candle; waiting
                    # for the NEXT 5m candle to confirm VWAP.
                    reentry_touch_state = "waiting_midpoint"
            # (The single touch on midpoint is no longer enough by itself;
            # we now require both touch AND next-candle VWAP confirmation.)
        elif pending_reversal is not None:
            decision = pending_reversal
            decision_snapshot = pending_reversal_snapshot
            decision_health = pending_reversal_health
        elif current_direction is None and not initial_processed:
            snapshot, decision_health = build_red_bar_v2_futures_snapshot(
                frame,
                futures_frame,
                instrument_key=instrument_key,
                vwap_instrument_key=vwap_instrument_key,
                timeframe="1M",
                evaluation_time=evaluation_time,
                expected_timestamp=candle_timestamp,
            )
            latest_health = decision_health
            initial = evaluate_initial_direction_futures(reference, snapshot)
            initial_evaluations += 1
            initial_last_evaluated = evaluation_time.isoformat()
            initial_last_result = initial.event_type.value
            initial_last_reason = initial.reason
            if _event_is_due(initial, evaluation_time):
                decision = initial
                decision_snapshot = snapshot
                if initial.direction is not None:
                    initial_processed = True
                    if initial_direction is None:
                        initial_direction = initial.direction
                        initial_established_at = evaluation_time.isoformat()
        elif current_direction is not None and evaluation_time.minute % 5 == 0:
            snapshot, decision_health = build_red_bar_v2_futures_snapshot(
                frame,
                futures_frame,
                instrument_key=instrument_key,
                vwap_instrument_key=vwap_instrument_key,
                timeframe="5M",
                evaluation_time=evaluation_time,
                expected_timestamp=evaluation_time - pd.Timedelta(minutes=5),
            )
            latest_health = decision_health
            if snapshot is not None:
                key = snapshot.candle_timestamp.isoformat()
                if key not in processed_5m_contexts:
                    processed_5m_contexts.add(key)
                    reversal_5m_evaluations += 1
                    reversal = evaluate_reversal_direction_futures(
                        reference,
                        snapshot,
                        previous_direction=current_direction,
                    )
                    if reversal.direction is not None and reversal.direction != current_direction and _event_is_due(reversal, evaluation_time):
                        reversal_detections += 1
                        reversal_last_at = evaluation_time.isoformat()
                        reversal_last_direction = reversal.direction
                        reversal_last_strength = reversal.trend_strength
                        decision = reversal
                        decision_snapshot = snapshot
                        pending_reversal = reversal
                        pending_reversal_snapshot = snapshot
                        pending_reversal_health = decision_health

        if decision is not None:
            admission = evaluate_candidate_admission(
                decision,
                trade_state,
                duplicate_signal=False,
                reversal_already_consumed=False,
            )
            duplicate = admission.decision_id in processed_candidates
            consumed = bool(admission.reversal_event_id and admission.reversal_event_id in consumed_reversals)
            admission = evaluate_candidate_admission(
                decision,
                trade_state,
                duplicate_signal=duplicate,
                reversal_already_consumed=consumed,
            )

            if admission.candidate_allowed:
                processed_candidates.add(admission.decision_id)
                if admission.reversal_event_id:
                    consumed_reversals.add(admission.reversal_event_id)
                admitted += 1
                last_admitted_at = evaluation_time.isoformat()
                last_admission_code = admission.admission_code.value
                if initial_admitted is None and admission.entry_type == "INITIAL":
                    initial_admitted = True
                trade_id = f"RBV2-FVWAP-{admitted:04d}"
                row = _trade_row(trade_id, admission, evaluation_time.to_pydatetime())
                row["instrument_key"] = instrument_key
                trade_rows.append(row)
                current_direction = admission.direction
                provisional_state = (
                    RedBarV2State.PROVISIONAL_BULLISH
                    if admission.direction == "BULLISH" and admission.trend_strength == "PROVISIONAL"
                    else RedBarV2State.PROVISIONAL_BEARISH
                    if admission.direction == "BEARISH" and admission.trend_strength == "PROVISIONAL"
                    else None
                )
                pending_reversal = None
                pending_reversal_snapshot = None
                pending_reversal_health = None
                waiting_for_red_bar_touch = False
                # This deputy has done its job. Retiring it with its search means
                # the next exit starts a fresh one rather than re-entering off a
                # level the market has already traded through.
                if admission.entry_type == "WORKING":
                    working_entries += 1
                working_reference = None
                working_search_after = None
                working_search_direction = None
            else:
                blocked += 1
                last_block_code = admission.admission_code.value
                last_block_reason = admission.admission_reason
                last_block_at = evaluation_time.isoformat()
                if initial_admitted is None and admission.entry_type == "INITIAL":
                    initial_admitted = False
                trade_id = None
                if admission.admission_code not in {AdmissionCode.ACTIVE_TRADE_BLOCK, AdmissionCode.PREVIOUS_TRADE_NOT_CLOSED}:
                    pending_reversal = None
                    pending_reversal_snapshot = None
                    pending_reversal_health = None

            details: dict[str, object] = {
                "entry_type": admission.entry_type,
                "trend_strength": admission.trend_strength,
                "decision_id": admission.decision_id,
                "reversal_event_id": admission.reversal_event_id,
                "admission_reason": admission.admission_reason,
                "reference_timestamp": admission.reference_timestamp,
                "context_timestamp": admission.context_timestamp,
                "active_trade_count": admission.active_trade_count,
                "previous_trade_status": admission.previous_trade_status,
                "conditions": dict(admission.conditions),
                "price_source_instrument": instrument_key,
                "rsi_source_instrument": instrument_key,
                "vwap_source_instrument": vwap_instrument_key,
                "execution_scope": "HISTORICAL_REPLAY_ONLY",
            }
            # Stage 3 geometry: which reference was in force, where the close sat
            # relative to the Red Bar band, and how far past the level it closed.
            # These gate nothing, but without them a replay row cannot be told
            # apart from one taken against a different level entirely.
            for field in (
                "zone_position",
                "governing_reference",
                "midpoint_distance_points",
                "working_body_ratio",
            ):
                value = getattr(decision, field, None)
                if value is not None:
                    details[field] = value
            if decision_health is not None:
                details["vwap_source_health"] = decision_health.to_dict()
            if decision_snapshot is not None:
                evidence = build_legacy_v2_decision_evidence(
                    underlying_instrument_key=instrument_key,
                    futures_instrument_key=vwap_instrument_key,
                    direction_decision=decision,
                    reference=decision_reference,
                    index_context=decision_snapshot,
                    futures_context=decision_snapshot,
                )
                details.update(evidence_to_event_details(evidence))

            events.append(ReplayEvent(
                timestamp=evaluation_time.to_pydatetime(),
                event_type="CANDIDATE_ADMISSION",
                direction=admission.direction,
                option_side=admission.option_side,
                admission_code=admission.admission_code.value,
                candidate_allowed=admission.candidate_allowed,
                trade_id=trade_id,
                details=details,
            ))

        if provisional_state is not None:
            active_state = observe_trade_state(trade_rows, instrument_key=instrument_key)
            if active_state.active_trade is not None:
                snapshot, health = build_red_bar_v2_futures_snapshot(
                    frame,
                    futures_frame,
                    instrument_key=instrument_key,
                    vwap_instrument_key=vwap_instrument_key,
                    timeframe="1M",
                    evaluation_time=evaluation_time,
                    expected_timestamp=candle_timestamp,
                )
                latest_health = health
                upgrade = evaluate_midpoint_upgrade(reference, snapshot, current_state=provisional_state)
                if upgrade.event_type.value == "FULL_DIRECTIONAL_ALIGNMENT" and _event_is_due(upgrade, evaluation_time):
                    upgrade_count += 1
                    upgrade_last_at = evaluation_time.isoformat()
                    upgrade_last_direction = upgrade.direction
                    events.append(ReplayEvent(
                        timestamp=evaluation_time.to_pydatetime(),
                        event_type="STATE_UPGRADE",
                        direction=upgrade.direction,
                        option_side=upgrade.option_side,
                        admission_code=AdmissionCode.FULL_DIRECTIONAL_ALIGNMENT.value,
                        candidate_allowed=False,
                        trade_id=active_state.active_trade.trade_id,
                        details={
                            "from": provisional_state.value,
                            "to": upgrade.state.value,
                            "vwap_source_health": health.to_dict(),
                        },
                    ))
                    provisional_state = None

    if latest_health is None:
        _, latest_health = build_red_bar_v2_futures_snapshot(
            frame,
            futures_frame,
            instrument_key=instrument_key,
            vwap_instrument_key=vwap_instrument_key,
            timeframe="1M",
            evaluation_time=pd.Timestamp(frame.index[-1]) + pd.Timedelta(minutes=1),
            expected_timestamp=frame.index[-1],
        )

    final_state = observe_trade_state(trade_rows, instrument_key=instrument_key)
    trading_date = pd.Timestamp(frame.index[0]).date().isoformat()
    rule_state: dict[str, object] = {
        "as_of": last_evaluation_iso,
        "current_direction": current_direction,
        "reference": {
            "established": rule_reference is not None,
            **(rule_reference or {}),
        },
        "initial": {
            "status": (
                "ESTABLISHED"
                if initial_processed
                else "SCANNING"
                if rule_reference is not None
                else "REFERENCE_PENDING"
            ),
            "direction": initial_direction,
            "established_at": initial_established_at,
            "admitted": initial_admitted,
            "evaluations": initial_evaluations,
            "last_evaluated_at": initial_last_evaluated,
            "last_result": initial_last_result,
            "last_reason": initial_last_reason,
        },
        "reversal": {
            "monitoring": current_direction is not None,
            "five_minute_evaluations": reversal_5m_evaluations,
            "detections": reversal_detections,
            "last_detected_at": reversal_last_at,
            "last_direction": reversal_last_direction,
            "last_trend_strength": reversal_last_strength,
            "pending": pending_reversal is not None,
        },
        "upgrade": {
            "provisional_state": (
                provisional_state.value if provisional_state is not None else None
            ),
            "upgrades": upgrade_count,
            "last_upgrade_at": upgrade_last_at,
            "last_direction": upgrade_last_direction,
        },
        "reentry": {
            "waiting": waiting_for_red_bar_touch,
            "touch_state": reentry_touch_state,
            "waiting_since": reentry_waiting_since,
            "last_touch_at": reentry_last_touch_at,
            "last_touch_direction": reentry_last_touch_direction,
            "last_vwap_confirmed": reentry_last_vwap_confirmed,
            "validated": reentry_validated,
            "failed": reentry_failed,
            "last_outcome": reentry_last_outcome,
            "last_outcome_at": reentry_last_outcome_at,
            "last_direction": reentry_last_direction,
        },
        "working_reference": {
            # The deputy covers the space the midpoint wait cannot reach, so its
            # counters are read against ``reentry``'s: a day with a long wait and
            # no working entry is a day the strategy sat out.
            "active": working_reference is not None,
            "searching": working_search_after is not None
            and working_reference is None,
            "direction": working_search_direction,
            "established_at": working_established_at,
            "zone_side": (
                working_reference.zone_side if working_reference is not None else None
            ),
            "body_ratio": (
                working_reference.body_ratio if working_reference is not None else None
            ),
            "entries": working_entries,
            "discards": working_discards,
            "last_discarded_at": working_last_discarded_at,
        },
        "admission": {
            "admitted": admitted,
            "blocked": blocked,
            "last_admitted_at": last_admitted_at,
            "last_admission_code": last_admission_code,
            "last_block_code": last_block_code,
            "last_block_reason": last_block_reason,
            "last_block_at": last_block_at,
            "active_trade_count": final_state.active_trade_count,
            "previous_trade_status": (
                final_state.latest_executed_trade.lifecycle_state.value
                if final_state.latest_executed_trade is not None
                else None
            ),
            "trade_state": final_state.lifecycle_state.value,
        },
    }
    result = RedBarV2ReplayResult(
        instrument_key=instrument_key,
        trading_date=trading_date,
        reference_timestamp=reference.reference_timestamp if reference else None,
        reference_midpoint=reference.midpoint if reference else None,
        events=tuple(events),
        admitted_candidates=admitted,
        blocked_candidates=blocked,
        closed_trades=closed,
        final_trade_state=final_state.lifecycle_state.value,
        rule_state=rule_state,
    )
    return result, latest_health


def _reentry_vwap_confirms(
    index_row: pd.Series,
    reference: object,
    futures_frame: pd.DataFrame,
) -> bool | None:
    """Check if this 5m candle's underlying-vs-futures aligns with the touch.

    The re-entry rule is: a single level touch (midpoint, VWAP, or
    mid-session) STARTS the wait. The next 5m candle must confirm the
    direction by having the underlying close on the same side of the
    underlying futures close as the original touch.

    The touch direction is inferred from the index candle's close vs the
    reference midpoint:
      - index_close > midpoint  =>  BULLISH touch
      - index_close < midpoint  =>  BEARISH touch
      - equal                  =>  undefined (return None)

    Returns:
        True  - direction confirmed (re-entry is allowed)
        False - opposite direction (re-entry wait is cancelled)
        None  - data unavailable (wait continues)

    The futures close is the latest completed 5m futures close at or
    before the index candle's timestamp. This is a simple proxy for
    VWAP confirmation; a more sophisticated implementation would
    compare to the actual VWAP series. The historical-replay context
    doesn't have VWAP directly available at the candle level, so
    futures close is the most reliable signal.
    """
    from red_bar_lab.intelligence.market_context import completed_candles

    try:
        candle_ts = index_row.name
        index_close = float(index_row.get("close", 0.0))
        midpoint = float(getattr(reference, "midpoint", 0.0))

        if midpoint == 0.0 or index_close == 0.0:
            return None

        bullish = index_close > midpoint
        if index_close == midpoint:
            return None  # touch direction undefined

        relevant_futures = completed_candles(
            futures_frame, evaluation_time=candle_ts, interval_minutes=5
        )
        if relevant_futures.empty:
            return None
        relevant_futures = relevant_futures.sort_index()
        before = relevant_futures[relevant_futures.index <= candle_ts]
        if before.empty:
            return None
        futures_close = float(before.iloc[-1]["close"])
        if futures_close == 0.0:
            return None

        if bullish:
            return index_close > futures_close
        else:
            return index_close < futures_close
    except Exception:
        return None