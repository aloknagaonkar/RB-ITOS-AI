from __future__ import annotations

from datetime import date
from time import perf_counter
from typing import Callable
import pandas as pd

from red_bar_lab.execution.candidate_lifecycle import MarketSessionManager
from red_bar_lab.execution.portfolio_manager import PortfolioCandidate
from red_bar_lab.services.historical_decision_replay import (
    DecisionReplayRow,
    HistoricalDecisionReplayResult,
    HistoricalDecisionReplayService,
)
from red_bar_lab.services.historical_dri_replay import detect_historical_dri_events
from red_bar_lab.services.historical_dri_quality import (
    DRIQualityConfig,
    SameDirectionReentryGate,
    calibration_eligible,
    filter_tradable_candidates,
)
from red_bar_lab.services.historical_dri_reentry_policy import (
    ResetAndRebreakGate,
)
from red_bar_lab.services.historical_dri_reversal_state import (
    HistoricalDRIReversalStateMachine,
)
from red_bar_lab.services.historical_dri_trailing_validation import (
    TrailingStopConfig,
    simulate_trailing_stop,
)
from red_bar_lab.services.historical_dri_trailing_reporting import (
    attach_trailing_columns,
    summarize_trailing_audit,
)
from red_bar_lab.services.historical_dri_diagnostics import (
    build_reversal_diagnostics,
)
from red_bar_lab.services.historical_dri_refinements import (
    override_reset_rebreak_if_reexpanded,
    reset_reexpansion_diagnostics,
)
from red_bar_lab.services.historical_dri_quality_refinement import (
    evaluate_reset_override_quality,
    resolve_numeric_metric,
    simulate_adaptive_trailing_stop,
)

IST = "Asia/Kolkata"


class HistoricalDRIDecisionReplayService:
    """Additive DRI-to-existing-policy replay adapter.

    One DRI event is one bundle and one Rank-1 candidate. Future option candles
    are used only after the entry decision has been frozen.
    """

    def __init__(self, base: HistoricalDecisionReplayService) -> None:
        if base.option_chain_sync is None:
            raise ValueError("Point-in-time option-chain data is required.")
        self.base = base
        self.last_timing: dict[str, object] = {}

    def run_day(
        self,
        instrument_key: str,
        trading_date: date,
        progress_callback: Callable[[int, int, str, float], None] | None = None,
    ):
        started = perf_counter()
        coverage = self.base.option_chain_sync.validate_day(
            instrument_key, trading_date
        )
        if not coverage.replay_ready:
            raise ValueError(
                f"Historical option replay is not ready for {trading_date}: "
                f"{coverage.fidelity}"
            )

        candles = self.base.historical.read_day(
            instrument_key, trading_date, interval_minutes=1
        )
        if candles is None or candles.empty:
            raise ValueError(f"No cached 1-minute candles for {trading_date}")

        events = detect_historical_dri_events(candles)
        underlying = self.base._to_ist(candles)

        # Preload replay-day option data once. The previous implementation
        # reread/reconstructed every contract for every DRI event.
        preload_started = perf_counter()
        sync = self.base.option_chain_sync
        live_mode = coverage.data_source == "LIVE_MARKET_CAPTURE"
        live_snapshots = tuple(
            sync._live_snapshots(instrument_key, trading_date)
        ) if live_mode else ()
        live_series_cache: dict[str, pd.DataFrame] = {}
        stored_contracts: list[dict[str, object]] = []
        stored_series: dict[str, pd.DataFrame] = {}
        if not live_mode:
            manifest = sync.store.read_manifest(instrument_key, trading_date)
            stored_contracts = [
                dict(raw)
                for raw in (manifest.get("contracts") or [])
                if isinstance(raw, dict)
            ]
            for raw in stored_contracts:
                key = sync._contract_key(raw)
                if not key:
                    continue
                frame = sync.store.read_candles(
                    instrument_key, trading_date, key
                )
                if frame is not None and not frame.empty:
                    stored_series[key] = frame.reset_index(drop=True)
        preload_seconds = perf_counter() - preload_started

        def _prior(frame: pd.DataFrame, moment: pd.Timestamp) -> pd.DataFrame:
            if frame is None or frame.empty or "timestamp" not in frame.columns:
                return pd.DataFrame()
            ts = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
            result = frame.loc[ts <= moment.tz_convert("UTC")]
            return result.reset_index(drop=True)

        def point_in_time_contracts(moment: pd.Timestamp):
            if not live_mode:
                result = []
                for raw in stored_contracts:
                    key = sync._contract_key(raw)
                    full = stored_series.get(key)
                    if full is None:
                        continue
                    prior = _prior(full, moment)
                    if not prior.empty:
                        result.append((raw, prior, full))
                return result

            prior_snapshots = [s for s in live_snapshots if s[0] <= moment]
            if not prior_snapshots:
                return []
            latest_ts, latest_meta, latest_chain = prior_snapshots[-1]
            if (moment - latest_ts).total_seconds() > 180:
                return []
            result = []
            for _, chain_row in latest_chain.iterrows():
                for side in ("CE", "PE"):
                    raw = sync._live_contract_row(
                        chain_row,
                        side,
                        str(latest_meta.get("option_expiry") or "") or None,
                    )
                    key = sync._contract_key(raw)
                    strike = sync._strike(raw)
                    cache_key = f"{key}|{side}|{strike:.6f}"
                    full = live_series_cache.get(cache_key)
                    if full is None:
                        full = sync._live_contract_series(
                            live_snapshots,
                            instrument_key=key,
                            strike=strike,
                            side=side,
                        ).reset_index(drop=True)
                        live_series_cache[cache_key] = full
                    prior = _prior(full, moment)
                    if not prior.empty:
                        result.append((raw, prior, full))
            return result

        rows = []
        admitted = 0
        watchlisted = 0
        quality_config = DRIQualityConfig()
        reentry_gate = SameDirectionReentryGate(
            quality_config.same_direction_cooldown_minutes
        )
        reset_rebreak_gate = ResetAndRebreakGate()
        reset_rebreak_suppressed_count = 0
        opposite_regime_reset_count = 0
        reversal_state = HistoricalDRIReversalStateMachine()
        pending_reversal_count = 0
        confirmed_reversal_count = 0
        provisional_reversal_count = 0
        provisional_taken_directions = set()
        trailing_audit = []
        trailing_config = TrailingStopConfig(
            initial_stop_pct=7.0,
        )
        detected_count = len(events)
        qualified_count = 0
        executed_count = 0
        hypothetical_count = 0
        unresolved_count = 0
        quality_rejected_count = 0
        cooldown_suppressed_count = 0

        total_events = len(events)
        if progress_callback:
            progress_callback(
                0, total_events, "Replay-day option data loaded",
                perf_counter() - started,
            )

        for event_index, event in enumerate(events, start=1):
            if progress_callback:
                progress_callback(
                    event_index, total_events,
                    f"Processing {event.setup_type}",
                    perf_counter() - started,
                )
            moment = pd.Timestamp(event.timestamp)
            if moment.tzinfo is None:
                moment = moment.tz_localize(IST)
            else:
                moment = moment.tz_convert(IST)

            direction = event.direction
            option_side = "CE" if direction == "BULLISH" else "PE"
            known = underlying.loc[underlying["timestamp"] <= moment]
            spot = (
                float(known.iloc[-1]["close"])
                if not known.empty
                else float(event.trigger_level)
            )

            signal = {
                "signal_id": event.event_id,
                "bundle_id": event.event_id,
                "source": event.source,
                "stage": event.stage,
                "setup_type": event.setup_type,
                "direction": direction,
                "confirmation_high": (
                    event.trigger_level
                    if direction == "BULLISH"
                    else event.invalidation_level
                ),
                "confirmation_low": (
                    event.invalidation_level
                    if direction == "BULLISH"
                    else event.trigger_level
                ),
                "confirmation_close": event.trigger_level,
                "underlying_entry": event.trigger_level,
                "trigger_level": event.trigger_level,
                "invalidation_level": event.invalidation_level,
                "fresh_until": event.fresh_until,
            }
            signal.update(self.base._point_in_time_ema10(candles, moment))
            metrics = self.base._point_in_time_metrics(
                candles, moment, direction
            )
            lifecycle = self.base.lifecycle.evaluate(
                signal_id=event.event_id,
                confirmation_timestamp=event.timestamp,
                now=moment.to_pydatetime(),
            )
            session = MarketSessionManager.classify(moment.to_pydatetime())

            candidates = []
            full_by_symbol = {}
            for raw, prior, full in point_in_time_contracts(moment):
                candidate = self.base._historical_candidate(raw, prior)
                if candidate is None:
                    continue
                if candidate.contract.option_type != option_side:
                    continue
                candidates.append(candidate)
                full_by_symbol[candidate.contract.tradingsymbol] = full

            quality_result = filter_tradable_candidates(
                candidates,
                spot=spot,
                config=quality_config,
            )
            quality_rejected_count += quality_result.rejected_count
            candidates = list(quality_result.accepted)
            candidates.sort(
                key=lambda c: (
                    c.total_score,
                    -abs(c.contract.strike - spot),
                ),
                reverse=True,
            )
            rank1 = candidates[0] if candidates else None
            rank1_blocker = (
                "NO_TRADABLE_RANK1_OPTION"
                if quality_result.rejected_count
                else "NO_RANK1_OPTION_AT_TIMESTAMP"
            )

            if rank1 is None:
                rows.append(
                    DecisionReplayRow(
                        signal_id=event.event_id,
                        timestamp=event.timestamp,
                        level_type=event.setup_type,
                        direction=direction,
                        option_side=option_side,
                        lifecycle_state=lifecycle.state,
                        lifecycle_action=lifecycle.action,
                        market_session=session.code,
                        primary_confidence_pct=0.0,
                        shadow_decision="WAIT",
                        shadow_confidence_pct=50.0,
                        agreement="INFORMATIONAL",
                        shadow_adjustment_pct=0.0,
                        final_confidence_pct=0.0,
                        expectancy_pct=0.0,
                        decision="WAIT",
                        execution="WOULD_WAIT",
                        blocker=rank1_blocker,
                        data_fidelity=coverage.fidelity,
                        vwap_ok=metrics["vwap_ok"],
                        ema_ok=metrics["ema_ok"],
                        momentum_ok=metrics["momentum_ok"],
                        volume_score=float(metrics["volume_score"]),
                        oi_score=float(metrics["oi_score"]),
                        outcome_points=None,
                        outcome_result="UNKNOWN",
                        verdict="UNRESOLVED",
                        learning_attribution=(
                            "OPTION_QUALITY_FILTER"
                            if rank1_blocker == "NO_TRADABLE_RANK1_OPTION"
                            else "OPTION_DATA_GAP"
                        ),
                        learning_recommendation=(
                            "No tradable point-in-time Rank-1 option was available."
                        ),
                    )
                )
                unresolved_count += 1
                continue

            qualified_count += 1

            reversal_decision = reversal_state.evaluate_opposite_event(
                direction,
                close_price=event.trigger_level,
                metrics=metrics,
                setup_type=event.setup_type,
                candles=candles,
                moment=moment,
            )
            pending_reversal = (
                reversal_decision.state.value.startswith("PENDING_")
                and not reversal_decision.confirmed
            )
            provisional_reversal = bool(
                getattr(reversal_decision, "provisional", False)
            )
            provisional_already_used = bool(
                provisional_reversal
                and direction in provisional_taken_directions
            )
            if pending_reversal:
                pending_reversal_count += 1
            if provisional_reversal:
                provisional_reversal_count += 1

            if reversal_decision.confirmed:
                before_cooldown = dict(reentry_gate._last_taken)
                before_reset = dict(reset_rebreak_gate._last_taken)
                reentry_gate.reset_opposite(direction)
                reset_rebreak_gate.reset_opposite(direction)
                if (
                    before_cooldown != reentry_gate._last_taken
                    or before_reset != reset_rebreak_gate._last_taken
                ):
                    opposite_regime_reset_count += 1
                confirmed_reversal_count += 1

            cooldown_reason = reentry_gate.reason(direction, moment)
            reset_rebreak = reset_rebreak_gate.evaluate(
                direction,
                moment,
                candles,
                trigger_level=event.trigger_level,
                invalidation_level=event.invalidation_level,
            )
            reset_rebreak = override_reset_rebreak_if_reexpanded(
                reset_rebreak,
                candles,
                moment=moment,
                direction=direction,
                momentum_ok=bool(metrics.get("momentum_ok")),
            )
            reset_reexpansion_diag = reset_reexpansion_diagnostics(
                candles,
                moment=moment,
                direction=direction,
                momentum_ok=bool(metrics.get("momentum_ok")),
            )

            reversal_diag = build_reversal_diagnostics(
                candles,
                moment=moment,
                direction=direction,
                reversal_decision=reversal_decision,
                active_invalidation=getattr(
                    reversal_state, "last_invalidation", None
                ),
                reset_rebreak_reason=getattr(
                    reset_rebreak, "reason", None
                ),
            )

            opportunity = self.base.opportunity_engine.evaluate(
                signal=signal,
                candidate=rank1,
                spot_price=spot,
                signal_age_seconds=0.0,
                opposite_red_bar_confirmed=False,
                freshness_seconds=180.0,
            )
            selection = self.base.selection_engine.evaluate(
                candidate=rank1,
                candidate_rank=1,
                opportunity=opportunity,
                historical_orders=(),
                entry_mode=opportunity.entry_mode,
                minimum_candidate_score=65.0,
                stop_loss_pct=self.base.stop_loss_pct,
                target_pct=self.base.target_pct,
                require_opportunity_gate=False,
            )
            committee = self.base.execution_committee.evaluate(
                candidate=rank1,
                selection=selection,
                opportunity=opportunity,
                historical_orders=(),
                current_shadow=None,
                historical_shadow=(),
                stop_loss_pct=self.base.stop_loss_pct,
                target_pct=self.base.target_pct,
            )

            portfolio = []
            queue_id = (
                f"HDRI-{event.event_id}-"
                f"{rank1.contract.instrument_token}"
            )
            if committee.eligible:
                portfolio = self.base.portfolio_manager.admit(
                    [
                        PortfolioCandidate(
                            queue_id=queue_id,
                            signal_id=event.event_id,
                            symbol=rank1.contract.tradingsymbol,
                            option_type=rank1.contract.option_type,
                            rank=1,
                            candidate_score=rank1.total_score,
                            opportunity_health=opportunity.opportunity_score,
                            expectancy_pct=committee.expected_value_pct,
                            reference_price=float(rank1.ltp or 0.0),
                            stop_loss_pct=self.base.stop_loss_pct,
                            quantity=rank1.contract.lot_size,
                        )
                    ],
                    initial_capital=self.base.initial_capital,
                    current_open_trades=0,
                    current_deployed_capital=0.0,
                    current_risk=0.0,
                    current_ce=0,
                    current_pe=0,
                )
            admission = portfolio[0] if portfolio else None

            execution = "WOULD_WAIT"
            decision = "WAIT"
            blocker = committee.reason
            portfolio_status = "NOT_QUALIFIED"
            portfolio_reason = committee.reason

            quality_candidate_score_input = resolve_numeric_metric(
                rank1.total_score,
            )
            quality_opportunity_health_input = resolve_numeric_metric(
                opportunity.opportunity_score,
            )

            reset_quality = evaluate_reset_override_quality(
                candles,
                moment=moment,
                direction=direction,
                reset_classification=str(
                    reset_reexpansion_diag.get(
                        "reset_classification"
                    ) or "NONE"
                ),
                reset_rebreak_reason=getattr(
                    reset_rebreak, "reason", None
                ),
                break_level=reset_reexpansion_diag.get(
                    "reexpansion_break_level"
                ),
                candidate_score=quality_candidate_score_input,
                opportunity_health=quality_opportunity_health_input,
                ema10_ok=reversal_diag.get("reversal_ema10_ok"),
                ema30_ok=reversal_diag.get("reversal_ema30_ok"),
                reversal_confirmed=bool(
                    reversal_diag.get("reversal_confirmed")
                ),
            )
            reset_quality_blocker = bool(
                reset_quality.get("applicable")
                and not reset_quality.get("passed")
            )
            if reset_quality_blocker:
                execution = "WOULD_WAIT"
                decision = "WAIT"
                blocker = "RESET_EXPANSION_QUALITY"
                portfolio_status = "RESET_QUALITY_WAIT"
                portfolio_reason = (
                    "RESET_QUALITY_"
                    f"{reset_quality.get('criteria_count', 0)}_OF_5_"
                    f"MARKET_ACTION_{reset_quality.get('market_action_count', 0)}"
                )
            elif pending_reversal or provisional_already_used:
                execution = "WOULD_WAIT"
                decision = "WAIT"
                blocker = reversal_decision.reason
                portfolio_status = (
                    "PROVISIONAL_REVERSAL_USED"
                    if provisional_already_used
                    else "PENDING_REVERSAL"
                )
                portfolio_reason = reversal_decision.reason
            elif cooldown_reason:
                execution = "WOULD_WAIT"
                decision = "WAIT"
                blocker = cooldown_reason
                portfolio_status = "COOLDOWN"
                portfolio_reason = cooldown_reason
                cooldown_suppressed_count += 1
            elif not reset_rebreak.allowed:
                execution = "WOULD_WAIT"
                decision = "WAIT"
                blocker = reset_rebreak.reason
                portfolio_status = "RESET_REQUIRED"
                portfolio_reason = reset_rebreak.reason
                reset_rebreak_suppressed_count += 1
            elif not session.entry_allowed:
                execution = "WOULD_BLOCK"
                decision = "BLOCKED"
                blocker = f"MARKET_SESSION_{session.code}"
                portfolio_status = "BLOCKED"
                portfolio_reason = blocker
            elif committee.eligible and admission and admission.admitted:
                execution = "WOULD_TAKE"
                decision = "APPROVED"
                blocker = "NONE"
                portfolio_status = "APPROVED"
                portfolio_reason = admission.reason
                admitted += 1
                executed_count += 1
                reentry_gate.record_taken(direction, moment)
                reset_rebreak_gate.record_taken(
                    direction,
                    moment,
                    trigger_level=event.trigger_level,
                    invalidation_level=event.invalidation_level,
                )
                if provisional_reversal:
                    provisional_taken_directions.add(direction)
                else:
                    reversal_state.record_taken(
                        direction,
                        invalidation_level=event.invalidation_level,
                    )
            elif committee.eligible and admission:
                portfolio_status = "WATCHLIST"
                portfolio_reason = admission.reason
                blocker = admission.reason
                watchlisted += 1

            exit_info = {
                "entry": rank1.ltp,
                "exit": None,
                "return_pct": None,
                "reason": "NO_FUTURE_OPTION_CANDLES",
            }
            full = full_by_symbol.get(
                rank1.contract.tradingsymbol, pd.DataFrame()
            )
            if full is not None and not full.empty:
                exit_info = self.base._simulate_exit(
                    candidate=rank1,
                    all_candles=full,
                    entry_moment=moment.to_pydatetime(),
                    signal=signal,
                    underlying=candles,
                )

            trailing_result = None
            adaptive_trailing_result = None
            adaptive_initial_stop_pct = None
            if execution == "WOULD_TAKE" and rank1.ltp:
                trailing_result = simulate_trailing_stop(
                    full,
                    entry_moment=moment,
                    entry_price=float(rank1.ltp),
                    baseline_exit_price=exit_info.get("exit"),
                    config=trailing_config,
                )
                (
                    adaptive_initial_stop_pct,
                    adaptive_trailing_result,
                ) = simulate_adaptive_trailing_stop(
                    full,
                    entry_moment=moment,
                    entry_price=float(rank1.ltp),
                    baseline_exit_price=exit_info.get("exit"),
                    base_config=trailing_config,
                )
                trailing_audit.append({
                    "signal_id": event.event_id,
                    "symbol": rank1.contract.tradingsymbol,
                    "baseline_exit": exit_info.get("exit"),
                    "baseline_return_pct": exit_info.get("return_pct"),
                    **trailing_result.to_dict(),
                })

            ret = exit_info.get("return_pct")
            if ret is None:
                outcome = "UNKNOWN"
                points = None
            else:
                points = float(exit_info.get("exit") or 0.0) - float(
                    exit_info.get("entry") or 0.0
                )
                outcome = (
                    "WIN" if ret > 0 else "LOSS" if ret < 0 else "BREAKEVEN"
                )

            if execution != "WOULD_TAKE" and outcome != "UNKNOWN":
                hypothetical_count += 1
            verdict = self.base._verdict(execution, outcome)
            attribution, recommendation = self.base._learning_attribution(
                verdict=verdict,
                blocker=blocker,
                shadow_decision="WAIT",
                shadow_adjustment=0.0,
                vwap_ok=metrics["vwap_ok"],
                ema_ok=metrics["ema_ok"],
                momentum_ok=metrics["momentum_ok"],
            )

            rows.append(
                DecisionReplayRow(
                    signal_id=event.event_id,
                    timestamp=event.timestamp,
                    level_type=event.setup_type,
                    direction=direction,
                    option_side=option_side,
                    lifecycle_state=lifecycle.state,
                    lifecycle_action=lifecycle.action,
                    market_session=session.code,
                    primary_confidence_pct=committee.primary_confidence_pct,
                    shadow_decision="WAIT",
                    shadow_confidence_pct=50.0,
                    agreement="INFORMATIONAL",
                    shadow_adjustment_pct=0.0,
                    final_confidence_pct=committee.execution_probability_pct,
                    expectancy_pct=committee.expected_value_pct,
                    decision=decision,
                    execution=execution,
                    blocker=blocker,
                    data_fidelity=coverage.fidelity,
                    vwap_ok=metrics["vwap_ok"],
                    ema_ok=metrics["ema_ok"],
                    momentum_ok=metrics["momentum_ok"],
                    volume_score=rank1.volume_score,
                    oi_score=rank1.oi_score,
                    outcome_points=points,
                    outcome_result=outcome,
                    verdict=verdict,
                    learning_attribution=attribution,
                    learning_recommendation=recommendation,
                    candidate_symbol=rank1.contract.tradingsymbol,
                    candidate_rank=1,
                    candidate_score=rank1.total_score,
                    opportunity_health=opportunity.opportunity_score,
                    portfolio_status=portfolio_status,
                    portfolio_reason=portfolio_reason,
                    exit_reason=exit_info.get("reason"),
                    option_entry_price=exit_info.get("entry"),
                    option_exit_price=exit_info.get("exit"),
                    option_return_pct=ret,
                    trailing_activated=bool(
                        trailing_result and trailing_result.activated
                    ),
                    trailing_exit_price=(
                        trailing_result.exit_price
                        if trailing_result else None
                    ),
                    trailing_return_pct=(
                        trailing_result.return_pct
                        if trailing_result else None
                    ),
                    trailing_exit_reason=(
                        trailing_result.exit_reason
                        if trailing_result else None
                    ),
                    trailing_protected_points=(
                        trailing_result.protected_points
                        if trailing_result else None
                    ),
                    reversal_state=reversal_diag["reversal_state"],
                    reversal_reason=reversal_diag["reversal_reason"],
                    reversal_provisional=reversal_diag[
                        "reversal_provisional"
                    ],
                    reversal_confirmed=reversal_diag[
                        "reversal_confirmed"
                    ],
                    reversal_ema10_value=reversal_diag[
                        "reversal_ema10_value"
                    ],
                    reversal_ema10_slope=reversal_diag[
                        "reversal_ema10_slope"
                    ],
                    reversal_ema10_ok=reversal_diag[
                        "reversal_ema10_ok"
                    ],
                    reversal_ema30_value=reversal_diag[
                        "reversal_ema30_value"
                    ],
                    reversal_ema30_slope=reversal_diag[
                        "reversal_ema30_slope"
                    ],
                    reversal_ema30_ok=reversal_diag[
                        "reversal_ema30_ok"
                    ],
                    reversal_two_directional_closes=reversal_diag[
                        "reversal_two_directional_closes"
                    ],
                    reversal_momentum_ok=(
                        bool(metrics.get("momentum_ok"))
                        if metrics.get("momentum_ok") is not None
                        else None
                    ),
                    reversal_active_invalidation=reversal_diag[
                        "reversal_active_invalidation"
                    ],
                    reversal_invalidation_broken=reversal_diag[
                        "reversal_invalidation_broken"
                    ],
                    reset_rebreak_reason=reversal_diag[
                        "reset_rebreak_reason"
                    ],
                    reset_seen=reset_reexpansion_diag["reset_seen"],
                    reexpansion_detected=(
                        reset_reexpansion_diag["reexpansion_detected"]
                    ),
                    reset_candle_time=(
                        reset_reexpansion_diag["reset_candle_time"]
                    ),
                    ema10_touch_detected=(
                        reset_reexpansion_diag["ema10_touch_detected"]
                    ),
                    reexpansion_break_level=(
                        reset_reexpansion_diag["reexpansion_break_level"]
                    ),
                    strong_expansion_candle=(
                        reset_reexpansion_diag["strong_expansion_candle"]
                    ),
                    reset_classification=reset_reexpansion_diag[
                        "reset_classification"
                    ],
                    reset_window_bars=reset_reexpansion_diag[
                        "reset_window_bars"
                    ],
                    reset_counter_candle_seen=reset_reexpansion_diag[
                        "reset_counter_candle_seen"
                    ],
                    reset_near_touch_detected=reset_reexpansion_diag[
                        "reset_near_touch_detected"
                    ],
                    shallow_reset_detected=reset_reexpansion_diag[
                        "shallow_reset_detected"
                    ],
                    reset_quality_passed=reset_quality.get("passed"),
                    reset_quality_criteria_count=reset_quality.get(
                        "criteria_count"
                    ),
                    reset_quality_criteria=reset_quality.get(
                        "criteria"
                    ),
                    reset_market_action_count=reset_quality.get(
                        "market_action_count"
                    ),
                    reset_market_action_passed=reset_quality.get(
                        "market_action_passed"
                    ),
                    reset_market_action_criteria=reset_quality.get(
                        "market_action_criteria"
                    ),
                    reset_moderate_market_action_passed=reset_quality.get(
                        "moderate_market_action_passed"
                    ),
                    reset_market_action_tier=reset_quality.get(
                        "market_action_tier"
                    ),
                    reset_body_ratio_pct=reset_quality.get(
                        "body_ratio_pct"
                    ),
                    reset_move_beyond_break_pct=reset_quality.get(
                        "move_beyond_break_pct"
                    ),
                    reset_relative_volume=reset_quality.get(
                        "relative_volume"
                    ),
                    quality_candidate_score_input=(
                        quality_candidate_score_input
                    ),
                    quality_opportunity_health_input=(
                        quality_opportunity_health_input
                    ),
                    adaptive_initial_stop_pct=adaptive_initial_stop_pct,
                    adaptive_trailing_exit_price=(
                        adaptive_trailing_result.exit_price
                        if adaptive_trailing_result else None
                    ),
                    adaptive_trailing_return_pct=(
                        adaptive_trailing_result.return_pct
                        if adaptive_trailing_result else None
                    ),
                    adaptive_trailing_exit_reason=(
                        adaptive_trailing_result.exit_reason
                        if adaptive_trailing_result else None
                    ),
                    adaptive_trailing_protected_points=(
                        adaptive_trailing_result.protected_points
                        if adaptive_trailing_result else None
                    ),
                    outcome_basis=(
                        "EXECUTED_EXIT_ENGINE"
                        if execution == "WOULD_TAKE"
                        else "COUNTERFACTUAL_EXIT_ENGINE"
                    ),
                )
            )

        approved = sum(r.execution == "WOULD_TAKE" for r in rows)
        waiting = sum(r.execution == "WOULD_WAIT" for r in rows)
        blocked = sum(r.execution == "WOULD_BLOCK" for r in rows)
        winners = sum(
            r.execution == "WOULD_TAKE" and r.outcome_result == "WIN"
            for r in rows
        )
        losers = sum(
            r.execution == "WOULD_TAKE" and r.outcome_result == "LOSS"
            for r in rows
        )
        net = sum(
            (r.outcome_points or 0.0)
            for r in rows
            if r.execution == "WOULD_TAKE"
        )
        calibration_rows = [row for row in rows if calibration_eligible(row)]
        recommendations, accuracy = self.base._aggregate_learning(
            calibration_rows
        )

        total_seconds = perf_counter() - started
        self.last_timing = {
            "events": len(events),
            "preload_seconds": round(preload_seconds, 3),
            "total_seconds": round(total_seconds, 3),
            "cached_contract_series": (
                len(live_series_cache) if live_mode else len(stored_series)
            ),
            "data_source": coverage.data_source,
            "detected": detected_count,
            "qualified": qualified_count,
            "executed": executed_count,
            "hypothetical": hypothetical_count,
            "unresolved": unresolved_count,
            "quality_rejected_candidates": quality_rejected_count,
            "cooldown_suppressed": cooldown_suppressed_count,
            "reset_rebreak_suppressed": reset_rebreak_suppressed_count,
            "opposite_regime_resets": opposite_regime_reset_count,
            "pending_reversals": pending_reversal_count,
            "confirmed_reversals": confirmed_reversal_count,
            "provisional_reversals": provisional_reversal_count,
            "provisional_directions_used": len(provisional_taken_directions),
            "trailing_audited_trades": len(trailing_audit),
            "trailing_net_points": round(sum(
                float(item.get("exit_price") or 0.0)
                - float(item.get("entry_price") or 0.0)
                for item in trailing_audit
            ), 3),
            "baseline_net_points_for_trailing_set": round(sum(
                float(item.get("baseline_exit") or 0.0)
                - float(item.get("entry_price") or 0.0)
                for item in trailing_audit
            ), 3),
            "trailing_protected_points": round(sum(
                float(item.get("protected_points") or 0.0)
                for item in trailing_audit
            ), 3),
            "calibration_eligible": len(calibration_rows),
        }
        self.last_trailing_validation = tuple(trailing_audit)
        self.last_trailing_summary = summarize_trailing_audit(
            trailing_audit
        )
        if hasattr(self, "last_timing"):
            self.last_timing.update(self.last_trailing_summary)
        for _candidate_rows in (
            locals().get("rows"),
            locals().get("replay_rows"),
            locals().get("results"),
        ):
            if isinstance(_candidate_rows, list):
                attach_trailing_columns(
                    _candidate_rows,
                    trailing_audit,
                )
        if progress_callback:
            progress_callback(
                len(events), len(events), "Replay completed", total_seconds
            )

        return HistoricalDecisionReplayResult(
            trading_date=trading_date,
            rows=tuple(rows),
            active_signals=len(events),
            approved=approved,
            blocked=blocked,
            waiting=waiting,
            expired=0,
            winners=winners,
            losers=losers,
            net_points=round(net, 2),
            data_fidelity=coverage.fidelity,
            correct_takes=sum(r.verdict == "CORRECT_TAKE" for r in rows),
            false_positives=sum(
                r.verdict == "FALSE_POSITIVE" for r in rows
            ),
            missed_opportunities=sum(
                r.verdict == "MISSED_OPPORTUNITY" for r in rows
            ),
            correct_skips=sum(r.verdict == "CORRECT_SKIP" for r in rows),
            incorrect_blocks=sum(
                r.verdict == "INCORRECT_BLOCK" for r in rows
            ),
            correct_blocks=sum(
                r.verdict == "CORRECT_BLOCK" for r in rows
            ),
            decision_accuracy_pct=accuracy,
            learning_recommendations=recommendations,
            option_contract_coverage_pct=coverage.contract_coverage_pct,
            option_candle_coverage_pct=coverage.candle_coverage_pct,
            option_oi_coverage_pct=coverage.oi_coverage_pct,
            replay_ready=coverage.replay_ready,
            replay_fidelity_reason=coverage.reason,
            portfolio_admitted=admitted,
            portfolio_watchlisted=watchlisted,
            data_source=coverage.data_source,
        )
