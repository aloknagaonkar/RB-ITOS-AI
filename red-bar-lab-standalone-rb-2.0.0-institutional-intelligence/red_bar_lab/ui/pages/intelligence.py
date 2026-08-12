from red_bar_lab.ui._shared import *


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Intelligence")
    st.caption(
        "Automatic pipeline health, Feature Store readiness, Shadow "
        "Validation analytics and maintenance tools. Shadow intelligence "
        "remains observation-only."
    )

    st.markdown("### Institutional Option Flow — Sprint 1")
    st.markdown(
        _decision_badge_html(
            "INSTITUTIONAL FLOW · OBSERVATION ONLY · EXECUTION IMPACT = NONE",
            "shadow",
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Compares the two latest ONLINE option-chain snapshots to classify OI behaviour "
        "and infer call/put buying or writing. This module is research-only and cannot "
        "change Primary, Committee, Portfolio or Queue decisions."
    )
    try:
        flow = InstitutionalFlowService(database).latest(
            instrument_key, date.today().isoformat()
        )
        if flow.status != "READY":
            st.info(f"Institutional Flow: {flow.reason}")
        else:
            fi1, fi2, fi3, fi4 = st.columns(4)
            fi1.metric("Bullish Institutional Flow", f"{flow.bullish_flow_pct:.1f}%")
            fi2.metric("Bearish Institutional Flow", f"{flow.bearish_flow_pct:.1f}%")
            fi3.metric("Dominant Activity", flow.dominant_activity)
            fi4.metric("Expiry", flow.option_expiry or "—")
            fi5, fi6, fi7, fi8 = st.columns(4)
            fi5.metric("Strongest Bullish Strike", flow.strongest_bullish or "—")
            fi6.metric("Strongest Bearish Strike", flow.strongest_bearish or "—")
            fi7.metric("Flow Samples", len(flow.rows))
            fi8.metric("Execution Impact", "NONE")
            st.caption(
                f"Current snapshot: {flow.snapshot_timestamp or '—'} · "
                f"Previous snapshot: {flow.previous_snapshot_timestamp or '—'} · "
                f"{flow.reason}"
            )
            flow_rows = [row.as_dict() for row in flow.rows]
            flow_rows.sort(
                key=lambda row: float(row.get("Confidence %") or 0.0),
                reverse=True,
            )
            st.markdown("#### Strongest Institutional Activities")
            st.dataframe(
                _arrow_safe_rows(flow_rows[:40]),
                width="stretch",
                hide_index=True,
            )
            with st.expander("Institutional Flow Classification Rules", expanded=False):
                st.markdown(
                    "- Premium ↑ + OI ↑ → LONG_BUILDUP\n"
                    "- Premium ↓ + OI ↑ → SHORT_BUILDUP\n"
                    "- Premium ↑ + OI ↓ → SHORT_COVERING\n"
                    "- Premium ↓ + OI ↓ → LONG_UNWINDING\n\n"
                    "For CE, LONG_BUILDUP maps to CALL_BUYING and SHORT_BUILDUP to CALL_WRITING. "
                    "For PE, LONG_BUILDUP maps to PUT_BUYING and SHORT_BUILDUP to PUT_WRITING."
                )
    except Exception as exc:
        st.warning(f"Institutional option-flow analytics unavailable: {exc}")

    st.markdown("### Shadow Validation Dashboard")
    st.markdown(
        _decision_badge_html(
            "SHADOW ANALYTICS · EXECUTION IMPACT = NONE",
            "shadow",
        ),
        unsafe_allow_html=True,
    )
    try:
        validation = ShadowValidationService(database).evaluate()
        shadow_summary = validation["summary"]

        sv1, sv2, sv3, sv4 = st.columns(4)
        sv1.metric(
            "Closed Paper Trades",
            shadow_summary.closed_trades,
        )
        sv2.metric(
            "Current Engine Win Rate",
            f"{shadow_summary.current_win_rate:.1f}%",
        )
        sv3.metric(
            "Shadow Accuracy",
            (
                f"{shadow_summary.shadow_accuracy:.1f}%"
                if shadow_summary.shadow_accuracy is not None
                else "INSUFFICIENT DATA"
            ),
        )
        sv4.metric(
            "Resolved Shadow Samples",
            shadow_summary.shadow_resolved,
        )

        sv5, sv6, sv7, sv8 = st.columns(4)
        sv5.metric(
            "Agreement Rate",
            (
                f"{shadow_summary.agreement_rate:.1f}%"
                if shadow_summary.agreement_rate is not None
                else "—"
            ),
        )
        sv6.metric(
            "Agreement Win Rate",
            (
                f"{shadow_summary.agreement_win_rate:.1f}%"
                if shadow_summary.agreement_win_rate is not None
                else "—"
            ),
        )
        sv7.metric(
            "Shadow Better",
            shadow_summary.shadow_better,
        )
        sv8.metric(
            "Current Better",
            shadow_summary.current_better,
        )

        st.caption(
            "Accuracy is conservative: an opposite-direction shadow call "
            "is marked UNRESOLVED unless a real counterfactual option path "
            "exists. The dashboard does not assume that the opposite trade "
            "would have won."
        )

        st.markdown("#### Recommendation Stability")
        stability = validation["stability"]
        rs1, rs2, rs3, rs4 = st.columns(4)
        rs1.metric(
            "Current Shadow Decision",
            stability.get("decision") or "NO DATA",
        )
        rs2.metric(
            "Stable For",
            f"{float(stability.get('minutes') or 0):.1f} min",
        )
        rs3.metric(
            "Consecutive Samples",
            int(stability.get("samples") or 0),
        )
        rs4.metric(
            "Shadow Confidence",
            f"{shadow_summary.latest_shadow_confidence:.1f}%",
        )
        st.caption(
            f"Stability start: {stability.get('started_at') or '—'} · "
            f"Last seen: {stability.get('last_seen_at') or '—'}"
        )

        st.markdown("#### Intelligence Scoreboard")
        module_scoreboard = validation["module_scoreboard"]
        if module_scoreboard:
            scoreboard_display = []
            for row in module_scoreboard:
                accuracy = row.get("Accuracy %")
                if accuracy is None:
                    quality = "LEARNING"
                elif float(accuracy) >= 80:
                    quality = "EXCELLENT"
                elif float(accuracy) >= 70:
                    quality = "GOOD"
                elif float(accuracy) >= 60:
                    quality = "WATCH"
                else:
                    quality = "WEAK"
                scoreboard_display.append(
                    {
                        **row,
                        "Quality": quality,
                    }
                )
            st.dataframe(
                _arrow_safe_rows(scoreboard_display),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "No module accuracy is available yet. Closed paper trades "
                "with matching Shadow evaluations are required."
            )

        st.markdown("#### Promotion Candidates")
        promotion_rows = [
            row for row in module_scoreboard
            if row.get("Promotion") == "CANDIDATE"
        ]
        if promotion_rows:
            st.success(
                "The following modules meet the current evidence threshold "
                "for review. They are NOT automatically promoted."
            )
            st.dataframe(
                _arrow_safe_rows(promotion_rows),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "No Shadow module is ready for promotion review yet. "
                "Current review threshold: at least 30 resolved samples, "
                "accuracy >= 70%, and resolved coverage >= 50%."
            )

        st.markdown("#### Agreement Analytics")
        comparison_rows = validation["trade_comparison"]
        if comparison_rows:
            st.dataframe(
                _arrow_safe_rows(comparison_rows[-200:]),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                f"Unresolved comparisons: "
                f"{shadow_summary.unresolved_disagreements}. "
                "Opposite-direction calls stay unresolved until a "
                "counterfactual replay engine exists."
            )
        else:
            st.info(
                "No closed paper trades have both execution outcome and "
                "Shadow evaluation data yet."
            )
    except Exception as exc:
        st.warning(f"Shadow validation analytics unavailable: {exc}")

    try:
        context_reader = RedBarHistoricalService(
            RedBarUpstoxService("cache-only"),
            layout,
        )
        context_dates = context_reader.available_dates(
            instrument_key,
            interval_minutes=1,
        )
    except Exception:
        context_reader = None
        context_dates = ()

    if context_dates:
        default_to = context_dates[-1]
        default_from = max(
            context_dates[0],
            default_to - timedelta(days=30),
        )
    else:
        default_to = date.today()
        default_from = default_to - timedelta(days=30)

    st.markdown("### Automatic Intelligence Pipeline")
    try:
        today_key = date.today().isoformat()
        pipeline_status = database.read_pipeline_run_status(
            instrument_key,
            today_key,
        )
        signal_pipeline_rows = (
            database.read_signal_pipeline_status_range(
                instrument_key,
                today_key,
                today_key,
            )
        )
        eod_validation = database.read_eod_pipeline_validation(
            instrument_key,
            today_key,
        )

        confirmed_count = len(signal_pipeline_rows)
        core_ready = sum(
            int(bool(row.get("core_eligible")))
            for row in signal_pipeline_rows
        )
        hybrid_ready = sum(
            int(bool(row.get("hybrid_eligible")))
            for row in signal_pipeline_rows
        )
        missing_options = sum(
            1
            for row in signal_pipeline_rows
            if not bool(row.get("options_context_ready"))
        )

        ap1, ap2, ap3, ap4 = st.columns(4)
        ap1.metric(
            "Pipeline",
            (
                pipeline_status.get("status")
                if pipeline_status
                else "WAITING"
            ),
        )
        ap2.metric(
            "CORE Eligible",
            f"{core_ready}/{confirmed_count}",
        )
        ap3.metric(
            "HYBRID Eligible",
            f"{hybrid_ready}/{confirmed_count}",
        )
        ap4.metric(
            "Missing Options",
            missing_options,
        )

        st.caption(
            "CORE = Red Bar + Price/Session + Volume/Structure. "
            "HYBRID = CORE + entry-aligned Options Context."
        )
        if pipeline_status:
            st.caption(
                f"Last pipeline update: "
                f"{pipeline_status.get('updated_at')} · "
                f"{pipeline_status.get('message') or ''}"
            )

        if signal_pipeline_rows:
            st.dataframe(
                _arrow_safe_rows(signal_pipeline_rows),
                width="stretch",
                hide_index=True,
            )

        if eod_validation:
            st.info(
                f"EOD validation: {eod_validation.get('status')} · "
                f"Core {float(eod_validation.get('core_completeness_pct') or 0):.1f}% · "
                f"Hybrid {float(eod_validation.get('hybrid_completeness_pct') or 0):.1f}%"
            )
    except Exception as exc:
        st.warning(f"Automatic pipeline health unavailable: {exc}")

    st.markdown("---")
    st.markdown("### Maintenance / Backfill")
    st.caption(
        "The controls below are for historical rebuilds, repairs, testing "
        "and backfill. They are not required for normal live operation."
    )

    st.markdown("#### Historical Options Backfill")
    st.caption(
        "Backfill Upstox Plus historical EOD OI and Change-in-OI. "
        "This data is research/EOD context only and is never marked as "
        "entry-aligned HYBRID features."
    )

    hb1, hb2 = st.columns(2)
    with hb1:
        historical_options_from = st.date_input(
            "Historical Options From",
            value=max(
                date.today() - timedelta(days=30),
                date.today() - timedelta(days=186),
            ),
            key="historical_options_backfill_from",
        )
    with hb2:
        historical_options_to = st.date_input(
            "Historical Options To",
            value=date.today() - timedelta(days=1),
            key="historical_options_backfill_to",
        )

    hb3, hb4 = st.columns(2)
    with hb3:
        historical_change_interval = st.number_input(
            "Change-in-OI interval (days)",
            min_value=1,
            max_value=30,
            value=1,
            step=1,
            key="historical_change_oi_interval",
        )
    with hb4:
        historical_overwrite = st.checkbox(
            "Overwrite existing backfill rows",
            value=False,
            key="historical_options_overwrite",
        )

    if st.button(
        "Backfill Historical Options Data",
        key="historical_options_backfill_button",
    ):
        try:
            access_token = resolve_access_token(token)
            service = RedBarHistoricalOptionsBackfillService(
                RedBarUpstoxService(access_token),
                database,
                settings,
            )
            report = service.backfill_range(
                instrument_key=instrument_key,
                date_from=historical_options_from,
                date_to=historical_options_to,
                change_interval_days=int(
                    historical_change_interval
                ),
                overwrite=historical_overwrite,
            )
            st.success(
                f"Historical options backfill complete: "
                f"{report.completed_days} day(s) written, "
                f"{report.skipped_days} skipped, "
                f"{report.failed_days} failed."
            )
            st.caption(
                f"Requested {report.requested_days} calendar days · "
                f"attempted {report.attempted_days} trading-day candidates."
            )
            if report.errors:
                with st.expander(
                    f"Backfill warnings/errors ({len(report.errors)})"
                ):
                    for error in report.errors[:100]:
                        st.text(error)
        except MissingAccessToken as exc:
            st.error(str(exc))
        except Exception as exc:
            st.exception(exc)

    historical_option_rows = (
        database.read_historical_option_backfill_range(
            instrument_key,
            default_from.isoformat(),
            default_to.isoformat(),
        )
    )
    if historical_option_rows:
        st.markdown("##### Historical Options EOD Context")
        st.dataframe(
            _arrow_safe_rows(historical_option_rows[-100:]),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption(
            "No historical Upstox Plus OI backfill is stored for "
            "the selected context range."
        )

    st.markdown("#### Market Context Engine")
    mc1, mc2 = st.columns(2)
    with mc1:
        context_from = st.date_input(
            "Market Context From",
            value=default_from,
            key="intel_market_context_from",
        )
    with mc2:
        context_to = st.date_input(
            "Market Context To",
            value=default_to,
            key="intel_market_context_to",
        )

    if st.button(
        "Build Market Context",
        key="intel_build_market_context",
    ):
        if context_reader is None:
            st.error("Historical cache is not available.")
        else:
            try:
                context_service = RedBarMarketContextService(
                    context_reader,
                    database,
                    settings,
                )
                context_rows, report = context_service.build_for_range(
                    instrument_key,
                    context_from,
                    context_to,
                )
                st.success(
                    f"Built {report.snapshots_built} market-context "
                    f"snapshots from {report.signals_found} signals; "
                    f"skipped {report.skipped}."
                )
                st.caption(f"Saved to: {report.output_path}")
                if context_rows:
                    st.dataframe(
                        _arrow_safe_rows(context_rows[:50]),
                        width="stretch",
                        hide_index=True,
                    )
            except Exception as exc:
                st.exception(exc)

    st.markdown("#### Volume & Structure Context")
    vs1, vs2 = st.columns(2)
    with vs1:
        volume_from = st.date_input(
            "Volume/Structure From",
            value=default_from,
            key="intel_volume_context_from",
        )
    with vs2:
        volume_to = st.date_input(
            "Volume/Structure To",
            value=default_to,
            key="intel_volume_context_to",
        )

    if st.button(
        "Build Volume & Structure Context",
        key="intel_build_volume_structure",
    ):
        if context_reader is None:
            st.error("Historical cache is not available.")
        else:
            try:
                service = RedBarVolumeStructureService(
                    context_reader,
                    database,
                    settings,
                )
                rows, report = service.build_for_range(
                    instrument_key,
                    volume_from,
                    volume_to,
                )
                st.success(
                    f"Built {report.snapshots_built} volume/structure "
                    f"snapshots from {report.signals_found} signals; "
                    f"skipped {report.skipped}."
                )
                st.caption(f"Saved to: {report.output_path}")
                if rows:
                    st.dataframe(
                        _arrow_safe_rows(rows[:50]),
                        width="stretch",
                        hide_index=True,
                    )
            except Exception as exc:
                st.exception(exc)

    st.markdown("#### Dual Market Data Collector")
    st.caption(
        "Online: one-minute option-chain history during market hours. "
        "Offline: final/EOD snapshot collection after market hours. "
        "The existing signal-triggered capture remains enabled as a fallback."
    )

    collector_status = database.read_collector_status()
    dc1, dc2, dc3, dc4 = st.columns(4)
    dc1.metric(
        "Clock Mode",
        market_clock_mode(),
    )
    dc2.metric(
        "Collector Status",
        (
            str(collector_status.get("status"))
            if collector_status
            else "NOT STARTED"
        ),
    )
    dc3.metric(
        "Last Mode",
        (
            str(collector_status.get("collector_mode"))
            if collector_status
            else "—"
        ),
    )
    dc4.metric(
        "Last Snapshot",
        (
            str(collector_status.get("last_snapshot_id"))
            if collector_status
            and collector_status.get("last_snapshot_id") is not None
            else "—"
        ),
    )
    if collector_status:
        st.caption(
            f"Last update: {collector_status.get('updated_at')} · "
            f"{collector_status.get('message') or ''}"
        )

    st.code(
        '$env:UPSTOX_ACCESS_TOKEN="your-token"\n'
        '.\\run_market_collector.ps1',
        language="powershell",
    )
    st.caption(
        "Run the collector in a second PowerShell window. Auto mode uses "
        "online collection during market hours and offline/EOD collection "
        "outside market hours. Default interval is 60 seconds."
    )

    dcb1, dcb2 = st.columns(2)
    with dcb1:
        if st.button(
            "Run Online Collector Tick",
            key="intel_run_online_collector_tick",
        ):
            try:
                access_token = resolve_access_token(token)
                collector = RedBarDualMarketCollector(
                    RedBarUpstoxService(access_token),
                    database,
                    settings,
                )
                tick = collector.online_tick(
                    instrument_key=instrument_key,
                    expiry=None,
                    link_window_seconds=120,
                )
                st.success(
                    f"{tick.status}: {tick.message} "
                    f"Snapshot={tick.snapshot_id or '—'}"
                )
            except MissingAccessToken as exc:
                st.error(str(exc))
            except Exception as exc:
                st.exception(exc)

    with dcb2:
        if st.button(
            "Run Offline / EOD Collector Tick",
            key="intel_run_offline_collector_tick",
        ):
            try:
                access_token = resolve_access_token(token)
                collector = RedBarDualMarketCollector(
                    RedBarUpstoxService(access_token),
                    database,
                    settings,
                )
                tick = collector.offline_eod_tick(
                    instrument_key=instrument_key,
                    trading_date=date.today().isoformat(),
                )
                st.success(
                    f"{tick.status}: {tick.message} "
                    f"Snapshot={tick.snapshot_id or '—'}"
                )
            except MissingAccessToken as exc:
                st.error(str(exc))
            except Exception as exc:
                st.exception(exc)

    history_rows = database.read_option_chain_history(
        instrument_key,
        default_from.isoformat(),
        default_to.isoformat(),
        limit=100,
    )
    if history_rows:
        st.markdown("##### Recent Option-Chain History")
        st.dataframe(
            _arrow_safe_rows(history_rows),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption(
            "No continuous option-chain history has been collected yet."
        )

    st.markdown("#### Options Context")
    st.caption(
        "RB-0.7.4.1 keeps signal context plus continuous online/offline option-chain history. "
        "eligible for AI features only when captured within the configured "
        "entry-alignment window."
    )

    opt1, opt2 = st.columns(2)
    with opt1:
        option_expiry = st.text_input(
            "Expiry (optional)",
            value="",
            help=(
                "Leave blank to use the nearest active Upstox expiry. "
                "Format: YYYY-MM-DD."
            ),
            key="intel_option_expiry",
        )
    with opt2:
        option_alignment_seconds = st.number_input(
            "Entry alignment window (seconds)",
            min_value=30,
            max_value=600,
            value=120,
            step=30,
            key="intel_option_alignment_seconds",
        )

    if st.button(
        "Capture Options Context for Today's Confirmed Signals",
        key="intel_capture_options_context",
    ):
        try:
            access_token = resolve_access_token(token)
            option_provider = RedBarUpstoxService(access_token)
            option_service = RedBarOptionsContextService(
                option_provider,
                database,
                settings,
            )
            option_report = (
                option_service.capture_current_confirmed_signals(
                    instrument_key=instrument_key,
                    trading_date=date.today().isoformat(),
                    expiry=(option_expiry.strip() or None),
                    alignment_tolerance_seconds=int(
                        option_alignment_seconds
                    ),
                )
            )
            st.success(
                f"Captured {option_report.captured} option-context "
                f"snapshot(s); {option_report.entry_aligned} are "
                f"entry-aligned and AI-eligible; "
                f"{option_report.skipped} skipped."
            )
            if option_report.expiry:
                st.caption(
                    f"Expiry: {option_report.expiry} · "
                    f"Summary: {option_report.summary_path} · "
                    f"Chain: {option_report.chain_path}"
                )
        except MissingAccessToken as exc:
            st.error(str(exc))
        except Exception as exc:
            st.exception(exc)

    option_upload = st.file_uploader(
        "Import Options Context CSV",
        type=["csv"],
        key="intel_option_context_import",
        help=(
            "Use this for externally captured/historical option-context "
            "snapshots. Imported rows still carry the entry_aligned flag."
        ),
    )
    if option_upload is not None and st.button(
        "Import Options Context",
        key="intel_import_options_context",
    ):
        try:
            import_frame = pd.read_csv(option_upload)
            option_service = RedBarOptionsContextService(
                RedBarUpstoxService("import-only"),
                database,
                settings,
            )
            imported = option_service.import_context_frame(import_frame)
            st.success(f"Imported {imported} option-context row(s).")
        except Exception as exc:
            st.exception(exc)

    option_rows = database.read_option_context_snapshots(
        instrument_key,
        default_from.isoformat(),
        default_to.isoformat(),
    )
    if option_rows:
        st.markdown("##### Stored Options Context")
        st.dataframe(
            _arrow_safe_rows(option_rows[-50:]),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption(
            "No stored options context exists for this range yet."
        )

    st.markdown("---")
    st.markdown("### Intelligence Foundation")
    st.caption("Build the leakage-safe Intelligence Dataset from completed signals.")
    ai1, ai2 = st.columns(2)
    with ai1:
        intel_from = st.date_input(
            "Dataset From",
            value=default_from,
            key="intel_dataset_workspace_from",
        )
    with ai2:
        intel_to = st.date_input(
            "Dataset To",
            value=default_to,
            key="intel_dataset_workspace_to",
        )

    if st.button(
        "Build Intelligence Dataset",
        key="intel_workspace_build_dataset",
    ):
        try:
            intel_service = RedBarIntelligenceDatasetService(
                database,
                settings,
            )
            intel_rows, report = intel_service.build_for_range(
                instrument_key,
                intel_from.isoformat(),
                intel_to.isoformat(),
            )
            st.success(
                f"Built {report.rows} completed-signal rows with "
                f"{report.features} entry-time features and "
                f"{report.labels} post-trade labels."
            )
            st.caption(f"Saved to: {report.output_path}")
            if intel_rows:
                st.dataframe(
                    _arrow_safe_rows(intel_rows[:50]),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info(
                    "No completed signals are available in this range."
                )
        except Exception as exc:
            st.exception(exc)

    st.markdown("---")
    st.markdown("### Dataset Health")
    try:
        feature_store = RedBarFeatureStore(database)
        health = feature_store.health(
            instrument_key,
            default_from.isoformat(),
            default_to.isoformat(),
        )

        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Confirmed Signals", health.confirmed_signals)
        h2.metric("Market Context", health.market_context)
        h3.metric("Volume/Structure", health.volume_structure)
        h4.metric("Options Context", health.options_context)

        h5, h6 = st.columns(2)
        h5.metric(
            "Core Context Complete",
            health.complete_core_context,
        )
        h6.metric(
            "Complete + Options",
            health.complete_with_options,
        )

        if health.confirmed_signals:
            core_pct = (
                health.complete_core_context
                / health.confirmed_signals
                * 100.0
            )
            full_pct = (
                health.complete_with_options
                / health.confirmed_signals
                * 100.0
            )
            st.progress(min(1.0, core_pct / 100.0))
            st.caption(
                f"Core context completeness: {core_pct:.1f}% · "
                f"Full context including entry-aligned options: "
                f"{full_pct:.1f}%"
            )
    except Exception as exc:
        st.warning(f"Dataset health unavailable: {exc}")
