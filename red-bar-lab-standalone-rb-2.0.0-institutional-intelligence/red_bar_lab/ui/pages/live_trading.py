from red_bar_lab.ui._shared import *


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Live Trading")
    st.caption(
        "RB-0.6.12.1 adds a compact Current Trade Dashboard above Live / Open Signals with entry/current/exit/P&L information. RB-0.6.12 is the Trader Experience release: one Live page, precise entry/exit timestamps and prices, trader-friendly status, Current P/L beside EOD benchmark points, and a chronological Trade Timeline. RB-0.6.11 adds quality visibility and backtest filtering. RB-0.6.10 freezes 10 actionable models plus the informational EOD benchmark. RB-0.6.9 keeps completed signals visible and adds occurrence labels such as NEXT_RED_CANDLE_1. RB-0.6.8 stabilizes the live signal lifecycle with canonical IDs, automatic live paper-trade refresh, true OPEN models, target progress, and signal drill-down. RB-0.6.7.1 fixes Streamlit/PyArrow table compatibility and makes Points Gained plus SUCCESS/FAILED outcomes explicit. RB-0.6.7 adds trade-result classification, signal outcome summaries, and live P/L visibility. RB-0.6.6 adds live decision visibility. A completed 5-minute candle creates "
        "the setup; the next five 1-minute candles are checked for confirmation, "
        "with ACTIVE, WAITING and FAILED/TIMEOUT details shown below."
    )
    auto_refresh = st.toggle("Auto refresh live monitor", value=False)
    refresh_seconds = st.slider(
        "Refresh interval (seconds)", 5, 60, 15, 5,
        disabled=not auto_refresh,
    )

    def render_live_monitor() -> None:
        try:
            access_token = resolve_access_token(token)
            provider = RedBarUpstoxService(access_token)
            historical_live = RedBarHistoricalService(provider, layout)
            monitor = RedBarLiveService(
                historical_live, layout, database
            )
            result = monitor.refresh(instrument_key)

            # RB-0.7.4.2: intelligence enrichment is automatic but
            # remains fault-isolated from trading.
            try:
                option_service = RedBarOptionsContextService(
                    provider,
                    database,
                    settings,
                )
                option_capture = (
                    option_service.capture_recent_missing_signals(
                        instrument_key=instrument_key,
                        trading_date=result.trading_date.isoformat(),
                        alignment_tolerance_seconds=120,
                    )
                )
                dual_collector = RedBarDualMarketCollector(
                    provider,
                    database,
                    settings,
                )
                pipeline = RedBarIntelligencePipelineOrchestrator(
                    historical=historical_live,
                    database=database,
                    settings=settings,
                    options_collector=dual_collector,
                )
                pipeline_report = pipeline.sync_day(
                    instrument_key=instrument_key,
                    trading_date=result.trading_date.isoformat(),
                    link_window_seconds=120,
                )
                if (
                    option_capture.entry_aligned
                    or pipeline_report.market_built
                    or pipeline_report.volume_built
                    or pipeline_report.options_linked
                ):
                    st.caption(
                        "Intelligence pipeline synchronized automatically."
                    )
            except Exception:
                # Intelligence enrichment must never interrupt Live Trading.
                pass

            if result.connected:
                st.success(result.message)
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("1-minute rows", result.source_rows)
                c2.metric("Completed 5-minute", result.completed_five_minute_rows)
                c3.metric("ACTIVE", result.active)
                c4.metric("Waiting 1m", result.awaiting)
                c5.metric("Failed / Timeout", result.failed)
                st.caption(
                    f"Last refresh: {result.last_refresh.strftime('%Y-%m-%d %H:%M:%S %Z')} · "
                    f"Levels stored: {result.levels_stored}"
                )
                if result.latest_completed_candle:
                    st.markdown("#### Latest completed 5-minute candle")
                    st.dataframe(
                        [result.latest_completed_candle],
                        width="stretch",
                        hide_index=True,
                    )
                st.markdown("#### Current Trade Dashboard")
                dashboard_rows = _current_dashboard_rows(
                    database,
                    instrument_key,
                    result.trading_date.isoformat(),
                    result.active_attempts,
                    result.completed_attempts,
                )
                if dashboard_rows:
                    st.dataframe(
                        _arrow_safe_rows(dashboard_rows),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.caption(
                        "No confirmed or completed trades available yet."
                    )

                st.markdown("#### Live / Open Signals")
                st.caption(
                    "Quality is based on actionable models already closed. "
                    "The EOD benchmark is informational only."
                )
                if result.active_attempts:
                    active_rows = []
                    for item in result.active_attempts:
                        live_points = item.get("live_points")
                        active_rows.append(
                            {
                                "signal_id": item.get("signal_id"),
                                "signal_label": item.get("signal_label"),
                                "signal_marker": item.get("signal_marker"),
                                "signal_sequence": item.get("signal_sequence"),
                                "priority": item.get("priority"),
                                "quality_symbol": item.get("quality_symbol"),
                                "level_type": item.get("level_type"),
                                "direction": item.get("direction"),
                                "trade_status": item.get("trade_status"),
                                "current_result": item.get("current_result"),
                                "entry_time_ist": _format_ist_time(
                                    item.get("confirmation_timestamp")
                                ),
                                "entry_price": item.get("underlying_entry"),
                                "stop_price": item.get("stop_price"),
                                "current_price": item.get("current_price"),
                                "current_p_l": (
                                    round(float(live_points), 2)
                                    if live_points is not None
                                    else None
                                ),
                                "live_result": (
                                    "PROFIT"
                                    if live_points is not None
                                    and float(live_points) > 0
                                    else "LOSS"
                                    if live_points is not None
                                    and float(live_points) < 0
                                    else "BREAKEVEN"
                                    if live_points is not None
                                    else "UNKNOWN"
                                ),
                                "live_mfe": (
                                    round(
                                        float(item["live_mfe_points"]), 2
                                    )
                                    if item.get("live_mfe_points") is not None
                                    else None
                                ),
                                "live_mae": (
                                    round(
                                        float(item["live_mae_points"]), 2
                                    )
                                    if item.get("live_mae_points") is not None
                                    else None
                                ),
                                "targets_hit": item.get("targets_hit"),
                                "next_target": item.get("next_target"),
                                "points_to_next_target": item.get(
                                    "points_to_next_target"
                                ),
                                "target_progress": item.get(
                                    "target_progress"
                                ),
                                "setup_high": item.get("cross_high"),
                                "setup_low": item.get("cross_low"),
                                "confirmation_delay_minutes": item.get(
                                    "confirmation_delay_minutes"
                                ),
                                "actionable_open": item.get(
                                    "actionable_open"
                                ),
                                "actionable_closed": item.get(
                                    "actionable_closed"
                                ),
                                "actionable_success": item.get(
                                    "actionable_success"
                                ),
                                "actionable_failed": item.get(
                                    "actionable_failed"
                                ),
                                "actionable_breakeven": item.get(
                                    "actionable_breakeven"
                                ),
                                "actionable_success_rate_pct": item.get(
                                    "actionable_success_rate_pct"
                                ),
                                "actionable_score": item.get(
                                    "actionable_score"
                                ),
                                "quality_explanation": item.get(
                                    "quality_explanation"
                                ),
                                "quality_symbol": item.get(
                                    "quality_symbol"
                                ),
                                "quality_band": item.get(
                                    "quality_band"
                                ),
                                "actionable_done_at": _format_ist_time(
                                    item.get("actionable_completed_at")
                                ),
                                "best_exit": item.get(
                                    "best_actionable_exit"
                                ),
                                "best_exit_time": _format_ist_time(
                                    item.get("best_actionable_exit_time")
                                ),
                                "best_exit_price": item.get(
                                    "best_actionable_exit_price"
                                ),
                                "best_points": _round_points(
                                    item.get("best_actionable_points")
                                ),
                                "signal_lifecycle": item.get(
                                    "signal_lifecycle"
                                ),
                                "signal_quality": item.get(
                                    "signal_quality"
                                ),
                                "benchmark_status": item.get(
                                    "benchmark_status"
                                ),
                                "benchmark_current_points": item.get(
                                    "benchmark_current_points"
                                ),
                                "eod_exit_time": _format_ist_time(
                                    item.get("benchmark_exit_time")
                                ),
                                "eod_exit_price": item.get(
                                    "benchmark_exit_price"
                                ),
                                "eod_points": (
                                    item.get("benchmark_final_points")
                                    if item.get("benchmark_status") == "CLOSED"
                                    else item.get("benchmark_current_points")
                                ),
                                "reason": item.get("reason"),
                            }
                        )
                    st.dataframe(
                        _arrow_safe_rows(active_rows),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.info("No ACTIVE Red Bar signal yet.")

                if result.active_attempts:
                    st.markdown("#### Signal Details")
                    signal_options = {
                        (
                            f"{item.get('signal_label')} | "
                            f"{item.get('trade_status')} | "
                            f"{item.get('current_result')}"
                        ): item
                        for item in result.active_attempts
                        if item.get("signal_id")
                    }
                    selected_live_label = st.selectbox(
                        "Inspect signal",
                        list(signal_options.keys()),
                        key="live_signal_drilldown",
                    )
                    selected_item = signal_options[selected_live_label]
                    selected_signal_id = str(
                        selected_item.get("signal_id")
                    )
                    live_trade_rows = [
                        row
                        for row in database.read_paper_trade_outcomes(
                            instrument_key,
                            result.trading_date.isoformat(),
                        )
                        if row.get("signal_id") == selected_signal_id
                    ]

                    actionable = summarize_actionable_models(
                        live_trade_rows
                    )
                    benchmark = benchmark_summary(
                        live_trade_rows,
                        current_price=selected_item.get(
                            "current_price"
                        ),
                        direction=selected_item.get("direction"),
                        entry_price=selected_item.get(
                            "underlying_entry"
                        ),
                    )
                    eod_points = (
                        benchmark.get("benchmark_final_points")
                        if benchmark.get("benchmark_status") == "CLOSED"
                        else benchmark.get(
                            "benchmark_current_points"
                        )
                    )

                    d1, d2, d3, d4 = st.columns(4)
                    d1.metric(
                        "Trade Status",
                        str(
                            selected_item.get("trade_status")
                            or "—"
                        ),
                    )
                    current_pl = _round_points(
                        selected_item.get("live_points")
                    )
                    d2.metric(
                        "Current P/L",
                        (
                            f"{current_pl:+.2f}"
                            if current_pl is not None
                            else "—"
                        ),
                    )
                    d3.metric(
                        "Actionable Score",
                        str(
                            selected_item.get(
                                "actionable_score"
                            )
                            or "—"
                        ),
                    )
                    d4.metric(
                        "EOD Benchmark",
                        (
                            f"{float(eod_points):+.2f}"
                            if eod_points is not None
                            else "—"
                        ),
                    )

                    precise = [{
                        "signal": selected_item.get("signal_label"),
                        "signal_marker": selected_item.get(
                            "signal_marker"
                        ),
                        "direction": selected_item.get("direction"),
                        "trade_status": selected_item.get(
                            "trade_status"
                        ),
                        "current_result": selected_item.get(
                            "current_result"
                        ),
                        "entry_time_ist": _format_ist_time(
                            selected_item.get(
                                "confirmation_timestamp"
                            )
                        ),
                        "entry_price": selected_item.get(
                            "underlying_entry"
                        ),
                        "stop_price": selected_item.get(
                            "stop_price"
                        ),
                        "current_price": selected_item.get(
                            "current_price"
                        ),
                        "current_p_l": current_pl,
                        "targets_hit": selected_item.get(
                            "targets_hit"
                        ),
                        "points_to_next_target": selected_item.get(
                            "points_to_next_target"
                        ),
                        "actionable_done_at": _format_ist_time(
                            actionable.get(
                                "actionable_completed_at"
                            )
                        ),
                        "best_exit": actionable.get(
                            "best_actionable_exit"
                        ),
                        "best_exit_time": _format_ist_time(
                            actionable.get(
                                "best_actionable_exit_time"
                            )
                        ),
                        "best_exit_price": actionable.get(
                            "best_actionable_exit_price"
                        ),
                        "best_points": _round_points(
                            actionable.get(
                                "best_actionable_points"
                            )
                        ),
                        "eod_status": benchmark.get(
                            "benchmark_status"
                        ),
                        "eod_exit_time": _format_ist_time(
                            benchmark.get("benchmark_exit_time")
                        ),
                        "eod_exit_price": benchmark.get(
                            "benchmark_exit_price"
                        ),
                        "eod_points": _round_points(eod_points),
                    }]

                    st.markdown("##### Precise Entry / Exit")
                    st.dataframe(
                        _arrow_safe_rows(precise),
                        width="stretch",
                        hide_index=True,
                    )

                    if live_trade_rows:
                        st.markdown(
                            "##### 10 Actionable Models + EOD Benchmark"
                        )
                        st.dataframe(
                            _trade_display_rows(live_trade_rows),
                            width="stretch",
                            hide_index=True,
                        )
                        st.markdown("##### Trade Timeline")
                        st.dataframe(
                            _arrow_safe_rows(
                                _trade_timeline_rows(
                                    live_trade_rows
                                )
                            ),
                            width="stretch",
                            hide_index=True,
                        )
                    else:
                        st.info(
                            "No paper-trade models are linked to this "
                            "signal yet."
                        )

                st.markdown("#### Completed Signals Today")
                st.caption(
                    "Quality explanation uses the 10 actionable models only. "
                    "Example: 9W / 1L / 0BE = 9/10."
                )
                if result.completed_attempts:
                    st.dataframe(
                        _arrow_safe_rows(result.completed_attempts),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.caption(
                        "No signal has fully completed all trade models yet."
                    )

                if result.completed_attempts:
                    st.markdown("#### Completed Signal Drill-down")
                    completed_options = {
                        (
                            f"{item.get('signal_label')} | "
                            f"{item.get('signal_id')}"
                        ): str(item.get("signal_id"))
                        for item in result.completed_attempts
                        if item.get("signal_id")
                    }
                    selected_completed_label = st.selectbox(
                        "Inspect completed signal",
                        list(completed_options.keys()),
                        key="completed_signal_drilldown",
                    )
                    selected_completed_signal = completed_options[
                        selected_completed_label
                    ]
                    completed_trade_rows = [
                        row
                        for row in database.read_paper_trade_outcomes(
                            instrument_key,
                            result.trading_date.isoformat(),
                        )
                        if row.get("signal_id")
                        == selected_completed_signal
                    ]
                    if completed_trade_rows:
                        st.dataframe(
                            _trade_display_rows(completed_trade_rows),
                            width="stretch",
                            hide_index=True,
                        )

                st.markdown("#### Waiting for 1-minute confirmation")
                if result.awaiting_attempts:
                    for index, item in enumerate(
                        result.awaiting_attempts, start=1
                    ):
                        title = (
                            f"{item['level_type']} · {item['direction']} · "
                            f"{item['confirmation_candles_checked']}/5 checked"
                        )
                        with st.expander(title, expanded=True):
                            st.write(
                                f"**Required:** {item['required_condition']} "
                                f"**{item['required_price']}**"
                            )
                            st.write(f"**Status:** {item['reason']}")
                            if item["confirmation_window"]:
                                st.dataframe(
                                    _arrow_safe_rows(
                                        item["confirmation_window"]
                                    ),
                                    width="stretch",
                                    hide_index=True,
                                )
                else:
                    st.caption("No setup is currently waiting for confirmation.")

                st.markdown("#### Failed / timed-out setups")
                if result.failed_attempts:
                    for index, item in enumerate(
                        result.failed_attempts, start=1
                    ):
                        title = (
                            f"{item['level_type']} · {item['direction']} · "
                            f"{item['state']}"
                        )
                        with st.expander(title, expanded=(index == 1)):
                            d1, d2, d3 = st.columns(3)
                            d1.metric("Midpoint", item["level_value"])
                            d2.metric("Setup High", item["cross_high"])
                            d3.metric("Setup Low", item["cross_low"])
                            st.write(
                                f"**Failure reason:** `{item['reason']}`"
                            )
                            st.write(
                                f"**Required:** {item['required_condition']} "
                                f"**{item['required_price']}**"
                            )
                            st.write(
                                f"**Confirmation candles checked:** "
                                f"{item['confirmation_candles_checked']}/5"
                            )
                            if item["confirmation_window"]:
                                st.dataframe(
                                    _arrow_safe_rows(
                                        item["confirmation_window"]
                                    ),
                                    width="stretch",
                                    hide_index=True,
                                )
                else:
                    st.caption("No failed or timed-out setup yet.")

                st.markdown("#### Live event timeline")
                if result.event_timeline:
                    st.dataframe(
                        _arrow_safe_rows(result.event_timeline),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.caption("No strategy events yet.")
            else:
                st.warning(result.message)
        except MissingAccessToken as exc:
            st.error(str(exc))
        except Exception as exc:
            st.exception(exc)

    if auto_refresh:
        @st.fragment(run_every=f"{refresh_seconds}s")
        def live_fragment() -> None:
            render_live_monitor()
        live_fragment()
    elif st.button("Refresh Live Monitor", type="primary"):
        render_live_monitor()
