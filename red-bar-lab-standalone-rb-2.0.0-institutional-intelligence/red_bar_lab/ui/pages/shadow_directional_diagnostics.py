from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.ui._shared import *
from red_bar_lab.services.shadow_directional_store import ShadowDirectionalStore
from red_bar_lab.services.shadow_directional_observation import (
    ShadowDirectionalObservationService,
)
from red_bar_lab.services.shadow_directional_replay import (
    ShadowDirectionalReplayService,
)
from red_bar_lab.services.shadow_directional_comparison import (
    compare_shadow_to_current_engine,
)
from red_bar_lab.services.shadow_directional_validation import (
    MultiDayShadowValidationService,
)
from red_bar_lab.services.shadow_feature_calibration import (
    ShadowFeatureCalibrationService,
    build_calibration_rows,
)
from red_bar_lab.services.shadow_out_of_sample_validation import (
    ShadowOutOfSampleValidationService,
)
from red_bar_lab.services.shadow_regime_period_stability import (
    ShadowRegimePeriodStabilityService,
)
from red_bar_lab.services.shadow_signal_lifecycle_simulation import (
    ShadowSignalLifecycleSimulationService,
)
from red_bar_lab.intelligence.stateful_multitimeframe_regime import (
    StatefulMultiTimeframeRegimeEngine,
)
from red_bar_lab.services.stateful_regime_store import StatefulRegimeStore
from red_bar_lab.intelligence.transition_sequence_state_machine import (
    TransitionSequenceStateMachine,
)
from red_bar_lab.services.transition_sequence_store import TransitionSequenceStore
from red_bar_lab.services.attribution_context import build_attribution_context
from red_bar_lab.intelligence.fresh_setup_signal_engine import (
    FreshSetupSignalEngine,
)
from red_bar_lab.services.fresh_setup_signal_store import FreshSetupSignalStore
from red_bar_lab.services.signal_attribution import attach_signal_to_attribution
from red_bar_lab.services.fresh_setup_bundle import build_setup_bundles
from red_bar_lab.services.fresh_setup_bundle_store import FreshSetupBundleStore
from red_bar_lab.services.signal_trade_attribution import create_ledger_record
from red_bar_lab.services.signal_trade_attribution_store import (
    SignalTradeAttributionStore,
)
from red_bar_lab.services.signal_trade_attribution_summary import (
    summarize_by_primary_setup,
    funnel_summary,
)
from red_bar_lab.services.historical_attribution_audit import (
    HistoricalAuditRequest,
    RangeHistoricalAttributionAudit,
    resolve_range_preset,
)
from red_bar_lab.services.historical_bundle_backfill import (
    HistoricalBundleBackfillRequest,
    HistoricalV43BundleBackfill,
)


IST = ZoneInfo("Asia/Kolkata")


def _completed_five_minute_rows(frame: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], errors="coerce")
    result = result.dropna(subset=["timestamp"]).sort_values("timestamp")
    current = now or datetime.now(IST)
    latest_complete = current.replace(second=0, microsecond=0)
    latest_complete = latest_complete - timedelta(minutes=latest_complete.minute % 5)
    cutoff = latest_complete.replace(tzinfo=None) if result["timestamp"].dt.tz is None else pd.Timestamp(latest_complete)
    return result[result["timestamp"] < cutoff].reset_index(drop=True)


def _store(layout, instrument_key: str) -> ShadowDirectionalStore:
    safe = layout._safe_instrument(instrument_key)
    return ShadowDirectionalStore(
        layout.settings.runs_root / "shadow_directional" / f"{safe}.jsonl"
    )


def _load_day(historical, instrument_key: str, trading_date: date) -> pd.DataFrame:
    historical.load_or_download(
        instrument_key,
        trading_date,
        trading_date,
        interval_minutes=5,
        force=False,
    )
    return historical.read_day(
        instrument_key,
        trading_date,
        interval_minutes=5,
    )


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Shadow Directional Transition")
    st.markdown(
        _decision_badge_html(
            "SPRINT 4.2 · VALIDATION MODE · EXECUTION IMPACT = NONE",
            "shadow",
        ),
        unsafe_allow_html=True,
    )

    live_tab, replay_tab, validation_tab, calibration_tab, oos_tab, stability_tab, lifecycle_tab, stateful_tab, attribution_replay_tab = st.tabs([
        "Current Observation",
        "Historical Replay & Outcomes",
        "Multi-Day Validation",
        "Feature Calibration",
        "Out-of-Sample Validation",
        "Regime & Period Stability",
        "Lifecycle Simulation",
        "Stateful Regime v4.3",
        "Historical Attribution Replay",
    ])

    with live_tab:
        selected_date = st.date_input(
            "Trading date",
            value=date.today(),
            key="shadow_directional_date",
        )
        persist = st.toggle(
            "Persist observation",
            value=True,
            key="shadow_directional_persist",
        )
        evaluate = st.button(
            "Evaluate latest completed 5m candle",
            type="primary",
            key="shadow_directional_evaluate",
        )
        store = _store(layout, instrument_key)

        if evaluate:
            try:
                historical = _historical_service(token, layout)
                frame = _load_day(historical, instrument_key, selected_date)
                completed = _completed_five_minute_rows(frame)
                if len(completed) < 35:
                    st.warning(f"Only {len(completed)} completed candles are available; at least 35 are required.")
                else:
                    service = ShadowDirectionalObservationService(store)
                    if persist:
                        record, inserted = service.evaluate_and_store(
                            instrument_key=instrument_key,
                            completed_five_minute_candles=completed,
                        )
                    else:
                        record = service.engine.evaluate(completed).as_record()
                        record.update({
                            "instrument_key": instrument_key,
                            "candle_timestamp": str(completed.iloc[-1]["timestamp"]),
                            "execution_allowed": False,
                        })
                        inserted = False
                    st.session_state["latest_shadow_directional"] = record
                    st.success("Shadow observation stored." if inserted else "Shadow observation evaluated.")
            except MissingAccessToken:
                st.warning("Enter or configure the Upstox access token.")
            except Exception as exc:
                st.error(f"Shadow evaluation failed: {type(exc).__name__}: {exc}")

        latest = st.session_state.get("latest_shadow_directional")
        if latest is None:
            rows = store.latest(instrument_key=instrument_key, limit=1)
            latest = rows[0] if rows else None

        if latest:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Direction", str(latest.get("direction") or "—"))
            c2.metric("Transition", str(latest.get("transition_type") or "—"))
            c3.metric("Confidence", f"{float(latest.get('confidence') or 0):.1f}")
            c4.metric("Regime", str(latest.get("regime") or "—"))
            c5.metric("Execution", "BLOCKED")
            st.dataframe(_arrow_safe_rows([latest]), width="stretch", hide_index=True)
        else:
            st.info("No Shadow Directional observation is available yet.")

    with replay_tab:
        replay_date = st.date_input(
            "Replay trading date",
            value=date.today(),
            key="shadow_directional_replay_date",
        )
        minimum_decision = st.selectbox(
            "Minimum decision strength",
            ("TRANSITION_FORMING", "SHADOW_SIGNAL", "STRONG_SHADOW_SIGNAL"),
            index=0,
            key="shadow_replay_strength",
        )
        if st.button("Run historical shadow replay", type="primary", key="shadow_directional_replay"):
            try:
                historical = _historical_service(token, layout)
                frame = _completed_five_minute_rows(_load_day(historical, instrument_key, replay_date))
                replay = ShadowDirectionalReplayService()
                rows = replay.replay(frame, minimum_decision=minimum_decision)
                current_signals = database.read_signal_attempts(
                    instrument_key,
                    replay_date.isoformat(),
                )
                st.session_state["shadow_replay_rows"] = compare_shadow_to_current_engine(rows, current_signals)
                st.session_state["shadow_replay_summary"] = replay.summarize(rows).as_record()
                st.session_state["shadow_replay_regimes"] = replay.summarize_by_regime(rows)
            except Exception as exc:
                st.error(f"Replay failed: {type(exc).__name__}: {exc}")

        summary = st.session_state.get("shadow_replay_summary")
        if summary:
            st.dataframe(_arrow_safe_rows([summary]), width="stretch", hide_index=True)
            st.dataframe(_arrow_safe_rows(st.session_state.get("shadow_replay_regimes", [])), width="stretch", hide_index=True)
            st.dataframe(_arrow_safe_rows(st.session_state.get("shadow_replay_rows", [])), width="stretch", hide_index=True)

    with validation_tab:
        c1, c2 = st.columns(2)
        start_date = c1.date_input(
            "Start date",
            value=date.today() - timedelta(days=30),
            key="shadow_validation_start",
        )
        end_date = c2.date_input(
            "End date",
            value=date.today(),
            key="shadow_validation_end",
        )
        minimum_decision_multi = st.selectbox(
            "Minimum decision strength",
            ("TRANSITION_FORMING", "SHADOW_SIGNAL", "STRONG_SHADOW_SIGNAL"),
            index=0,
            key="shadow_validation_strength",
        )

        if st.button("Run multi-day validation", type="primary", key="shadow_validation_run"):
            try:
                historical = _historical_service(token, layout)
                validator = MultiDayShadowValidationService()
                frames = {}
                progress = st.progress(0.0, text="Loading 5-minute sessions...")
                days = validator.trading_dates(start_date, end_date)
                for index, trading_day in enumerate(days, start=1):
                    try:
                        frame = _load_day(historical, instrument_key, trading_day)
                        completed = _completed_five_minute_rows(frame)
                        if len(completed) >= 35:
                            frames[trading_day] = completed
                    except Exception:
                        pass
                    progress.progress(index / max(1, len(days)), text=f"Processed {trading_day}")
                progress.empty()

                rows = validator.replay_days(
                    frames,
                    minimum_decision=minimum_decision_multi,
                )
                dashboard = validator.dashboard(rows)
                st.session_state["shadow_validation_dashboard"] = dashboard
            except Exception as exc:
                st.error(f"Multi-day validation failed: {type(exc).__name__}: {exc}")

        dashboard = st.session_state.get("shadow_validation_dashboard")
        if dashboard:
            summary = dashboard["summary"]
            gates = dashboard["promotion_gates"]

            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Transitions", int(summary.get("evaluated") or 0))
            m2.metric("Sessions", int(gates.get("trading_sessions") or 0))
            m3.metric("5m Accuracy", f"{float(summary.get('accuracy_5m') or 0):.1f}%")
            m4.metric("15m Accuracy", f"{float(summary.get('accuracy_15m') or 0):.1f}%")
            m5.metric("30m Accuracy", f"{float(summary.get('accuracy_30m') or 0):.1f}%")
            m6.metric("False Rate", f"{float(summary.get('false_transition_rate_30m') or 0):.1f}%")

            if gates.get("eligible"):
                st.success("PROMOTION GATES PASSED — still observation-only until explicitly approved.")
            else:
                for warning in gates.get("warnings") or []:
                    st.warning(str(warning))

            st.markdown("#### Promotion Gate Audit")
            st.dataframe(_arrow_safe_rows([gates]), width="stretch", hide_index=True)

            st.markdown("#### Direction Performance")
            st.dataframe(_arrow_safe_rows(dashboard["by_direction"]), width="stretch", hide_index=True)

            st.markdown("#### Regime Performance")
            st.dataframe(_arrow_safe_rows(dashboard["by_regime"]), width="stretch", hide_index=True)

            st.markdown("#### Confidence Band Performance")
            st.dataframe(_arrow_safe_rows(dashboard["by_confidence"]), width="stretch", hide_index=True)

            export = pd.DataFrame(dashboard["rows"]).to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download validation CSV",
                data=export,
                file_name=f"shadow_validation_{start_date}_{end_date}.csv",
                mime="text/csv",
            )

            st.markdown("#### All Evaluated Transitions")
            st.dataframe(_arrow_safe_rows(dashboard["rows"]), width="stretch", hide_index=True)
        else:
            st.info("Run multi-day validation to evaluate promotion readiness.")


    with calibration_tab:
        st.markdown("### Feature Contribution and Threshold Calibration")
        st.caption(
            "Walk-forward research for STRONG_SHADOW_SIGNAL by default. "
            "It measures which feature ranges separated 30-minute winners from failures. "
            "No score, threshold or execution rule is changed automatically."
        )

        c1, c2 = st.columns(2)
        calibration_start = c1.date_input(
            "Calibration start date",
            value=date.today() - timedelta(days=75),
            key="shadow_calibration_start",
        )
        calibration_end = c2.date_input(
            "Calibration end date",
            value=date.today(),
            key="shadow_calibration_end",
        )
        calibration_strength = st.selectbox(
            "Calibration decision strength",
            ("STRONG_SHADOW_SIGNAL", "SHADOW_SIGNAL", "TRANSITION_FORMING"),
            index=0,
            key="shadow_calibration_strength",
        )
        minimum_segment_samples = st.number_input(
            "Minimum samples per feature segment",
            min_value=5,
            max_value=100,
            value=10,
            step=5,
            key="shadow_calibration_min_samples",
        )

        if st.button(
            "Run feature calibration",
            type="primary",
            key="shadow_calibration_run",
        ):
            try:
                historical = _historical_service(token, layout)
                validator = MultiDayShadowValidationService()
                frames = {}
                days = validator.trading_dates(
                    calibration_start,
                    calibration_end,
                )
                progress = st.progress(0.0, text="Building calibration dataset...")
                for index, trading_day in enumerate(days, start=1):
                    try:
                        frame = _completed_five_minute_rows(
                            _load_day(historical, instrument_key, trading_day)
                        )
                        if len(frame) >= 35:
                            frames[trading_day] = frame
                    except Exception:
                        pass
                    progress.progress(
                        index / max(1, len(days)),
                        text=f"Processed {trading_day}",
                    )
                progress.empty()

                rows = build_calibration_rows(
                    frames,
                    minimum_decision=calibration_strength,
                )
                result = ShadowFeatureCalibrationService().analyze(
                    rows,
                    minimum_segment_samples=int(minimum_segment_samples),
                )
                st.session_state["shadow_feature_calibration"] = result
            except Exception as exc:
                st.error(
                    f"Feature calibration failed: {type(exc).__name__}: {exc}"
                )

        result = st.session_state.get("shadow_feature_calibration")
        if result:
            baseline = result["baseline"]
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Calibration Rows", int(baseline.get("samples") or 0))
            b2.metric("Resolved 30m", int(baseline.get("resolved_30m") or 0))
            b3.metric(
                "Baseline 30m Accuracy",
                f"{float(baseline.get('accuracy_30m') or 0):.1f}%",
            )
            b4.metric(
                "MFE / MAE",
                (
                    f"{float(baseline.get('average_mfe') or 0):.2f} / "
                    f"{float(baseline.get('average_mae') or 0):.2f}"
                ),
            )

            st.warning(
                "CALIBRATION OUTPUT IS RESEARCH ONLY. "
                "Do not change weights from in-sample results without "
                "a separate out-of-sample validation period."
            )

            st.markdown("#### Research Recommendations")
            recommendations = result.get("recommendations") or []
            if recommendations:
                st.dataframe(
                    _arrow_safe_rows(recommendations),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info(
                    "No segment currently meets the minimum sample, accuracy "
                    "and lift requirements for a calibration recommendation."
                )

            st.markdown("#### Strongest Feature Segments")
            st.dataframe(
                _arrow_safe_rows(result.get("strongest_segments") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Weakest Feature Segments")
            st.dataframe(
                _arrow_safe_rows(result.get("weakest_segments") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Numeric Feature Quartiles")
            st.dataframe(
                _arrow_safe_rows(result.get("numeric_segments") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Direction, Regime, Structure and Time")
            st.dataframe(
                _arrow_safe_rows(result.get("categorical_segments") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Individual Evidence Tags")
            st.dataframe(
                _arrow_safe_rows(result.get("evidence_segments") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Evidence Pairs")
            st.dataframe(
                _arrow_safe_rows(result.get("evidence_pair_segments") or []),
                width="stretch",
                hide_index=True,
            )

            export = pd.DataFrame(result.get("rows") or []).to_csv(
                index=False
            ).encode("utf-8")
            st.download_button(
                "Download calibration dataset CSV",
                data=export,
                file_name=(
                    f"shadow_feature_calibration_"
                    f"{calibration_start}_{calibration_end}.csv"
                ),
                mime="text/csv",
                key="shadow_calibration_download",
            )
        else:
            st.info(
                "Run calibration after collecting at least 100 strong shadow "
                "transitions across multiple market regimes."
            )



    with oos_tab:
        st.markdown("### Out-of-Sample Validation")
        st.caption(
            "Validates the calibration candidate on a separate date range. "
            "Groups are compared side by side and remain observation-only."
        )

        c1, c2 = st.columns(2)
        oos_start = c1.date_input(
            "Out-of-sample start date",
            value=date.today() - timedelta(days=28),
            key="shadow_oos_start",
        )
        oos_end = c2.date_input(
            "Out-of-sample end date",
            value=date.today(),
            key="shadow_oos_end",
        )

        c3, c4 = st.columns(2)
        adx_threshold = c3.number_input(
            "ADX slope threshold",
            value=2.136,
            step=0.1,
            format="%.3f",
            key="shadow_oos_adx_threshold",
        )
        displacement_threshold = c4.number_input(
            "Directional displacement ATR threshold",
            value=2.445,
            step=0.1,
            format="%.3f",
            key="shadow_oos_displacement_threshold",
        )

        if st.button(
            "Run out-of-sample validation",
            type="primary",
            key="shadow_oos_run",
        ):
            try:
                historical = _historical_service(token, layout)
                validator = MultiDayShadowValidationService()
                frames = {}
                days = validator.trading_dates(oos_start, oos_end)
                progress = st.progress(0.0, text="Building out-of-sample dataset...")
                for index, trading_day in enumerate(days, start=1):
                    try:
                        frame = _completed_five_minute_rows(
                            _load_day(historical, instrument_key, trading_day)
                        )
                        if len(frame) >= 35:
                            frames[trading_day] = frame
                    except Exception:
                        pass
                    progress.progress(
                        index / max(1, len(days)),
                        text=f"Processed {trading_day}",
                    )
                progress.empty()

                rows = build_calibration_rows(
                    frames,
                    minimum_decision="STRONG_SHADOW_SIGNAL",
                )
                result = ShadowOutOfSampleValidationService().evaluate(
                    rows,
                    adx_slope_threshold=float(adx_threshold),
                    directional_displacement_threshold=float(displacement_threshold),
                )
                st.session_state["shadow_oos_result"] = result
            except Exception as exc:
                st.error(
                    f"Out-of-sample validation failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        result = st.session_state.get("shadow_oos_result")
        if result:
            summaries = result.get("summaries") or []
            st.markdown("#### Side-by-Side Group Comparison")
            st.dataframe(
                _arrow_safe_rows(summaries),
                width="stretch",
                hide_index=True,
            )

            calibrated = next(
                (
                    row for row in summaries
                    if row.get("group") == "CALIBRATED_BULLISH_BREAKOUT"
                ),
                None,
            )
            if calibrated:
                if calibrated.get("eligible"):
                    st.success(
                        "CALIBRATED_BULLISH_BREAKOUT PASSED ALL "
                        "OUT-OF-SAMPLE GATES. Execution still remains blocked."
                    )
                else:
                    for warning in calibrated.get("warnings") or []:
                        st.warning(str(warning))

            selected_group = st.selectbox(
                "Inspect group",
                [str(row.get("group")) for row in summaries],
                key="shadow_oos_group",
            )
            detail = (result.get("details") or {}).get(selected_group, {})

            st.markdown("#### Performance by Regime")
            st.dataframe(
                _arrow_safe_rows(detail.get("by_regime") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Performance by Time of Day")
            st.dataframe(
                _arrow_safe_rows(detail.get("by_time_bucket") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Performance by Trading Day")
            st.dataframe(
                _arrow_safe_rows(detail.get("by_trading_date") or []),
                width="stretch",
                hide_index=True,
            )

            export = pd.DataFrame(detail.get("rows") or []).to_csv(
                index=False
            ).encode("utf-8")
            st.download_button(
                "Download selected group CSV",
                data=export,
                file_name=f"shadow_oos_{selected_group}_{oos_start}_{oos_end}.csv",
                mime="text/csv",
                key="shadow_oos_download",
            )
        else:
            st.info(
                "Use a date range that was not used for calibration. "
                "Recommended first run: 2026/07/16 to 2026/08/13."
            )



    with stability_tab:
        st.markdown("### Regime and Period Stability Analysis")
        st.caption(
            "Compares calibration and out-of-sample periods to identify "
            "accuracy decay, volatility changes, regime dependence, failure "
            "clusters and repeated same-direction signals."
        )

        c1, c2 = st.columns(2)
        calibration_start = c1.date_input(
            "Calibration period start",
            value=date(2026, 5, 30),
            key="shadow_stability_cal_start",
        )
        calibration_end = c2.date_input(
            "Calibration period end",
            value=date(2026, 7, 15),
            key="shadow_stability_cal_end",
        )

        c3, c4 = st.columns(2)
        oos_start = c3.date_input(
            "Out-of-sample period start",
            value=date(2026, 7, 16),
            key="shadow_stability_oos_start",
        )
        oos_end = c4.date_input(
            "Out-of-sample period end",
            value=date(2026, 8, 13),
            key="shadow_stability_oos_end",
        )

        cooldown_minutes = st.number_input(
            "Same-direction duplicate/cooldown window (minutes)",
            min_value=5,
            max_value=120,
            value=30,
            step=5,
            key="shadow_stability_cooldown",
        )

        if st.button(
            "Run regime and period stability analysis",
            type="primary",
            key="shadow_stability_run",
        ):
            try:
                historical = _historical_service(token, layout)
                validator = MultiDayShadowValidationService()

                def load_range(start_day, end_day):
                    frames = {}
                    days = validator.trading_dates(start_day, end_day)
                    for trading_day in days:
                        try:
                            frame = _completed_five_minute_rows(
                                _load_day(historical, instrument_key, trading_day)
                            )
                            if len(frame) >= 35:
                                frames[trading_day] = frame
                        except Exception:
                            pass
                    return frames

                progress = st.progress(0.0, text="Loading calibration period...")
                calibration_frames = load_range(
                    calibration_start,
                    calibration_end,
                )
                progress.progress(0.5, text="Loading out-of-sample period...")
                oos_frames = load_range(oos_start, oos_end)

                calibration_rows = build_calibration_rows(
                    calibration_frames,
                    minimum_decision="STRONG_SHADOW_SIGNAL",
                )
                oos_rows = build_calibration_rows(
                    oos_frames,
                    minimum_decision="STRONG_SHADOW_SIGNAL",
                )

                result = ShadowRegimePeriodStabilityService().analyze(
                    calibration_rows,
                    oos_rows,
                    cooldown_minutes=int(cooldown_minutes),
                )
                st.session_state["shadow_stability_result"] = result
                progress.empty()
            except Exception as exc:
                st.error(
                    f"Stability analysis failed: {type(exc).__name__}: {exc}"
                )

        result = st.session_state.get("shadow_stability_result")
        if result:
            st.markdown("#### Period Comparison")
            st.dataframe(
                _arrow_safe_rows(result.get("period_comparison") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Stability Findings")
            findings = result.get("findings") or []
            for finding in findings:
                severity = str(finding.get("severity") or "INFO")
                message = f"{finding.get('code')}: {finding.get('message')}"
                if severity == "HIGH":
                    st.error(message)
                elif severity == "MEDIUM":
                    st.warning(message)
                else:
                    st.info(message)

            st.markdown("#### Duplicate Signal Density")
            st.dataframe(
                _arrow_safe_rows([result.get("duplicate_density") or {}]),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Consecutive Failure Clusters")
            clusters = result.get("failure_clusters") or []
            if clusters:
                st.dataframe(
                    _arrow_safe_rows(clusters),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.caption("No consecutive failure cluster of length two or more.")

            comparisons = [
                ("Weekly Performance", "calibration_by_week", "oos_by_week"),
                ("Regime Performance", "calibration_by_regime", "oos_by_regime"),
                ("Direction Performance", "calibration_by_direction", "oos_by_direction"),
                ("Time-of-Day Performance", "calibration_by_time", "oos_by_time"),
                ("Volatility Performance", "calibration_by_volatility", "oos_by_volatility"),
            ]
            for heading, calibration_key, oos_key in comparisons:
                st.markdown(f"#### {heading}")
                left, right = st.columns(2)
                left.caption("Calibration")
                left.dataframe(
                    _arrow_safe_rows(result.get(calibration_key) or []),
                    width="stretch",
                    hide_index=True,
                )
                right.caption("Out of sample")
                right.dataframe(
                    _arrow_safe_rows(result.get(oos_key) or []),
                    width="stretch",
                    hide_index=True,
                )

            cal_export = pd.DataFrame(
                result.get("calibration_rows") or []
            ).to_csv(index=False).encode("utf-8")
            oos_export = pd.DataFrame(
                result.get("out_of_sample_rows") or []
            ).to_csv(index=False).encode("utf-8")
            e1, e2 = st.columns(2)
            e1.download_button(
                "Download calibration stability rows",
                data=cal_export,
                file_name="shadow_stability_calibration.csv",
                mime="text/csv",
                key="shadow_stability_cal_download",
            )
            e2.download_button(
                "Download out-of-sample stability rows",
                data=oos_export,
                file_name="shadow_stability_oos.csv",
                mime="text/csv",
                key="shadow_stability_oos_download",
            )
        else:
            st.info(
                "Run the analysis with non-overlapping calibration and "
                "out-of-sample date ranges."
            )



    with lifecycle_tab:
        st.markdown("### Cooldown, Deduplication and Confirmation Simulation")
        st.caption(
            "Simulates alternative signal-lifecycle controls on historical "
            "STRONG_SHADOW_SIGNAL rows. No production rule is changed."
        )

        c1, c2 = st.columns(2)
        lifecycle_start = c1.date_input(
            "Simulation start date",
            value=date(2026, 7, 16),
            key="shadow_lifecycle_start",
        )
        lifecycle_end = c2.date_input(
            "Simulation end date",
            value=date(2026, 8, 13),
            key="shadow_lifecycle_end",
        )

        if st.button(
            "Run lifecycle simulations",
            type="primary",
            key="shadow_lifecycle_run",
        ):
            try:
                historical = _historical_service(token, layout)
                validator = MultiDayShadowValidationService()
                frames = {}
                days = validator.trading_dates(lifecycle_start, lifecycle_end)
                progress = st.progress(0.0, text="Building lifecycle simulation dataset...")
                for index, trading_day in enumerate(days, start=1):
                    try:
                        frame = _completed_five_minute_rows(
                            _load_day(historical, instrument_key, trading_day)
                        )
                        if len(frame) >= 35:
                            frames[trading_day] = frame
                    except Exception:
                        pass
                    progress.progress(
                        index / max(1, len(days)),
                        text=f"Processed {trading_day}",
                    )
                progress.empty()

                rows = build_calibration_rows(
                    frames,
                    minimum_decision="STRONG_SHADOW_SIGNAL",
                )
                result = ShadowSignalLifecycleSimulationService().evaluate(rows)
                st.session_state["shadow_lifecycle_result"] = result
            except Exception as exc:
                st.error(
                    f"Lifecycle simulation failed: {type(exc).__name__}: {exc}"
                )

        result = st.session_state.get("shadow_lifecycle_result")
        if result:
            st.markdown("#### Side-by-Side Simulation Comparison")
            st.dataframe(
                _arrow_safe_rows(result.get("summaries") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Ranked Simulations")
            st.dataframe(
                _arrow_safe_rows(result.get("ranked") or []),
                width="stretch",
                hide_index=True,
            )

            names = [
                str(row.get("simulation"))
                for row in result.get("summaries") or []
            ]
            selected = st.selectbox(
                "Inspect lifecycle simulation",
                names,
                key="shadow_lifecycle_selected",
            )
            detail = (result.get("details") or {}).get(selected, {})

            st.markdown("#### Performance by Regime")
            st.dataframe(
                _arrow_safe_rows(detail.get("by_regime") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Performance by Time of Day")
            st.dataframe(
                _arrow_safe_rows(detail.get("by_time_bucket") or []),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Suppression Reasons")
            st.dataframe(
                _arrow_safe_rows(detail.get("suppression_reasons") or []),
                width="stretch",
                hide_index=True,
            )

            a1, a2 = st.columns(2)
            accepted_csv = pd.DataFrame(
                detail.get("accepted") or []
            ).to_csv(index=False).encode("utf-8")
            suppressed_csv = pd.DataFrame(
                detail.get("suppressed") or []
            ).to_csv(index=False).encode("utf-8")

            a1.download_button(
                "Download accepted signals",
                data=accepted_csv,
                file_name=f"shadow_lifecycle_{selected}_accepted.csv",
                mime="text/csv",
                key="shadow_lifecycle_accepted_download",
            )
            a2.download_button(
                "Download suppressed signals",
                data=suppressed_csv,
                file_name=f"shadow_lifecycle_{selected}_suppressed.csv",
                mime="text/csv",
                key="shadow_lifecycle_suppressed_download",
            )

            st.warning(
                "Simulation results are historical counterfactuals only. "
                "They must pass a separate out-of-sample validation before any "
                "lifecycle rule is added to Paper Trading."
            )
        else:
            st.info(
                "Run the first simulation on the existing out-of-sample range "
                "2026/07/16 to 2026/08/13."
            )



    with stateful_tab:
        st.markdown("### Stateful Multi-Timeframe Regime Engine")
        st.caption(
            "Combines completed 5-minute regime facts with completed 1-minute "
            "early-transition structure. Red Bar is supporting evidence only."
        )
        stateful_date = st.date_input(
            "Regime evaluation date",
            value=date.today(),
            key="stateful_v43_date",
        )
        if st.button(
            "Evaluate stateful regime",
            type="primary",
            key="stateful_v43_evaluate",
        ):
            try:
                historical = _historical_service(token, layout)
                historical.load_or_download(
                    instrument_key, stateful_date, stateful_date,
                    interval_minutes=1, force=False,
                )
                historical.load_or_download(
                    instrument_key, stateful_date, stateful_date,
                    interval_minutes=5, force=False,
                )
                one = _completed_five_minute_rows(
                    historical.read_day(
                        instrument_key, stateful_date, interval_minutes=1
                    )
                )
                five = _completed_five_minute_rows(
                    historical.read_day(
                        instrument_key, stateful_date, interval_minutes=5
                    )
                )
                safe = layout._safe_instrument(instrument_key)
                store = StatefulRegimeStore(
                    layout.settings.runs_root
                    / "stateful_regime_v43"
                    / f"{safe}.jsonl"
                )
                previous = store.latest()
                snapshot = StatefulMultiTimeframeRegimeEngine().evaluate(
                    one, five, previous_state=previous,
                ).as_record()
                snapshot["instrument_key"] = instrument_key

                inserted = store.append_once(snapshot)

                transition_store = TransitionSequenceStore(
                    layout.settings.runs_root
                    / "transition_sequence_v43"
                    / f"{safe}.jsonl"
                )
                previous_transition = transition_store.latest()
                transition_state = TransitionSequenceStateMachine().advance(
                    snapshot,
                    previous=previous_transition,
                )
                transition_record = (
                    transition_state.as_record()
                    if transition_state is not None else None
                )
                setup_records = []
                attribution_records = []
                if transition_record is not None:
                    transition_store.append_once(transition_record)
                    attribution = build_attribution_context(
                        snapshot,
                        transition_record,
                    ).as_record()

                    signal_store = FreshSetupSignalStore(
                        layout.settings.runs_root
                        / "fresh_setup_signals_v43"
                        / f"{safe}.jsonl"
                    )
                    setup_signals = FreshSetupSignalEngine().detect(
                        snapshot,
                        transition_record,
                        attribution,
                    )
                    generated_records = [
                        signal.as_record() for signal in setup_signals
                    ]
                    setup_records, inserted_signals = (
                        signal_store.resolve_many_once(generated_records)
                    )
                    attribution_records = [
                        attach_signal_to_attribution(attribution, record)
                        for record in setup_records
                    ]

                    bundle_records = [
                        bundle.as_record()
                        for bundle in build_setup_bundles(setup_records)
                    ]
                    bundle_store = FreshSetupBundleStore(
                        layout.settings.runs_root
                        / "fresh_setup_bundles_v43"
                        / f"{safe}.jsonl"
                    )
                    bundle_store.append_many_once(bundle_records)

                    ledger_store = SignalTradeAttributionStore(
                        layout.settings.runs_root
                        / "signal_trade_attribution_v43"
                        / f"{safe}.jsonl"
                    )
                    ledger_records = []
                    for bundle_record in bundle_records:
                        existing_ledger = ledger_store.by_bundle(
                            str(bundle_record.get("bundle_id") or "")
                        )
                        if existing_ledger is None:
                            ledger_record = create_ledger_record(
                                bundle_record,
                                instrument_key=instrument_key,
                            ).as_record()
                            ledger_store.upsert(ledger_record)
                        else:
                            ledger_record = existing_ledger
                        ledger_records.append(ledger_record)
                else:
                    attribution = None

                st.session_state["stateful_v43_snapshot"] = snapshot
                st.session_state["stateful_v43_transition"] = transition_record
                st.session_state["stateful_v43_attribution"] = attribution
                st.session_state["stateful_v43_signals"] = setup_records
                st.session_state["stateful_v43_signal_attributions"] = attribution_records
                st.session_state["stateful_v43_bundles"] = (
                    bundle_records if transition_record is not None else []
                )
                st.session_state["stateful_v43_ledger_records"] = (
                    ledger_records if transition_record is not None else []
                )
                st.success(
                    "Stateful regime and transition sequence stored."
                    if inserted else
                    "Stateful regime evaluated; duplicate regime storage skipped."
                )
            except Exception as exc:
                st.error(
                    f"Stateful regime evaluation failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        snapshot = st.session_state.get("stateful_v43_snapshot")
        if snapshot:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Current Regime", snapshot.get("current_regime"))
            c2.metric("Previous Regime", snapshot.get("previous_regime"))
            c3.metric("Bullish Score", snapshot.get("bullish_score"))
            c4.metric("Bearish Score", snapshot.get("bearish_score"))
            c5.metric("Execution", "BLOCKED")
            st.markdown("#### Transition State")
            st.dataframe(
                _arrow_safe_rows([{
                    "transition_stage": snapshot.get("transition_stage"),
                    "transition_progress": snapshot.get("transition_progress"),
                    "five_minute_regime": snapshot.get("five_minute_regime"),
                    "one_minute_state": snapshot.get("one_minute_state"),
                    "last_swing_high": snapshot.get("last_swing_high"),
                    "last_swing_low": snapshot.get("last_swing_low"),
                    "swing_high_timestamp": snapshot.get("swing_high_timestamp"),
                    "swing_low_timestamp": snapshot.get("swing_low_timestamp"),
                    "structure_status": snapshot.get("structure_status"),
                    "break_level": snapshot.get("break_level"),
                    "invalidation_level": snapshot.get("invalidation_level"),
                    "red_bar_support": snapshot.get("red_bar_support"),
                }]),
                width="stretch",
                hide_index=True,
            )
            transition = st.session_state.get("stateful_v43_transition")
            if transition:
                st.markdown("#### Persistent Transition Sequence")
                t1, t2, t3, t4 = st.columns(4)
                t1.metric("Transition ID", str(transition.get("transition_id")))
                t2.metric("Status", str(transition.get("status")))
                t3.metric("Stage", str(transition.get("stage")))
                t4.metric(
                    "Progress",
                    f"{float(transition.get('progress_pct') or 0):.1f}%",
                )
                st.dataframe(
                    _arrow_safe_rows([transition]),
                    width="stretch",
                    hide_index=True,
                )

                attribution = st.session_state.get("stateful_v43_attribution")
                if attribution:
                    st.markdown("#### Attribution Seed")
                    st.dataframe(
                        _arrow_safe_rows([attribution]),
                        width="stretch",
                        hide_index=True,
                    )

            signals = st.session_state.get("stateful_v43_signals") or []
            if signals:
                st.markdown("#### Fresh Setup Signals")
                st.dataframe(
                    _arrow_safe_rows(signals),
                    width="stretch",
                    hide_index=True,
                )

                bundles = st.session_state.get("stateful_v43_bundles") or []
                if bundles:
                    st.markdown("#### Setup Bundle")
                    st.caption(
                        "One primary trigger is selected per transition timestamp. "
                        "Other detected setups remain supporting signals."
                    )
                    st.dataframe(
                        _arrow_safe_rows(bundles),
                        width="stretch",
                        hide_index=True,
                    )

                ledger_records = (
                    st.session_state.get("stateful_v43_ledger_records") or []
                )
                if ledger_records:
                    st.markdown("#### Signal-to-Trade Attribution Ledger")
                    st.caption(
                        "Candidate, opportunity, Committee and trade IDs remain "
                        "empty until the existing pipeline links them."
                    )
                    st.dataframe(
                        _arrow_safe_rows(ledger_records),
                        width="stretch",
                        hide_index=True,
                    )

                st.markdown("#### Signal Attribution")
                st.dataframe(
                    _arrow_safe_rows(
                        st.session_state.get(
                            "stateful_v43_signal_attributions"
                        ) or []
                    ),
                    width="stretch",
                    hide_index=True,
                )

                safe = layout._safe_instrument(instrument_key)
                signal_store = FreshSetupSignalStore(
                    layout.settings.runs_root
                    / "fresh_setup_signals_v43"
                    / f"{safe}.jsonl"
                )
                st.markdown("#### Generated Signals by Type")
                st.dataframe(
                    _arrow_safe_rows(signal_store.counts_by_type()),
                    width="stretch",
                    hide_index=True,
                )

                st.markdown("#### Recent Fresh Setup History")
                st.dataframe(
                    _arrow_safe_rows(signal_store.latest(limit=100)),
                    width="stretch",
                    hide_index=True,
                )

                ledger_store = SignalTradeAttributionStore(
                    layout.settings.runs_root
                    / "signal_trade_attribution_v43"
                    / f"{safe}.jsonl"
                )
                all_ledger_rows = ledger_store.read_all()

                st.markdown("#### Attribution Funnel")
                st.dataframe(
                    _arrow_safe_rows([funnel_summary(all_ledger_rows)]),
                    width="stretch",
                    hide_index=True,
                )

                st.markdown("#### Success by Primary Signal Type")
                st.dataframe(
                    _arrow_safe_rows(
                        summarize_by_primary_setup(all_ledger_rows)
                    ),
                    width="stretch",
                    hide_index=True,
                )

                st.markdown("#### Recent Attributed Trades and Outcomes")
                st.dataframe(
                    _arrow_safe_rows(ledger_store.latest(limit=100)),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info(
                    "No fresh setup signal was generated from the current "
                    "regime snapshot and transition."
                )

            st.markdown("#### Confirmed Swing Diagnostics")
            diagnostics = snapshot.get("structure_diagnostics") or []
            if diagnostics:
                st.dataframe(
                    _arrow_safe_rows(diagnostics),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("No confirmed pivot structure is available.")

            st.markdown("#### Evidence")
            st.code(
                "\n".join(
                    f"• {item}" for item in snapshot.get("evidence") or []
                ),
                language=None,
            )
        else:
            st.info("Run the stateful multi-timeframe evaluation.")


    st.caption(
        "Sprint 4.2 remains observation-only. Validation results cannot create, "
        "approve, enter, manage or exit any trade."
    )

    with attribution_replay_tab:
        st.markdown("### Range-Based Historical Attribution Audit")
        st.caption(
            "Read-only audit. It does not create candidates, Committee "
            "decisions, queue items, paper orders or live orders."
        )

        preset_col, anchor_col = st.columns(2)
        preset = preset_col.selectbox(
            "Range preset",
            (
                "Single Day",
                "Previous 5 Trading Days",
                "Previous 10 Trading Days",
                "Previous Month",
                "Previous 3 Months",
                "Custom Range",
            ),
            key="historical_attribution_range_preset",
        )
        anchor_date = anchor_col.date_input(
            "Range anchor",
            value=date.today(),
            key="historical_attribution_anchor",
        )

        if preset == "Custom Range":
            range_cols = st.columns(2)
            audit_date_from = range_cols[0].date_input(
                "Start date",
                value=anchor_date - timedelta(days=6),
                key="historical_attribution_custom_from",
            )
            audit_date_to = range_cols[1].date_input(
                "End date",
                value=anchor_date,
                key="historical_attribution_custom_to",
            )
        else:
            audit_date_from, audit_date_to = resolve_range_preset(
                preset,
                anchor_date,
            )
            st.info(
                f"Selected range: {audit_date_from.isoformat()} "
                f"to {audit_date_to.isoformat()}"
            )

        session_col, direction_col, setup_col = st.columns(3)
        session = session_col.selectbox(
            "Market session",
            (
                "Full Session",
                "Opening",
                "Mid-Session",
                "Closing",
                "Custom Time",
            ),
            key="historical_attribution_session",
        )
        audit_direction = direction_col.selectbox(
            "Direction",
            ("ALL", "BULLISH", "BEARISH"),
            key="historical_attribution_direction",
        )
        audit_setup = setup_col.selectbox(
            "Primary setup",
            (
                "ALL",
                "BULLISH_STRUCTURE_BREAK",
                "BEARISH_STRUCTURE_BREAK",
                "BULLISH_RANGE_BREAKOUT",
                "BEARISH_RANGE_BREAKDOWN",
                "BULLISH_PULLBACK_CONTINUATION",
                "BEARISH_PULLBACK_CONTINUATION",
                "BULLISH_EMA_RECLAIM",
                "BEARISH_EMA_LOSS",
                "BULLISH_RED_BAR_CONFIRMATION",
                "BEARISH_RED_BAR_CONFIRMATION",
                "COUNTER_TREND_RED_BAR",
            ),
            key="historical_attribution_setup",
        )

        session_windows = {
            "Full Session": (time(9, 15), time(15, 30)),
            "Opening": (time(9, 15), time(10, 30)),
            "Mid-Session": (time(10, 30), time(14, 0)),
            "Closing": (time(14, 0), time(15, 30)),
        }
        if session == "Custom Time":
            time_cols = st.columns(2)
            audit_start_time = time_cols[0].time_input(
                "Start time",
                value=time(9, 15),
                key="historical_attribution_start_time",
            )
            audit_end_time = time_cols[1].time_input(
                "End time",
                value=time(15, 30),
                key="historical_attribution_end_time",
            )
        else:
            audit_start_time, audit_end_time = session_windows[session]

        persist_backfill = st.toggle(
            "Persist generated v4.3 research artifacts",
            value=True,
            key="historical_attribution_persist_backfill",
            help=(
                "Writes only v4.3 regime, transition, signal and bundle JSONL "
                "research artifacts. Candidate, Committee, queue and order "
                "tables remain read-only."
            ),
        )
        action_cols = st.columns(2)
        run_backfill = action_cols[0].button(
            "Backfill missing v4.3 bundles",
            type="secondary",
            key="run_historical_bundle_backfill",
        )
        run_audit = action_cols[1].button(
            "Run read-only historical audit",
            type="primary",
            key="run_historical_attribution_audit",
        )

        if run_backfill:
            try:
                historical = _historical_service(token, layout)
                backfill_result = HistoricalV43BundleBackfill(
                    historical=historical,
                    layout=layout,
                ).run(
                    HistoricalBundleBackfillRequest(
                        instrument_key=instrument_key,
                        date_from=audit_date_from,
                        date_to=audit_date_to,
                        start_time=audit_start_time,
                        end_time=audit_end_time,
                        persist_artifacts=persist_backfill,
                    )
                )
                st.session_state[
                    "historical_bundle_backfill_result"
                ] = backfill_result
                st.success("Historical v4.3 bundle backfill completed.")
            except Exception as exc:
                st.error(
                    "Historical v4.3 bundle backfill failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        backfill_result = st.session_state.get(
            "historical_bundle_backfill_result"
        )
        if backfill_result:
            st.markdown("#### Historical Bundle Backfill Summary")
            st.dataframe(
                _arrow_safe_rows([backfill_result["summary"]]),
                width="stretch",
                hide_index=True,
            )
            st.markdown("#### Backfill by Trading Day")
            st.dataframe(
                _arrow_safe_rows(backfill_result["days"]),
                width="stretch",
                hide_index=True,
            )
        if run_audit:
            try:
                audit_service = RangeHistoricalAttributionAudit(
                    database=database,
                    runs_root=layout.settings.runs_root,
                )
                audit_request = HistoricalAuditRequest(
                    instrument_key=instrument_key,
                    date_from=audit_date_from,
                    date_to=audit_date_to,
                    start_time=audit_start_time,
                    end_time=audit_end_time,
                    direction=audit_direction,
                    setup_type=audit_setup,
                )
                st.session_state[
                    "historical_attribution_audit_result"
                ] = audit_service.audit(audit_request)
                st.success("Historical source audit completed.")
            except Exception as exc:
                st.error(
                    "Historical attribution audit failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        audit_result = st.session_state.get(
            "historical_attribution_audit_result"
        )
        if audit_result:
            st.markdown("#### Audit Summary")
            st.dataframe(
                _arrow_safe_rows([audit_result["summary"]]),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Historical Source Availability")
            st.dataframe(
                _arrow_safe_rows(audit_result["sources"]),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Bundle-to-Pipeline Matches")
            if audit_result["matches"]:
                st.dataframe(
                    _arrow_safe_rows(audit_result["matches"]),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info(
                    "No v4.3 setup bundles matched the selected date, "
                    "time, direction and setup filters."
                )

            st.markdown("#### Matching Interpretation")
            st.caption(
                "EXACT_SIGNAL_ID is direct identifier evidence. "
                "DIRECTION_AND_WINDOW is inferred historical alignment, "
                "not proof that v4.3 caused the pipeline event."
            )

