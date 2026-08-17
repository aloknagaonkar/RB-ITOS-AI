from red_bar_lab.services.historical_dri_replay import detect_historical_dri_events
from red_bar_lab.services.historical_dri_decision_replay import HistoricalDRIDecisionReplayService
from red_bar_lab.services.historical_dri_multiday_validation import validate_historical_dri_dates
from red_bar_lab.services.replay_opportunity_accounting import consolidate_replay_rows
from red_bar_lab.ui._shared import *
from red_bar_lab.services.historical_strategy_validation import default_strategy_registry
from red_bar_lab.services.historical_strategy_runner import (
    run_historical_strategy_validation,
)
from red_bar_lab.ui.historical_strategy_validation import (
    render_strategy_validation_results,
    render_strategy_validation_selector,
)


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Research Lab")

    try:
        generic_cached_reader = RedBarHistoricalService(
            RedBarUpstoxService("cache-only"), layout
        )
        generic_available_dates = generic_cached_reader.available_dates(
            instrument_key, interval_minutes=1
        )
    except Exception:
        generic_available_dates = []

    generic_registry = default_strategy_registry()
    generic_selection = render_strategy_validation_selector(
        generic_registry,
        generic_available_dates,
    )

    generic_run_disabled = (
        not generic_selection["dates"]
        or not generic_selection["compare"]
    )
    if st.button(
        "Run Generic Historical Validation",
        type="primary",
        disabled=generic_run_disabled,
        key="run_generic_historical_validation",
    ):
        try:
            generic_option_sync = HistoricalOptionChainSyncService(
                RedBarUpstoxService(token or "cache-only"),
                layout,
                generic_cached_reader,
                database=database,
            )
            with st.spinner(
                "Running research-only historical strategy validation..."
            ):
                generic_reports = run_historical_strategy_validation(
                    replay_reader=generic_cached_reader,
                    option_chain_sync=generic_option_sync,
                    instrument_key=instrument_key,
                    trading_dates=generic_selection["dates"],
                    strategies=generic_selection["compare"],
                    registry=generic_registry,
                )
            st.session_state[
                "generic_historical_validation_reports"
            ] = generic_reports
            st.session_state[
                "generic_historical_validation_signature"
            ] = (
                instrument_key,
                tuple(generic_selection["dates"]),
                tuple(generic_selection["compare"]),
            )
            st.success(
                f"Completed {len(generic_reports)} strategy validation "
                f"report(s) across "
                f"{len(generic_selection['dates'])} cached day(s)."
            )
        except Exception as exc:
            st.exception(exc)

    generic_reports = st.session_state.get(
        "generic_historical_validation_reports"
    )
    generic_signature = st.session_state.get(
        "generic_historical_validation_signature"
    )
    current_generic_signature = (
        instrument_key,
        tuple(generic_selection["dates"]),
        tuple(generic_selection["compare"]),
    )
    if generic_reports and generic_signature == current_generic_signature:
        render_strategy_validation_results(generic_reports)
    elif generic_reports:
        st.info(
            "The strategy or validation window changed. "
            "Run validation again to refresh the comparison."
        )

    st.markdown("---")
    st.markdown("#### Historical Data")
    today = date.today()
    start_date = st.date_input("From", today - timedelta(days=10))
    end_date = st.date_input("To", today)
    force = st.checkbox("Force re-download", value=False)
    if st.button("Download Historical Candles", type="primary"):
        try:
            service = _historical_service(token, layout)
            result = service.load_or_download(
                instrument_key,
                start_date,
                end_date,
                interval_minutes=interval,
                force=force,
            )
            st.success(
                f"Downloaded {len(result.downloaded_dates)} day(s), "
                f"reused {len(result.existing_dates)} day(s), "
                f"stored {result.rows_stored} rows."
            )
            if result.in_progress_dates:
                st.info(
                    "Current session refreshed (IN PROGRESS): "
                    + ", ".join(day.isoformat() for day in result.in_progress_dates)
                )
            if result.no_data_dates:
                st.warning(
                    "No data: "
                    + ", ".join(day.isoformat() for day in result.no_data_dates)
                )
            if result.future_dates:
                st.warning(
                    "Future dates skipped: "
                    + ", ".join(day.isoformat() for day in result.future_dates)
                )
        except MissingAccessToken as exc:
            st.error(str(exc))
        except Exception as exc:
            st.exception(exc)

    st.markdown("---")
    st.markdown("#### Bulk Historical Backtest")
    st.caption(
        "Runs cached dates through: reference levels → signal replay → "
        "paper trades → aggregate performance. This workflow does not "
        "download data; use Research Lab → Historical Data first."
    )

    try:
        cached_reader = RedBarHistoricalService(
            RedBarUpstoxService("cache-only"), layout
        )
        bulk_dates = cached_reader.available_dates(
            instrument_key, interval_minutes=1
        )
    except Exception:
        bulk_dates = []

    if not bulk_dates:
        st.info("No cached historical dates are available.")
    else:
        b1, b2 = st.columns(2)
        with b1:
            bulk_start = st.date_input(
                "Bulk From",
                value=bulk_dates[0],
                min_value=bulk_dates[0],
                max_value=bulk_dates[-1],
                key="bulk_start",
            )
        with b2:
            bulk_end = st.date_input(
                "Bulk To",
                value=bulk_dates[-1],
                min_value=bulk_dates[0],
                max_value=bulk_dates[-1],
                key="bulk_end",
            )

        if st.button("Run Bulk Historical Backtest", type="primary"):
            progress = st.progress(0.0)
            status = st.empty()

            def on_progress(index, total, trading_date):
                pct = index / total if total else 1.0
                progress.progress(min(1.0, pct))
                status.write(
                    f"Processing {trading_date.isoformat()} "
                    f"({index}/{total})"
                )

            try:
                service = BulkHistoricalBacktestService(
                    cached_reader,
                    database,
                    progress_callback=on_progress,
                )
                bulk_result = service.run(
                    instrument_key,
                    bulk_start,
                    bulk_end,
                )
                progress.progress(1.0)
                status.success(
                    f"Completed {bulk_result.trading_days_processed} "
                    f"cached trading day(s)."
                )
                if bulk_result.skipped_days:
                    st.warning(
                        f"Skipped {len(bulk_result.skipped_days)} day(s)."
                    )
                    st.dataframe(
                        [
                            {
                                "trading_date": row.trading_date,
                                "status": row.status,
                                "message": row.message,
                            }
                            for row in bulk_result.skipped_days
                        ],
                        width="stretch",
                        hide_index=True,
                    )
            except Exception as exc:
                st.exception(exc)

        summary = database.paper_trade_range_summary(
            instrument_key,
            bulk_start.isoformat(),
            bulk_end.isoformat(),
        )

        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("Trade models", summary["rows"])
        s2.metric("Win rate", f'{summary["win_rate"]:.1f}%')
        s3.metric("Net points", f'{summary["net_points"]:.2f}')
        s4.metric("Avg points", f'{summary["average_points"]:.2f}')
        pf = summary["profit_factor"]
        s5.metric(
            "Profit factor",
            "∞" if pf is None and summary["winners"] else (
                f"{pf:.2f}" if pf is not None else "—"
            ),
        )

        range_rows = database.paper_trade_range_rows(
            instrument_key,
            bulk_start.isoformat(),
            bulk_end.isoformat(),
        )
        if range_rows:
            st.markdown("#### Backtest Filters")

            signal_types = ["ALL"] + sorted(
                {
                    str(row.get("level_type"))
                    for row in range_rows
                    if row.get("level_type")
                }
            )
            directions = ["ALL"] + sorted(
                {
                    str(row.get("direction"))
                    for row in range_rows
                    if row.get("direction")
                }
            )
            exit_models = ["ALL"] + sorted(
                {
                    str(row.get("exit_model"))
                    for row in range_rows
                    if row.get("exit_model")
                }
            )

            bf1, bf2, bf3, bf4 = st.columns(4)
            with bf1:
                bt_signal_type = st.selectbox(
                    "Signal Type",
                    signal_types,
                    key="bt_filter_signal_type",
                )
            with bf2:
                bt_direction = st.selectbox(
                    "Direction",
                    directions,
                    key="bt_filter_direction",
                )
            with bf3:
                bt_exit_model = st.selectbox(
                    "Exit Model",
                    exit_models,
                    key="bt_filter_exit_model",
                )
            with bf4:
                bt_trade_result = st.selectbox(
                    "Trade Result",
                    ["ALL", "WIN", "LOSS", "BREAKEVEN"],
                    key="bt_filter_trade_result",
                )

            bq1, bq2 = st.columns(2)
            with bq1:
                bt_signal_quality = st.selectbox(
                    "Signal Quality",
                    [
                        "ALL",
                        "STRONG_SUCCESS",
                        "SUCCESS",
                        "MIXED",
                        "WEAK",
                        "BREAKEVEN",
                        "FAILED",
                        "IN_PROGRESS",
                    ],
                    key="bt_filter_signal_quality",
                )
            with bq2:
                bt_min_success_score = st.selectbox(
                    "Minimum Success Score",
                    [0, 3, 6, 8, 9, 10],
                    format_func=lambda value: (
                        "ALL"
                        if value == 0
                        else f"{value}+/10"
                    ),
                    key="bt_filter_min_success_score",
                )

            filtered_rows = _filter_backtest_rows(
                range_rows,
                signal_type=bt_signal_type,
                direction=bt_direction,
                exit_model=bt_exit_model,
                trade_result=bt_trade_result,
                signal_quality=bt_signal_quality,
                min_success_score=bt_min_success_score,
            )
            filtered_summary = _filtered_backtest_summary(
                filtered_rows
            )

            fs1, fs2, fs3, fs4, fs5, fs6 = st.columns(6)
            fs1.metric(
                "Actionable Rows",
                filtered_summary["actionable_rows"],
            )
            fs2.metric(
                "Win Rate",
                f'{filtered_summary["win_rate"]:.1f}%',
            )
            fs3.metric(
                "Avg Points",
                f'{filtered_summary["average_points"]:.2f}',
            )
            fs4.metric(
                "Best",
                (
                    f'{filtered_summary["best_points"]:.2f}'
                    if filtered_summary["best_points"] is not None
                    else "—"
                ),
            )
            fs5.metric(
                "Worst",
                (
                    f'{filtered_summary["worst_points"]:.2f}'
                    if filtered_summary["worst_points"] is not None
                    else "—"
                ),
            )
            fs6.metric(
                "Benchmark Rows",
                filtered_summary["benchmark_rows"],
            )

            st.markdown("#### Filtered Trade Outcomes")
            st.dataframe(
                _trade_display_rows(filtered_rows),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "No paper trades stored for this range yet. "
                "Click Run Bulk Historical Backtest."
            )

    st.markdown("---")
    st.markdown("#### Historical Decision Replay")
    st.caption(
        "Replays the decision at the historical timestamp using only data available "
        "up to that moment. It reports whether live-style execution would TAKE, WAIT, "
        "or BLOCK the setup. Missing intraday option microstructure/Greeks are neutral; "
        "EOD option data is never used to make an intraday decision."
    )
    try:
        replay_reader = RedBarHistoricalService(
            RedBarUpstoxService("cache-only"), layout
        )
        replay_dates = replay_reader.available_dates(
            instrument_key, interval_minutes=1
        )
    except Exception:
        replay_dates = []

    if not replay_dates:
        st.info("Download/cache at least one historical trading day first.")
    else:
        default_replay_date = replay_dates[-1]
        replay_date = st.selectbox(
            "Replay Trading Date",
            replay_dates,
            index=len(replay_dates) - 1,
            format_func=lambda value: value.isoformat(),
            key="historical_decision_replay_date",
        )
        replay_mode = st.radio(
            "Replay Mode",
            ["Full Session", "Fast Validation"],
            horizontal=True,
            key="historical_decision_replay_mode",
        )
        replay_sources = st.multiselect(
            "Replay Sources",
            ["RED_BAR", "DRI_EARLY", "DRI_CONFIRMED"],
            default=["RED_BAR", "DRI_EARLY"],
            key="historical_decision_replay_sources",
            help=(
                "RED_BAR runs the existing reference-level replay. "
                "DRI_EARLY detects completed 1-minute directional breaks immediately. "
                "DRI_CONFIRMED is reserved for progressive 5-minute enrichment."
            ),
        )
        st.caption(
            "Rank-1 opportunity accounting is used for headline performance. "
            "All candidate rows remain available in the detailed replay table."
        )
        st.caption(
            "RB-1.6.0 validates historical option-chain coverage first, then uses the "
            "same Primary / Opportunity / Committee / Portfolio / Exit policy engines "
            "where historical option data is replay-ready."
        )

        # Historical option-chain sync + readiness gate. Historical expired-option
        # candles include OHLC/volume/OI, but not historical bid/ask, IV or Greeks.
        cache_option_sync = HistoricalOptionChainSyncService(
            RedBarUpstoxService(token or "cache-only"), layout, replay_reader, database=database
        )
        coverage = cache_option_sync.validate_day(instrument_key, replay_date)
        st.markdown("##### Option Chain Sync Validation")
        oc1, oc2, oc3, oc4, oc5 = st.columns(5)
        oc1.metric("Contracts", f"{coverage.contracts_stored}/{coverage.contracts_discovered}")
        oc2.metric("Contract Coverage", f"{coverage.contract_coverage_pct:.1f}%")
        oc3.metric("Candle Coverage", f"{coverage.candle_coverage_pct:.1f}%")
        oc4.metric("OI Coverage", f"{coverage.oi_coverage_pct:.1f}%")
        oc5.metric("Replay Ready", "YES" if coverage.replay_ready else "NO")
        ds1, ds2, ds3, ds4 = st.columns(4)
        ds1.metric("Replay Source", coverage.data_source)
        ds2.metric("Live Snapshots", coverage.live_snapshots)
        ds3.metric("Snapshot Coverage", f"{coverage.snapshot_coverage_pct:.1f}%")
        ds4.metric("Bid/Ask", "AVAILABLE" if coverage.bid_ask_available else "UNAVAILABLE")
        if coverage.replay_ready:
            st.success(f"{coverage.fidelity}: {coverage.reason}")
        else:
            st.warning(f"{coverage.fidelity}: {coverage.reason}")
        if coverage.data_source == "LIVE_MARKET_CAPTURE":
            st.caption(
                "Using ITOS ONLINE option-chain snapshots captured on the replay date. "
                f"IV={'available' if coverage.iv_available else 'unavailable'}; "
                f"Greeks={'available' if coverage.greeks_available else 'unavailable'}. "
                "Only snapshots at or before each replay timestamp are used."
            )
        else:
            st.caption("Historical bid/ask depth, IV and Greeks are unavailable from expired-option candles and are never fabricated.")

        st.markdown("##### Replay Diagnostics & Health")
        st.caption(
            "Read-only diagnostics explain exactly where replay readiness succeeds or fails. "
            "Running diagnostics does not change trading rules, portfolio state or replay data."
        )
        if st.button("Run Replay Diagnostics", key="historical_replay_diagnostics"):
            try:
                diagnostic_provider = RedBarUpstoxService(resolve_access_token(token))
                diagnostic_sync = HistoricalOptionChainSyncService(
                    diagnostic_provider, layout, replay_reader, database=database
                )
                diagnostic_service = ReplayDiagnosticsService(
                    diagnostic_sync, replay_reader, database=database
                )
                with st.spinner("Checking underlying data, expiry resolution, contract discovery, storage and replay readiness..."):
                    st.session_state["historical_replay_diagnostics_result"] = diagnostic_service.inspect_day(
                        instrument_key, replay_date, probe_provider=True
                    )
            except MissingAccessToken as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(f"Replay diagnostics failed: {type(exc).__name__}: {exc}")

        diagnostic_result = st.session_state.get("historical_replay_diagnostics_result")
        if diagnostic_result is not None and diagnostic_result.trading_date == replay_date:
            summary = diagnostic_result.as_dict()
            d1, d2, d3, d4, d5 = st.columns(5)
            d1.metric("Underlying Rows", summary["Underlying Rows"])
            d2.metric("Resolved Expiry", summary["Resolved Expiry"])
            d3.metric("Provider Contracts", summary["Provider Contracts Found"])
            d4.metric("Stored Contracts", summary["Stored Manifest Contracts"])
            d5.metric("DB Status", summary["Database"])
            ex1, ex2, ex3, ex4 = st.columns(4)
            ex1.metric("Parsed Expiries", f'{summary["Parsed Expiries"]}/{summary["Expired Expiries Found"]}')
            ex2.metric("Previous Expiry", summary["Previous Expiry"])
            ex3.metric("Next Eligible Expiry", summary["Next Eligible Expiry"])
            ex4.metric("Resolution Rule", summary["Expiry Rule"])
            st.caption(f'Eligible/provider-verified expiries: {summary["Expiry Candidates"]}')
            st.caption(
                f'Expiry source: {summary["Expiry Resolution Source"]}; '
                f'provider probe dates: {summary["Probed Expiry Dates"]}'
            )
            if diagnostic_result.replay_ready:
                st.success(
                    f"Diagnostics: replay path is ready via {diagnostic_result.data_source} "
                    f"({diagnostic_result.replay_fidelity})."
                )
            else:
                failed = [stage for stage in diagnostic_result.stages if stage.status in {"FAIL", "BLOCKED", "LOCKED"}]
                first_failure = failed[0].detail if failed else diagnostic_result.error or "Replay readiness failed."
                st.warning(f"Diagnostics first actionable failure: {first_failure}")
            with st.expander("Replay Pipeline Diagnostics", expanded=not diagnostic_result.replay_ready):
                _st_dataframe_arrow_safe(
                    [stage.as_dict() for stage in diagnostic_result.stages],
                    width="stretch", hide_index=True
                )
                st.caption(
                    f"SQLite journal mode: {diagnostic_result.database_journal_mode}; "
                    f"database size: {diagnostic_result.database_size_mb:.2f} MB; "
                    f"diagnostics elapsed: {diagnostic_result.total_duration_ms:.1f} ms."
                )

        if st.button("Sync / Repair Historical Option Chain", key="historical_option_chain_sync"):
            try:
                sync_provider = RedBarUpstoxService(resolve_access_token(token))
                sync_service = HistoricalOptionChainSyncService(sync_provider, layout, replay_reader, database=database)
                with st.spinner("Discovering expired contracts and syncing one-minute option candles..."):
                    sync_result = sync_service.sync_day(instrument_key, replay_date, force=False)
                st.session_state["historical_option_sync_result"] = sync_result
                st.success(
                    f"Option sync complete: discovered {sync_result.discovered}, downloaded {sync_result.downloaded}, "
                    f"reused {sync_result.reused}, failed {sync_result.failed}."
                )
                if sync_result.errors:
                    st.warning("Some contracts could not be synced. See coverage below / rerun repair.")
                st.rerun()
            except MissingAccessToken as exc:
                st.error(str(exc))
            except Exception as exc:
                st.exception(exc)

        if coverage.contracts:
            with st.expander("Option Chain Coverage Details", expanded=False):
                _st_dataframe_arrow_safe([c.__dict__ for c in coverage.contracts], width="stretch", hide_index=True)
        if not coverage.replay_ready:
            st.info(
                "Replay is disabled for this date until option data is ready. "
                "Use Sync / Repair Historical Option Chain, or select a date with stored ONLINE snapshots / expired-option history."
            )
        if st.button(
            "Run Historical Decision Replay",
            type="primary",
            disabled=(not coverage.replay_ready or not replay_sources),
        ):
            try:
                if "RED_BAR" in replay_sources:
                    replay_service = HistoricalDecisionReplayService(
                        replay_reader,
                        freshness_seconds=180,
                        hard_expiry_seconds=900,
                        minimum_confidence_pct=70.0,
                        stop_loss_pct=15.0,
                        target_pct=25.0,
                        option_chain_sync=cache_option_sync,
                    )
                    st.session_state["historical_decision_replay_result"] = (
                        replay_service.run_day(instrument_key, replay_date)
                    )
                else:
                    st.session_state.pop("historical_decision_replay_result", None)

                dri_events = ()
                if {"DRI_EARLY", "DRI_CONFIRMED"} & set(replay_sources):
                    replay_candles = replay_reader.read_day(
                        instrument_key, replay_date, interval_minutes=1
                    )
                    dri_events = detect_historical_dri_events(replay_candles)
                st.session_state["historical_dri_replay_result"] = {
                    "trading_date": replay_date,
                    "sources": tuple(replay_sources),
                    "events": dri_events,
                }

                if "DRI_EARLY" in replay_sources:
                    dri_policy = HistoricalDecisionReplayService(
                        replay_reader,
                        freshness_seconds=180,
                        hard_expiry_seconds=900,
                        minimum_confidence_pct=70.0,
                        stop_loss_pct=15.0,
                        target_pct=25.0,
                        option_chain_sync=cache_option_sync,
                    )
                    dri_progress = st.progress(
                        0.0,
                        text="Preparing cached DRI replay-day data...",
                    )
                    dri_status = st.empty()

                    def _update_dri_progress(done, total, stage, elapsed):
                        ratio = min(1.0, done / total) if total else 0.0
                        dri_progress.progress(
                            ratio,
                            text=f"DRI opportunity {done} of {total}: {stage}",
                        )
                        dri_status.caption(
                            f"Current stage: {stage} · Elapsed: {elapsed:.1f}s"
                        )

                    dri_replay_service = HistoricalDRIDecisionReplayService(
                        dri_policy
                    )
                    st.session_state["historical_dri_decision_result"] = (
                        dri_replay_service.run_day(
                            instrument_key,
                            replay_date,
                            progress_callback=_update_dri_progress,
                        )
                    )
                    st.session_state["historical_dri_replay_timing"] = (
                        dri_replay_service.last_timing
                    )
                else:
                    st.session_state.pop(
                        "historical_dri_decision_result", None
                    )
            except ValueError as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.exception(exc)

        dri_replay_result = st.session_state.get("historical_dri_replay_result")
        if (
            dri_replay_result is not None
            and dri_replay_result.get("trading_date") == replay_date
        ):
            selected_sources = set(dri_replay_result.get("sources", ()))
            dri_events = tuple(dri_replay_result.get("events", ()))
            if {"DRI_EARLY", "DRI_CONFIRMED"} & selected_sources:
                st.markdown("##### Historical DRI Signal Replay")
                st.caption(
                    "These events are generated candle-by-candle from completed historical "
                    "1-minute candles. They use the historical candle timestamp and never "
                    "read future candles. EARLY events are created immediately; later "
                    "confirmation will enrich the same opportunity in the next wiring stage."
                )
                if dri_events:
                    st.dataframe(
                        [
                            {
                                "Time": event.timestamp,
                                "Event": event.event_id,
                                "Source": event.source,
                                "Stage": event.stage,
                                "Direction": event.direction,
                                "Setup": event.setup_type,
                                "Trigger": event.trigger_level,
                                "Invalidation": event.invalidation_level,
                                "Fresh Until": event.fresh_until,
                            }
                            for event in dri_events
                        ],
                        width="stretch",
                        hide_index=True,
                    )
                    de1, de2, de3 = st.columns(3)
                    de1.metric("DRI Opportunities", len(dri_events))
                    de2.metric(
                        "Bullish",
                        sum(1 for event in dri_events if event.direction == "BULLISH"),
                    )
                    de3.metric(
                        "Bearish",
                        sum(1 for event in dri_events if event.direction == "BEARISH"),
                    )
                else:
                    st.info(
                        "No historical DRI early-break events met the completed-candle "
                        "criteria for this date."
                    )
                if "DRI_CONFIRMED" in selected_sources:
                    st.info(
                        "DRI_CONFIRMED remains reserved for progressive 5-minute "
                        "enrichment of the same EARLY bundle."
                    )

                dri_decisions = st.session_state.get(
                    "historical_dri_decision_result"
                )
                if (
                    dri_decisions is not None
                    and dri_decisions.trading_date == replay_date
                ):
                    st.markdown(
                        "##### DRI Rank-1 Committee & Exit Replay"
                    )
                    st.caption(
                        "Each DRI bundle selects exactly one Rank-1 CE/PE, "
                        "then reuses the existing Opportunity, Committee, "
                        "Portfolio and Exit engines."
                    )
                    replay_timing = st.session_state.get(
                        "historical_dri_replay_timing"
                    ) or {}
                    if replay_timing:
                        st.caption(
                            "Replay performance — "
                            f"total {replay_timing.get('total_seconds', 0):.1f}s · "
                            f"preload {replay_timing.get('preload_seconds', 0):.1f}s · "
                            f"cached contracts "
                            f"{replay_timing.get('cached_contract_series', 0)}"
                        )
                    x1, x2, x3, x4, x5, x6 = st.columns(6)
                    x1.metric("Bundles", dri_decisions.active_signals)
                    x2.metric("TAKE", dri_decisions.approved)
                    x3.metric("WAIT", dri_decisions.waiting)
                    x4.metric("BLOCK", dri_decisions.blocked)
                    x5.metric("Wins", dri_decisions.winners)
                    x6.metric("Losses", dri_decisions.losers)
                    y1, y2, y3, y4 = st.columns(4)
                    y1.metric(
                        "False Positives",
                        dri_decisions.false_positives,
                    )
                    y2.metric(
                        "Correct Skips",
                        dri_decisions.correct_skips,
                    )
                    y3.metric(
                        "Accuracy",
                        f"{dri_decisions.decision_accuracy_pct:.1f}%",
                    )
                    y4.metric(
                        "Net Option Points",
                        f"{dri_decisions.net_points:.2f}",
                    )
                    _st_dataframe_arrow_safe(
                        [
                            {
                                "Time": row.timestamp,
                                "Bundle": row.signal_id,
                                "Setup": row.level_type,
                                "Direction": row.direction,
                                "Option": row.option_side,
                                "Rank-1 Contract": row.candidate_symbol,
                                "Rank": row.candidate_rank,
                                "Candidate Score": row.candidate_score,
                                "Opportunity Health": (
                                    row.opportunity_health
                                ),
                                "Committee": row.execution,
                                "Final %": row.final_confidence_pct,
                                "Portfolio": row.portfolio_status,
                                "Entry": row.option_entry_price,
                                "Exit": row.option_exit_price,
                                "Option Return %": row.option_return_pct,
                                "Exit Reason": row.exit_reason,
                                "Trailing Activated": row.trailing_activated,
                                "Trailing Exit": row.trailing_exit_price,
                                "Trailing Return %": row.trailing_return_pct,
                                "Trailing Exit Reason": row.trailing_exit_reason,
                                "Trailing Protected Points": (
                                    row.trailing_protected_points
                                ),
                                "Reversal State": row.reversal_state,
                                "Reversal Reason": row.reversal_reason,
                                "Reversal Provisional": (
                                    row.reversal_provisional
                                ),
                                "Reversal Confirmed": (
                                    row.reversal_confirmed
                                ),
                                "Reversal EMA10": (
                                    row.reversal_ema10_value
                                ),
                                "Reversal EMA10 Slope": (
                                    row.reversal_ema10_slope
                                ),
                                "Reversal EMA10 OK": (
                                    row.reversal_ema10_ok
                                ),
                                "Reversal EMA30": (
                                    row.reversal_ema30_value
                                ),
                                "Reversal EMA30 Slope": (
                                    row.reversal_ema30_slope
                                ),
                                "Reversal EMA30 OK": (
                                    row.reversal_ema30_ok
                                ),
                                "Two Directional Closes": (
                                    row.reversal_two_directional_closes
                                ),
                                "Reversal Momentum OK": (
                                    row.reversal_momentum_ok
                                ),
                                "Active Invalidation": (
                                    row.reversal_active_invalidation
                                ),
                                "Invalidation Broken": (
                                    row.reversal_invalidation_broken
                                ),
                                "Reset/Rebreak Reason": (
                                    row.reset_rebreak_reason
                                ),
                                "Reset Seen": row.reset_seen,
                                "Re-expansion Detected": (
                                    row.reexpansion_detected
                                ),
                                "Reset Candle Time": (
                                    row.reset_candle_time
                                ),
                                "EMA10 Touch Detected": (
                                    row.ema10_touch_detected
                                ),
                                "Re-expansion Break Level": (
                                    row.reexpansion_break_level
                                ),
                                "Strong Expansion Candle": (
                                    row.strong_expansion_candle
                                ),
                                "Reset Classification": row.reset_classification,
                                "Reset Window Bars": row.reset_window_bars,
                                "Counter Candle Seen": (
                                    row.reset_counter_candle_seen
                                ),
                                "EMA10 Near Touch": (
                                    row.reset_near_touch_detected
                                ),
                                "Shallow Reset Detected": (
                                    row.shallow_reset_detected
                                ),
                                "Reset Quality Passed": row.reset_quality_passed,
                                "Reset Quality Count": (
                                    row.reset_quality_criteria_count
                                ),
                                "Reset Quality Criteria": (
                                    row.reset_quality_criteria
                                ),
                                "Market Action Count": (
                                    row.reset_market_action_count
                                ),
                                "Market Action Passed": (
                                    row.reset_market_action_passed
                                ),
                                "Market Action Criteria": (
                                    row.reset_market_action_criteria
                                ),
                                "Moderate Market Action": (
                                    row.reset_moderate_market_action_passed
                                ),
                                "Market Action Tier": row.reset_market_action_tier,
                                "Reset Body Ratio %": (
                                    row.reset_body_ratio_pct
                                ),
                                "Reset Break Distance %": (
                                    row.reset_move_beyond_break_pct
                                ),
                                "Reset Relative Volume": (
                                    row.reset_relative_volume
                                ),
                                "Quality Candidate Score Input": (
                                    row.quality_candidate_score_input
                                ),
                                "Quality Opportunity Health Input": (
                                    row.quality_opportunity_health_input
                                ),
                                "Adaptive Initial Stop %": (
                                    row.adaptive_initial_stop_pct
                                ),
                                "Adaptive Trailing Exit": (
                                    row.adaptive_trailing_exit_price
                                ),
                                "Adaptive Trailing Return %": (
                                    row.adaptive_trailing_return_pct
                                ),
                                "Adaptive Trailing Exit Reason": (
                                    row.adaptive_trailing_exit_reason
                                ),
                                "Adaptive Protected Points": (
                                    row.adaptive_trailing_protected_points
                                ),
                                "Outcome": row.outcome_result,
                                "Verdict": row.verdict,
                                "Fidelity": row.data_fidelity,
                            }
                            for row in dri_decisions.rows
                        ],
                        width="stretch",
                        hide_index=True,
                    )

        with st.expander(
            "Historical DRI Multi-Day Validation",
            expanded=False,
        ):
            st.caption(
                "Freeze the current DRI rules and validate the full "
                "Opportunity, Committee, Portfolio and Exit path over "
                "3–5 completed trading dates. Each date uses a fresh "
                "service instance so state cannot leak between sessions."
            )
            batch_date_text = st.text_area(
                "Trading dates (comma or newline separated)",
                key="historical_dri_batch_dates",
                placeholder="2026-08-12, 2026-08-13, 2026-08-14",
                height=80,
            )
            if st.button(
                "Run 3–5 Day DRI Validation",
                key="historical_dri_batch_run",
            ):
                raw_tokens = [
                    token.strip()
                    for token in batch_date_text.replace("\n", ",").split(",")
                    if token.strip()
                ]
                try:
                    batch_dates = tuple(
                        pd.Timestamp(token).date()
                        for token in raw_tokens
                    )
                    batch_dates = tuple(dict.fromkeys(batch_dates))
                    if not 3 <= len(batch_dates) <= 5:
                        raise ValueError(
                            "Enter between 3 and 5 unique trading dates."
                        )

                    batch_progress = st.progress(
                        0.0,
                        text="Preparing multi-day DRI validation...",
                    )
                    batch_status = st.empty()

                    def _run_batch_day(batch_date):
                        import time

                        day_policy = HistoricalDecisionReplayService(
                            replay_reader,
                            freshness_seconds=180,
                            hard_expiry_seconds=900,
                            minimum_confidence_pct=70.0,
                            stop_loss_pct=15.0,
                            target_pct=25.0,
                            option_chain_sync=cache_option_sync,
                        )
                        day_service = HistoricalDRIDecisionReplayService(
                            day_policy
                        )
                        started = time.perf_counter()
                        result = day_service.run_day(
                            instrument_key,
                            batch_date,
                        )
                        return result, time.perf_counter() - started

                    def _batch_progress(done, total, day, status):
                        ratio = min(1.0, done / total) if total else 0.0
                        batch_progress.progress(
                            ratio,
                            text=(
                                f"Multi-day validation {done}/{total}: "
                                f"{day} · {status}"
                            ),
                        )
                        batch_status.caption(
                            f"Current date: {day} · Status: {status}"
                        )

                    st.session_state[
                        "historical_dri_batch_validation"
                    ] = validate_historical_dri_dates(
                        batch_dates,
                        run_day=_run_batch_day,
                        progress_callback=_batch_progress,
                    )
                except Exception as exc:
                    st.exception(exc)

            batch_result = st.session_state.get(
                "historical_dri_batch_validation"
            )
            if batch_result is not None:
                b1, b2, b3, b4, b5, b6 = st.columns(6)
                b1.metric("Successful Days", batch_result.successful_days)
                b2.metric("Failed Days", batch_result.failed_days)
                b3.metric("TAKE", batch_result.take)
                b4.metric("Wins", batch_result.wins)
                b5.metric("Losses", batch_result.losses)
                b6.metric(
                    "Net Option Points",
                    f"{batch_result.net_points:.2f}",
                )

                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Bundles", batch_result.bundles)
                c2.metric("WAIT", batch_result.wait)
                c3.metric("BLOCK", batch_result.block)
                c4.metric(
                    "False Positives",
                    batch_result.false_positives,
                )
                c5.metric(
                    "Mean Daily Accuracy",
                    f"{batch_result.mean_daily_accuracy_pct:.1f}%",
                )

                batch_rows = batch_result.rows()
                _st_dataframe_arrow_safe(
                    batch_rows,
                    width="stretch",
                    hide_index=True,
                )
                st.download_button(
                    "Download Multi-Day Summary as CSV",
                    data=pd.DataFrame(batch_rows).to_csv(index=False),
                    file_name="historical_dri_multiday_validation.csv",
                    mime="text/csv",
                    key="historical_dri_batch_download",
                )

        replay_result = st.session_state.get("historical_decision_replay_result")
        if replay_result is not None and replay_result.trading_date == replay_date:
            st.markdown("##### Live-Style Decision Summary")
            opportunity_summary = consolidate_replay_rows(replay_result.rows)
            st.markdown("##### Rank-1 Opportunity Summary")
            os1, os2, os3, os4, os5, os6 = st.columns(6)
            os1.metric("Opportunities", opportunity_summary.opportunities)
            os2.metric("Candidates Evaluated", opportunity_summary.candidates_evaluated)
            os3.metric("Trades Selected", opportunity_summary.trades_selected)
            os4.metric("Wins", opportunity_summary.winners)
            os5.metric("Losses", opportunity_summary.losers)
            os6.metric(
                "Opportunity Accuracy",
                f"{opportunity_summary.decision_accuracy_pct:.1f}%",
            )
            st.caption(
                "One Rank-1 row represents each signal opportunity. Lower-ranked "
                "contracts remain in the detailed table for diagnostics and are not "
                "counted as separate trades in this summary."
            )
            r1, r2, r3, r4, r5, r6 = st.columns(6)
            r1.metric("Signals", replay_result.active_signals)
            r2.metric("Would Take", replay_result.approved)
            r3.metric("Would Wait", replay_result.waiting)
            r4.metric("Would Block", replay_result.blocked)
            r5.metric("Wins (Taken)", replay_result.winners)
            r6.metric("Decision Accuracy", f"{replay_result.decision_accuracy_pct:.1f}%")
            l1, l2, l3, l4 = st.columns(4)
            l1.metric("Missed Opportunities", replay_result.missed_opportunities)
            l2.metric("False Positives", replay_result.false_positives)
            l3.metric("Correct Skips", replay_result.correct_skips)
            l4.metric("Net Underlying Points", f"{replay_result.net_points:.2f}")
            st.info(
                "Replay fidelity: " + replay_result.data_fidelity + ". "
                + replay_result.replay_fidelity_reason + " "
                "Future option candles are used only by the normal Exit Engine after entry; "
                "they are never used to make the entry decision."
            )
            pf1, pf2, pf3, pf4 = st.columns(4)
            pf1.metric("Option Contracts", f"{replay_result.option_contract_coverage_pct:.1f}%")
            pf2.metric("Option Candles", f"{replay_result.option_candle_coverage_pct:.1f}%")
            pf3.metric("Portfolio Admitted", replay_result.portfolio_admitted)
            pf4.metric("Portfolio Watchlist", replay_result.portfolio_watchlisted)
            replay_rows = [row.as_dict() for row in replay_result.rows]
            if replay_rows:
                display_rows = []
                for row in replay_rows:
                    display_rows.append({
                        "Time": row["timestamp"],
                        "Signal": row["signal_id"],
                        "Level": row["level_type"],
                        "Direction": row["direction"],
                        "Option": row["option_side"],
                        "Candidate": row.get("candidate_symbol"),
                        "Rank": row.get("candidate_rank"),
                        "Candidate Score": row.get("candidate_score"),
                        "Opportunity Health": row.get("opportunity_health"),
                        "Lifecycle": row["lifecycle_state"],
                        "Primary %": row["primary_confidence_pct"],
                        "Shadow": row["shadow_decision"],
                        "Shadow %": row["shadow_confidence_pct"],
                        "Agreement": row["agreement"],
                        "Final %": row["final_confidence_pct"],
                        "Expectancy %": row["expectancy_pct"],
                        "Decision": row["decision"],
                        "Execution": row["execution"],
                        "Portfolio": row.get("portfolio_status"),
                        "Portfolio Reason": row.get("portfolio_reason"),
                        "Blocker / Reason": row["blocker"],
                        "Exit Reason": row.get("exit_reason"),
                        "Option Return %": row.get("option_return_pct"),
                        "Outcome": row["outcome_result"],
                        "Outcome Basis": row.get("outcome_basis"),
                        "Outcome Points": row["outcome_points"],
                        "Verdict": row["verdict"],
                        "Learning Attribution": row["learning_attribution"],
                    })
                _st_dataframe_arrow_safe(display_rows, width="stretch", hide_index=True)

                st.markdown("##### Decision Learning Summary")
                st.caption(
                    "Learning is advisory-only. Historical outcomes classify decisions and suggest what to review; "
                    "RB-1.4.1 keeps Shadow informational-only and does not automatically modify live thresholds or weights."
                )
                for recommendation in replay_result.learning_recommendations:
                    st.info(recommendation)

                st.markdown("##### Replay Accuracy & Decision Calibration")
                st.caption(
                    "Post-decision research only. Missing option minutes, confidence calibration and threshold scenarios are measured "
                    "after historical decisions are frozen. Recommendations never change live parameters automatically."
                )
                accuracy_service = ReplayAccuracyService(cache_option_sync, replay_reader, minimum_calibration_samples=30)
                accuracy = accuracy_service.build(instrument_key, replay_result)
                aq1, aq2, aq3, aq4, aq5 = st.columns(5)
                aq1.metric("Temporal Coverage", f"{accuracy.temporal_coverage_pct:.1f}%")
                aq2.metric("Missing Minutes", accuracy.missing_minutes)
                aq3.metric("Longest Gap", f"{accuracy.longest_gap_minutes} min")
                aq4.metric("Resolved Candidates", accuracy.resolved_candidates)
                aq5.metric("Calibration", accuracy.recommendation_status)
                if accuracy.missing_ranges:
                    with st.expander("Option Capture Gaps", expanded=False):
                        st.caption("Missing minute ranges: " + ", ".join(accuracy.missing_ranges[:40]))
                        if len(accuracy.missing_ranges) > 40:
                            st.caption(f"+ {len(accuracy.missing_ranges)-40} additional gap range(s)")
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Confidence Calibration**")
                    _st_dataframe_arrow_safe([b.as_dict() for b in accuracy.confidence_buckets], width="stretch", hide_index=True)
                with c2:
                    st.markdown("**Advisory Confidence Threshold Scenarios**")
                    _st_dataframe_arrow_safe([x.as_dict() for x in accuracy.threshold_scenarios], width="stretch", hide_index=True)
                for rec in accuracy.recommendations:
                    st.info(rec)

                st.markdown("##### Why Trade Was Taken / Blocked")
                selected_signal = st.selectbox(
                    "Inspect Replay Signal",
                    [row["signal_id"] for row in replay_rows],
                    key="historical_decision_replay_signal",
                )
                selected = next(
                    row for row in replay_rows if row["signal_id"] == selected_signal
                )
                d1, d2, d3, d4 = st.columns(4)
                d1.metric("Primary", f'{selected["primary_confidence_pct"]:.2f}%')
                d2.metric("Final", f'{selected["final_confidence_pct"]:.2f}%')
                d3.metric("Expectancy", f'{selected["expectancy_pct"]:.3f}%')
                d4.metric("Execution", selected["execution"])
                st.write(
                    {
                        "Lifecycle": selected["lifecycle_state"],
                        "Lifecycle Action": selected["lifecycle_action"],
                        "Market Session": selected["market_session"],
                        "VWAP aligned": selected["vwap_ok"],
                        "EMA aligned": selected["ema_ok"],
                        "Momentum aligned": selected["momentum_ok"],
                        "Volume Score": selected["volume_score"],
                        "OI Score": selected["oi_score"],
                        "Shadow Decision": selected["shadow_decision"],
                        "Agreement": selected["agreement"],
                        "Shadow Adjustment": selected["shadow_adjustment_pct"],
                        "Blocker / Reason": selected["blocker"],
                        "Historical Outcome": selected["outcome_result"],
                        "Outcome Basis": selected.get("outcome_basis"),
                        "Historical Outcome Points": selected["outcome_points"],
                        "Decision Verdict": selected["verdict"],
                        "Learning Attribution": selected["learning_attribution"],
                        "Learning Recommendation": selected["learning_recommendation"],
                        "Data Fidelity": selected["data_fidelity"],
                    }
                )
            else:
                st.warning("No confirmed historical Red Bar signals were found for this day.")
