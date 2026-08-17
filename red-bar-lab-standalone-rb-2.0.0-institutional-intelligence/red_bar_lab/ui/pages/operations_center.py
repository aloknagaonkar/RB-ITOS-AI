from red_bar_lab.ui._shared import *


def _format_data_availability_timestamp(value) -> str:
    if value in (None, "", "—"):
        return "Not available"
    try:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("Asia/Kolkata")
        else:
            timestamp = timestamp.tz_convert("Asia/Kolkata")
        return timestamp.strftime("%d %b %Y, %I:%M:%S %p IST")
    except (TypeError, ValueError):
        return str(value)


def _availability_card_html(title, status, status_class, rows) -> str:
    row_html = "".join(
        (
            "<div class='rb-data-row'>"
            f"<span>{label}</span>"
            f"<strong class='rb-data-value rb-data-{row_class}'>{value}</strong>"
            "</div>"
        )
        for label, value, row_class in rows
    )
    return (
        f"<div class='rb-data-card rb-data-card-{status_class}'>"
        "<div class='rb-data-card-header'>"
        f"<strong>{title}</strong>"
        f"<span class='rb-data-badge rb-data-badge-{status_class}'>{status}</span>"
        "</div>"
        f"{row_html}"
        "</div>"
    )


def _availability_count(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count_status(value):
    count = _availability_count(value)
    if count is None:
        return "Not available", "unknown"
    if count == 0:
        return "0", "available"
    return str(count), "partial"


def _snapshot_freshness(value, market_phase):
    if value in (None, "", "—"):
        return "Not available", "unavailable", None
    try:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("Asia/Kolkata")
        else:
            timestamp = timestamp.tz_convert("Asia/Kolkata")
        now = pd.Timestamp.now(tz="Asia/Kolkata")
        age_seconds = max(0, int((now - timestamp).total_seconds()))
    except (TypeError, ValueError):
        return "Not available", "unknown", None

    if str(market_phase or "").upper() != "OPEN":
        return f"{age_seconds}s old", "unknown", age_seconds
    if age_seconds <= 90:
        return f"Fresh · {age_seconds}s", "available", age_seconds
    if age_seconds <= 180:
        return f"Delayed · {age_seconds}s", "partial", age_seconds
    return f"Stale · {age_seconds}s", "unavailable", age_seconds


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Operations Center")
    st.caption(
        "Mission control for platform health, market operations, "
        "intelligence readiness, data quality and AI training readiness."
    )

    operations = RedBarOperationsCenterService(
        database,
        settings,
    )
    ops = operations.snapshot(
        instrument_key=instrument_key,
        trading_date=date.today().isoformat(),
        token_present=bool(
            token.strip()
            or os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
        ),
    )

    if ops.health_score >= 90:
        health_state = "HEALTHY"
    elif ops.health_score >= 70:
        health_state = "WARNING"
    else:
        health_state = "CRITICAL"

    st.markdown("### Overall Health")
    oh1, oh2, oh3 = st.columns(3)
    oh1.metric("Health Score", f"{ops.health_score}/100")
    oh2.metric("State", health_state)
    oh3.metric("Version", settings.version)
    st.progress(min(1.0, ops.health_score / 100.0))

    st.markdown("### Platform Health")
    health_rows = [
        {
            "Service": item.name,
            "State": item.state,
            "Detail": item.detail,
        }
        for item in ops.platform_health
    ]
    st.dataframe(
        _arrow_safe_rows(health_rows),
        width="stretch",
        hide_index=True,
    )

    st.markdown("### Market Operations")
    market = ops.market
    mo1, mo2, mo3, mo4 = st.columns(4)
    mo1.metric("Market Phase", market.get("phase"))
    mo2.metric("Collector", market.get("collector_status"))
    mo3.metric("Last Snapshot", market.get("last_snapshot"))
    mo4.metric("Snapshots Today", market.get("snapshots_today"))

    mo5, mo6, mo7, mo8 = st.columns(4)
    mo5.metric(
        "Online Snapshots",
        market.get("online_snapshots_today"),
    )
    mo6.metric(
        "EOD Snapshots",
        market.get("eod_snapshots_today"),
    )
    mo7.metric(
        "Collector Mode",
        market.get("collector_mode"),
    )
    mo8.metric(
        "Current Expiry",
        market.get("current_expiry") or "—",
    )
    st.caption(f"Current time: {market.get('current_time')}")

    st.markdown("### Data Availability")
    quality = ops.data_quality
    pipeline = ops.pipeline
    latest_data_timestamp = market.get("last_snapshot")
    page_refresh_timestamp = pd.Timestamp.now(tz="Asia/Kolkata")
    freshness_text, freshness_class, _ = _snapshot_freshness(
        latest_data_timestamp,
        market.get("phase"),
    )

    missing_market, missing_market_class = _count_status(
        quality.get("missing_market_context")
    )
    missing_volume, missing_volume_class = _count_status(
        quality.get("missing_volume_structure")
    )
    missing_options, missing_options_class = _count_status(
        quality.get("missing_options_context")
    )
    pipeline_errors, pipeline_errors_class = _count_status(
        quality.get("pipeline_errors")
    )

    volume_missing_count = _availability_count(
        quality.get("missing_volume_structure")
    )
    volume_ready = volume_missing_count == 0
    volume_value = "Ready" if volume_ready else "Missing data"
    volume_class = "available" if volume_ready else "partial"

    options_missing_count = _availability_count(
        quality.get("missing_options_context")
    )
    options_ready = options_missing_count == 0
    option_status = "AVAILABLE" if options_ready else "PARTIAL"
    option_status_class = "available" if options_ready else "partial"

    st.markdown(
        "<div class='rb-data-meta'>"
        "<div><strong>Last successful Upstox option-chain collection:</strong> "
        f"{_format_data_availability_timestamp(latest_data_timestamp)}</div>"
        "<div><strong>Page refreshed:</strong> "
        f"{_format_data_availability_timestamp(page_refresh_timestamp)}</div>"
        "<div><strong>Collector cadence:</strong> 60 seconds by default · "
        "<strong>Broker timestamp:</strong> Not provided</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='rb-missing-strip'>"
        "<span>Missing today:</span> "
        f"<strong class='rb-data-{missing_market_class}'>Market {missing_market}</strong> · "
        f"<strong class='rb-data-{missing_volume_class}'>Volume {missing_volume}</strong> · "
        f"<strong class='rb-data-{missing_options_class}'>Options {missing_options}</strong> · "
        f"<strong class='rb-data-{pipeline_errors_class}'>Pipeline errors {pipeline_errors}</strong>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <style>
        .rb-data-meta {
            font-size: 0.76rem;
            color: #6B7280;
            line-height: 1.45;
            margin-top: -0.35rem;
            margin-bottom: 0.45rem;
        }
        .rb-missing-strip {
            font-size: 0.78rem;
            padding: 0.45rem 0.65rem;
            border: 1px solid #E5E7EB;
            border-radius: 8px;
            margin-bottom: 0.7rem;
            background: var(--secondary-background-color);
        }
        .rb-data-card {
            border: 1px solid #E5E7EB;
            border-top-width: 3px;
            border-radius: 10px;
            padding: 0.8rem 0.85rem;
            background: var(--secondary-background-color);
            min-height: 190px;
        }
        .rb-data-card-available { border-top-color: #22C55E; }
        .rb-data-card-partial { border-top-color: #F59E0B; }
        .rb-data-card-unavailable { border-top-color: #DC2626; }
        .rb-data-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            margin-bottom: 0.65rem;
        }
        .rb-data-badge {
            border-radius: 999px;
            padding: 0.16rem 0.48rem;
            font-size: 0.66rem;
            font-weight: 700;
            white-space: nowrap;
        }
        .rb-data-badge-available { background:#DCFCE7;color:#166534; }
        .rb-data-badge-partial { background:#FEF3C7;color:#92400E; }
        .rb-data-badge-unavailable { background:#FEE2E2;color:#991B1B; }
        .rb-data-row {
            display: flex;
            justify-content: space-between;
            gap: 0.65rem;
            padding: 0.25rem 0;
            border-bottom: 1px solid rgba(107,114,128,0.16);
            font-size: 0.78rem;
        }
        .rb-data-row:last-child { border-bottom: 0; }
        .rb-data-value { text-align: right; white-space: nowrap; }
        .rb-data-available { color:#16A34A; }
        .rb-data-partial { color:#D97706; }
        .rb-data-unavailable { color:#DC2626; }
        .rb-data-unknown { color:#6B7280; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    availability_columns = st.columns(4)
    availability_cards = (
        _availability_card_html(
            "Underlying Data",
            "PARTIAL",
            "partial",
            (
                ("1-minute OHLC", "Supported", "available"),
                ("Current volume", volume_value, volume_class),
                ("RSI(7)", "Supported", "available"),
                ("Candle freshness", "Not validated", "unknown"),
            ),
        ),
        _availability_card_html(
            "Option-Chain Data",
            option_status,
            option_status_class,
            (
                ("Spot / ATM", "Available", "available"),
                ("CE / PE price", "Available", "available"),
                ("Volume / OI / PCR", "Available", "available"),
                ("Collection freshness", freshness_text, freshness_class),
            ),
        ),
        _availability_card_html(
            "Liquidity & Greeks",
            "PARTIAL",
            "partial",
            (
                ("Bid / Ask", "Available", "available"),
                ("Spread", "Partial", "partial"),
                ("IV and Greeks", "Available", "available"),
                ("Relative volume", "Not validated", "unknown"),
            ),
        ),
        _availability_card_html(
            "Data Quality Controls",
            "NOT AVAILABLE",
            "unavailable",
            (
                ("Broker data timestamp", "Not provided", "unknown"),
                ("Chain completeness", "Not available", "unavailable"),
                ("Stale quote check", "Not available", "unavailable"),
                ("Execution readiness", "Not available", "unavailable"),
            ),
        ),
    )
    for column, card in zip(availability_columns, availability_cards):
        column.markdown(card, unsafe_allow_html=True)

    st.caption(
        "The Upstox collection time is the latest successfully stored option-chain "
        "snapshot. It is not an authoritative broker-provided market-data timestamp. "
        "Availability remains informational and cannot change execution decisions."
    )

    st.markdown("### Intelligence Pipeline")
    ip1, ip2, ip3, ip4 = st.columns(4)
    ip1.metric("Signals Today", pipeline.get("signals_today"))
    ip2.metric(
        "Confirmed",
        pipeline.get("confirmed_signals"),
    )
    ip3.metric("CORE Ready", pipeline.get("core_ready"))
    ip4.metric("HYBRID Ready", pipeline.get("hybrid_ready"))

    ip5, ip6, ip7, ip8 = st.columns(4)
    ip5.metric(
        "Market Context",
        pipeline.get("market_context"),
    )
    ip6.metric(
        "Volume / Structure",
        pipeline.get("volume_structure"),
    )
    ip7.metric(
        "Options Context",
        pipeline.get("options_context"),
    )
    ip8.metric(
        "Pipeline Status",
        pipeline.get("pipeline_status"),
    )

    st.caption(
        f"Active signals: {pipeline.get('active_signals')} · "
        f"Failed/timeout: {pipeline.get('failed_signals')} · "
        f"EOD validation: {pipeline.get('eod_status')}"
    )

    st.markdown("### AI Readiness")
    ai = ops.ai_readiness
    ar1, ar2, ar3, ar4 = st.columns(4)
    ar1.metric("Training Samples", ai.get("training_samples"))
    ar2.metric("Target Samples", ai.get("target_samples"))
    ar3.metric(
        "Readiness",
        f"{float(ai.get('readiness_pct') or 0):.1f}%",
    )
    ar4.metric("Status", ai.get("status"))

    st.progress(
        min(
            1.0,
            float(ai.get("readiness_pct") or 0) / 100.0,
        )
    )

    ar5, ar6, ar7 = st.columns(3)
    ar5.metric(
        "Historical Signals",
        ai.get("historical_signals"),
    )
    ar6.metric(
        "Feature Store Rows",
        ai.get("feature_store_rows"),
    )
    ar7.metric(
        "Historical Options Days",
        ai.get("historical_options_days"),
    )
    st.caption(
        "AI readiness measures available training-data volume only. "
        "It is not a prediction-accuracy score."
    )

    st.markdown("### Data Quality")
    dq1, dq2, dq3, dq4 = st.columns(4)
    dq1.metric(
        "Missing Market",
        quality.get("missing_market_context"),
    )
    dq2.metric(
        "Missing Volume",
        quality.get("missing_volume_structure"),
    )
    dq3.metric(
        "Missing Options",
        quality.get("missing_options_context"),
    )
    dq4.metric(
        "Duplicate Snapshots",
        quality.get("duplicate_snapshots"),
    )

    dq5, dq6, dq7 = st.columns(3)
    dq5.metric(
        "Incomplete CORE",
        quality.get("incomplete_core"),
    )
    dq6.metric(
        "Incomplete HYBRID",
        quality.get("incomplete_hybrid"),
    )
    dq7.metric(
        "Pipeline Errors",
        quality.get("pipeline_errors"),
    )

    st.markdown("### Performance & Storage")
    perf = ops.performance
    pf1, pf2, pf3, pf4 = st.columns(4)
    pf1.metric(
        "Database Size",
        f"{float(perf.get('database_size_mb') or 0):.2f} MB",
    )
    pf2.metric(
        "Artifacts Size",
        f"{float(perf.get('artifacts_size_mb') or 0):.2f} MB",
    )
    pf3.metric(
        "Feature Store Rows",
        perf.get("feature_store_rows"),
    )
    heartbeat = perf.get("collector_heartbeat_age_sec")
    pf4.metric(
        "Collector Heartbeat Age",
        (
            f"{float(heartbeat):.0f}s"
            if heartbeat is not None else "—"
        ),
    )
    if perf.get("ui_process_memory_mb") is not None:
        st.caption(
            f"UI process memory: "
            f"{float(perf.get('ui_process_memory_mb')):.2f} MB"
        )

    st.markdown("### Portfolio Intelligence — Shadow Mode")
    ops_orders = database.read_paper_execution_orders("PAPER-STD")
    ops_open = [
        row for row in ops_orders if row.get("status") == "OPEN"
    ]
    ce_open = sum(
        1 for row in ops_open
        if str(row.get("option_type") or "").upper() == "CE"
    )
    pe_open = sum(
        1 for row in ops_open
        if str(row.get("option_type") or "").upper() == "PE"
    )
    if ce_open and pe_open:
        exposure = "MIXED / HEDGED"
    elif ce_open:
        exposure = "BULLISH (CE)"
    elif pe_open:
        exposure = "BEARISH (PE)"
    else:
        exposure = "FLAT"

    latest_shadow_rows = (
        database.read_shadow_intelligence_evaluations(limit=1)
    )
    latest_shadow = (
        latest_shadow_rows[0] if latest_shadow_rows else None
    )

    pi1, pi2, pi3, pi4, pi5, pi6 = st.columns(6)
    pi1.metric("Open CE", ce_open)
    pi2.metric("Open PE", pe_open)
    pi3.metric("Net Exposure", exposure)
    pi4.metric(
        "Shadow Decision",
        (
            latest_shadow.get("shadow_decision")
            if latest_shadow else "NO DATA"
        ),
    )
    pi5.metric(
        "Portfolio Conflict",
        (
            "YES"
            if latest_shadow
            and latest_shadow.get("portfolio_conflict")
            else "NO"
        ),
    )
    pi6.metric(
        "Suggested Action",
        (
            latest_shadow.get("portfolio_action")
            if latest_shadow else "OBSERVE"
        ),
    )
    st.markdown(
        _decision_badge_html(
            "SHADOW MODE · EXECUTION IMPACT = NONE",
            "shadow",
        ),
        unsafe_allow_html=True,
    )
    if latest_shadow:
        st.caption(
            f"Latest evaluation: {latest_shadow.get('evaluated_at')} · "
            f"Current engine: {latest_shadow.get('current_decision')} · "
            f"Agreement: {latest_shadow.get('agreement')} · "
            f"Shadow confidence: "
            f"{float(latest_shadow.get('shadow_confidence') or 0):.1f}%"
        )
    else:
        st.caption(
            "Shadow observations appear here after Paper Trading has "
            "evaluated a current option candidate."
        )

    st.markdown("### Shadow Validation Snapshot")
    try:
        ops_validation = ShadowValidationService(database).evaluate()
        ops_shadow = ops_validation["summary"]
        va1, va2, va3, va4, va5 = st.columns(5)
        va1.metric(
            "Current Win Rate",
            f"{ops_shadow.current_win_rate:.1f}%",
        )
        va2.metric(
            "Shadow Accuracy",
            (
                f"{ops_shadow.shadow_accuracy:.1f}%"
                if ops_shadow.shadow_accuracy is not None
                else "LEARNING"
            ),
        )
        va3.metric(
            "Agreement Rate",
            (
                f"{ops_shadow.agreement_rate:.1f}%"
                if ops_shadow.agreement_rate is not None
                else "—"
            ),
        )
        va4.metric(
            "Stable Shadow",
            (
                f"{ops_shadow.latest_shadow_decision} · "
                f"{ops_shadow.stability_minutes:.1f}m"
            ),
        )
        va5.metric(
            "Resolved Samples",
            ops_shadow.shadow_resolved,
        )
        st.caption(
            "Validation is evidence-only. Shadow analytics cannot change "
            "paper execution. See Intelligence → Shadow Validation Dashboard "
            "for module-level accuracy and promotion candidates."
        )
    except Exception as exc:
        st.caption(
            f"Shadow validation snapshot unavailable: {exc}"
        )

    st.markdown("### Today's Timeline")
    if ops.timeline:
        timeline_rows = [
            {
                "Time": row.get("time"),
                "Event": row.get("event"),
                "Detail": row.get("detail"),
            }
            for row in ops.timeline
        ]
        st.dataframe(
            _arrow_safe_rows(timeline_rows),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info(
            "No operational timeline events are available for today yet."
        )
