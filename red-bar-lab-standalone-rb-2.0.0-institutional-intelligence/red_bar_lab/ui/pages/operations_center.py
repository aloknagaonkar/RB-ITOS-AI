from red_bar_lab.ui._shared import *
from red_bar_lab.platform.state_store import AtomicJsonStore, ComponentState
from pathlib import Path


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


def _pipeline_stage_card_html(title, status, status_class, rows) -> str:
    row_html = "".join(
        (
            "<div class='rb-pipeline-row'>"
            f"<span>{label}</span>"
            f"<strong>{value}</strong>"
            "</div>"
        )
        for label, value in rows
    )
    return (
        f"<div class='rb-pipeline-card rb-pipeline-card-{status_class}'>"
        "<div class='rb-pipeline-card-header'>"
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


def _render_platform_runtime_health(settings) -> None:
    state_path = settings.artifacts_root / "platform" / "platform_state.json"
    if not state_path.exists():
        state_path = Path(__file__).resolve().parent.parent.parent.parent / "artifacts" / "red_bar" / "platform" / "platform_state.json"

    store = AtomicJsonStore(state_path)
    platform = store.read_platform_state()
    components = store.read_all_components()

    if not components:
        st.info(
            "No runtime health data available. "
            "Start the platform with: python -m red_bar_lab.platform.control start"
        )
        return

    now = pd.Timestamp.now(tz="Asia/Kolkata")

    def _heartbeat_age(comp: ComponentState) -> str:
        if not comp.heartbeat_at:
            return "No heartbeat"
        try:
            hb = pd.Timestamp(comp.heartbeat_at)
            if hb.tzinfo is None:
                hb = hb.tz_localize("UTC")
            age = max(0, int((now - hb.tz_convert("Asia/Kolkata")).total_seconds()))
            if age <= 30:
                return f"{age}s"
            if age <= 120:
                return f"{age // 60}m {age % 60}s"
            return f"{age // 60}m {age % 60}s (stale)"
        except (TypeError, ValueError):
            return "Invalid"

    def _health_state(comp: ComponentState, spec_fresh: float = 30.0, spec_stale: float = 90.0) -> str:
        if comp.state in ("STOPPED",):
            return "STOPPED"
        if comp.state in ("ERROR", "CRASHED"):
            return "UNHEALTHY"
        if not comp.heartbeat_at:
            return "STARTING"
        try:
            hb = pd.Timestamp(comp.heartbeat_at)
            if hb.tzinfo is None:
                hb = hb.tz_localize("UTC")
            age = max(0, (now - hb.tz_convert("Asia/Kolkata")).total_seconds())
            if age <= spec_fresh:
                return "HEALTHY"
            if age <= spec_stale:
                return "DEGRADED"
            return "STALE"
        except (TypeError, ValueError):
            return "UNKNOWN"

    fresh_thresholds = {
        "market_collector": (60, 180),
        "paper_monitor": (15, 30),
        "position_monitor": (15, 30),
        "market_research": (20, 40),
        "ui": (999999, 999999),
    }

    rows = []
    overall = "HEALTHY"
    for name, comp in sorted(components.items()):
        fresh, stale = fresh_thresholds.get(name, (30, 90))
        health = _health_state(comp, fresh, stale)
        age_str = _heartbeat_age(comp)
        pid_str = str(comp.pid) if comp.pid else "—"

        if health == "UNHEALTHY" and comp.required if hasattr(comp, "required") else True:
            overall = "ENTRY_SUSPENDED"
        elif health == "DEGRADED" and overall == "HEALTHY":
            overall = "DEGRADED"
        elif health == "STALE" and overall in ("HEALTHY", "DEGRADED"):
            overall = "DEGRADED"

        outcome = comp.last_outcome or "—"
        if len(outcome) > 40:
            outcome = outcome[:37] + "..."

        rows.append({
            "Component": name,
            "State": health,
            "PID": pid_str,
            "Heartbeat Age": age_str,
            "Last Outcome": outcome,
            "Restarts": comp.restart_count,
        })

    st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)

    if platform.platform_state:
        state_col1, state_col2 = st.columns(2)
        state_col1.metric("Platform State", platform.platform_state)
        state_col2.metric("Overall Health", overall)


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

    st.markdown("### Platform Runtime Health")
    _render_platform_runtime_health(settings)

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

    st.markdown("### Data Readiness Gate v1")
    quality = ops.data_quality
    pipeline = ops.pipeline
    latest_data_timestamp = market.get("last_snapshot")
    page_refresh_timestamp = pd.Timestamp.now(tz="Asia/Kolkata")
    freshness_text, freshness_class, freshness_age = _snapshot_freshness(
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

    missing_market_count = _availability_count(
        quality.get("missing_market_context")
    )
    volume_missing_count = _availability_count(
        quality.get("missing_volume_structure")
    )
    options_missing_count = _availability_count(
        quality.get("missing_options_context")
    )
    pipeline_error_count = _availability_count(
        quality.get("pipeline_errors")
    )

    volume_ready = volume_missing_count == 0
    volume_value = "Ready" if volume_ready else "Missing data"
    volume_class = "available" if volume_ready else "partial"

    options_ready = options_missing_count == 0
    option_status = "AVAILABLE" if options_ready else "PARTIAL"
    option_status_class = "available" if options_ready else "partial"

    blocking_reasons = []
    warning_reasons = []
    if latest_data_timestamp in (None, "", "—"):
        blocking_reasons.append("No successful Upstox option-chain snapshot is available.")
    if (
        str(market.get("phase") or "").upper() == "OPEN"
        and freshness_class == "unavailable"
    ):
        blocking_reasons.append(
            f"Latest option-chain snapshot is stale ({freshness_age}s old)."
        )
    if str(market.get("collector_status") or "").upper() == "ERROR":
        blocking_reasons.append("Collector status is ERROR.")
    if pipeline_error_count and pipeline_error_count > 0:
        blocking_reasons.append(
            f"Pipeline has {pipeline_error_count} recorded error(s)."
        )

    for label, count in (
        ("market context", missing_market_count),
        ("volume / structure", volume_missing_count),
        ("options context", options_missing_count),
    ):
        if count is None:
            warning_reasons.append(f"{label.title()} count is unavailable.")
        elif count > 0:
            warning_reasons.append(f"{count} signal(s) are missing {label}.")

    if freshness_class == "partial":
        warning_reasons.append("Latest option-chain snapshot is delayed.")
    warning_reasons.extend(
        (
            "Chain completeness validation is not implemented yet.",
            "Zero/stale quote validation is not implemented yet.",
            "Underlying candle freshness is not validated yet.",
        )
    )

    if blocking_reasons:
        readiness_state = "NOT READY"
        readiness_class = "unavailable"
    elif warning_reasons:
        readiness_state = "PARTIAL"
        readiness_class = "partial"
    else:
        readiness_state = "READY"
        readiness_class = "available"

    readiness_reason_html = "".join(
        f"<li class='rb-data-unavailable'>{reason}</li>"
        for reason in blocking_reasons
    ) + "".join(
        f"<li class='rb-data-partial'>{reason}</li>"
        for reason in warning_reasons
    )

    st.markdown(
        "<div class='rb-readiness-banner "
        f"rb-readiness-banner-{readiness_class}'>"
        "<div class='rb-readiness-banner-header'>"
        "<strong>Overall data readiness</strong>"
        f"<span class='rb-data-badge rb-data-badge-{readiness_class}'>"
        f"{readiness_state}</span>"
        "</div>"
        "<ul class='rb-readiness-reasons'>"
        f"{readiness_reason_html}"
        "</ul>"
        "</div>",
        unsafe_allow_html=True,
    )

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
        .rb-readiness-banner {
            border: 1px solid #E5E7EB;
            border-left-width: 4px;
            border-radius: 9px;
            padding: 0.7rem 0.8rem;
            margin-bottom: 0.65rem;
        }
        .rb-readiness-banner-available {
            background:#F0FDF4;
            border-left-color:#16A34A;
        }
        .rb-readiness-banner-partial {
            background:#FFFBEB;
            border-left-color:#F59E0B;
        }
        .rb-readiness-banner-unavailable {
            background:#FEF2F2;
            border-left-color:#DC2626;
        }
        .rb-readiness-banner-header {
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:0.75rem;
        }
        .rb-readiness-reasons {
            margin:0.45rem 0 0 1rem;
            padding:0;
            font-size:0.76rem;
        }
        .rb-data-meta {
            font-size: 0.76rem;
            color: #6B7280;
            line-height: 1.45;
            margin-top: -0.1rem;
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
            "Source Availability",
            "PARTIAL",
            "partial",
            (
                ("1-minute OHLC", "Supported", "available"),
                ("Volume", volume_value, volume_class),
                ("RSI(7) input", "Supported", "available"),
                ("Candle freshness", "Not validated", "unknown"),
            ),
        ),
        _availability_card_html(
            "Option-Chain Collection",
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
            "Quality Controls",
            "PARTIAL",
            "partial",
            (
                ("Snapshot freshness", freshness_text, freshness_class),
                ("Chain completeness", "Not validated", "unknown"),
                ("Zero / stale quotes", "Not validated", "unknown"),
                ("Execution authority", "None", "unknown"),
            ),
        ),
    )
    for column, card in zip(availability_columns, availability_cards):
        column.markdown(card, unsafe_allow_html=True)

    st.caption(
        "Data Readiness Gate v1 is a read-only architecture and diagnostics "
        "view. It does not block execution or change strategy decisions."
    )

    st.markdown("### Signal Enrichment Pipeline")
    st.caption(
        "Confirmed signals are enriched independently with market, volume and "
        "options context before CORE and HYBRID readiness is calculated."
    )

    signals_today = _availability_count(pipeline.get("signals_today")) or 0
    confirmed_signals = _availability_count(
        pipeline.get("confirmed_signals")
    ) or 0
    active_signals = _availability_count(pipeline.get("active_signals")) or 0
    failed_signals = _availability_count(pipeline.get("failed_signals")) or 0
    core_ready = _availability_count(pipeline.get("core_ready")) or 0
    hybrid_ready = _availability_count(pipeline.get("hybrid_ready")) or 0

    market_ready_count = max(
        0,
        confirmed_signals - (missing_market_count or 0),
    )
    volume_ready_count = max(
        0,
        confirmed_signals - (volume_missing_count or 0),
    )
    options_ready_count = max(
        0,
        confirmed_signals - (options_missing_count or 0),
    )

    def _stage_status(ready_count, total_count, missing_count=None):
        if total_count == 0:
            return "WAITING", "unknown"
        if missing_count is None:
            return "UNKNOWN", "unknown"
        if ready_count >= total_count:
            return "READY", "available"
        if ready_count > 0:
            return "PARTIAL", "partial"
        return "MISSING", "unavailable"

    signal_status = "READY" if confirmed_signals > 0 else "WAITING"
    signal_class = "available" if confirmed_signals > 0 else "unknown"
    market_status, market_class = _stage_status(
        market_ready_count,
        confirmed_signals,
        missing_market_count,
    )
    volume_status, volume_stage_class = _stage_status(
        volume_ready_count,
        confirmed_signals,
        volume_missing_count,
    )
    options_stage_status, options_stage_class = _stage_status(
        options_ready_count,
        confirmed_signals,
        options_missing_count,
    )

    feature_ready = min(market_ready_count, volume_ready_count)
    feature_status, feature_class = _stage_status(
        feature_ready,
        confirmed_signals,
        max(missing_market_count or 0, volume_missing_count or 0),
    )

    eligibility_status = (
        "READY"
        if confirmed_signals > 0 and core_ready == confirmed_signals
        else "PARTIAL"
        if core_ready > 0 or hybrid_ready > 0
        else "WAITING"
    )
    eligibility_class = (
        "available"
        if eligibility_status == "READY"
        else "partial"
        if eligibility_status == "PARTIAL"
        else "unknown"
    )

    pipeline_status_value = str(
        pipeline.get("pipeline_status") or "UNKNOWN"
    ).upper()
    pipeline_health_class = (
        "available"
        if pipeline_status_value in {"HEALTHY", "READY", "OK"}
        else "unavailable"
        if pipeline_status_value in {"ERROR", "FAILED", "CRITICAL"}
        else "partial"
    )

    st.markdown(
        """
        <style>
        .rb-pipeline-flow {
            display: grid;
            grid-template-columns: repeat(6, minmax(145px, 1fr));
            gap: 0.55rem;
            overflow-x: auto;
            padding-bottom: 0.2rem;
        }
        .rb-pipeline-card {
            border: 1px solid #E5E7EB;
            border-top-width: 3px;
            border-radius: 10px;
            padding: 0.7rem 0.75rem;
            background: var(--secondary-background-color);
            min-height: 148px;
        }
        .rb-pipeline-card-available { border-top-color:#22C55E; }
        .rb-pipeline-card-partial { border-top-color:#F59E0B; }
        .rb-pipeline-card-unavailable { border-top-color:#DC2626; }
        .rb-pipeline-card-unknown { border-top-color:#9CA3AF; }
        .rb-pipeline-card-header {
            display:flex;
            justify-content:space-between;
            align-items:center;
            gap:0.4rem;
            margin-bottom:0.55rem;
            font-size:0.82rem;
        }
        .rb-pipeline-row {
            display:flex;
            justify-content:space-between;
            gap:0.5rem;
            padding:0.22rem 0;
            border-bottom:1px solid rgba(107,114,128,0.14);
            font-size:0.73rem;
        }
        .rb-pipeline-row:last-child { border-bottom:0; }
        .rb-pipeline-row strong { text-align:right; }
        .rb-pipeline-health {
            margin-top:0.65rem;
            padding:0.55rem 0.7rem;
            border:1px solid #E5E7EB;
            border-radius:8px;
            font-size:0.77rem;
            background:var(--secondary-background-color);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    pipeline_cards = (
        _pipeline_stage_card_html(
            "1. Confirmed Signals",
            signal_status,
            signal_class,
            (
                ("Signals today", signals_today),
                ("Confirmed", confirmed_signals),
                ("Active", active_signals),
                ("Failed / timeout", failed_signals),
            ),
        ),
        _pipeline_stage_card_html(
            "2. Market Context",
            market_status,
            market_class,
            (
                ("Ready", market_ready_count),
                ("Missing", missing_market),
                ("Source", "Market context service"),
                ("Scope", "Per confirmed signal"),
            ),
        ),
        _pipeline_stage_card_html(
            "3. Volume & Structure",
            volume_status,
            volume_stage_class,
            (
                ("Ready", volume_ready_count),
                ("Missing", missing_volume),
                ("Source", "Volume structure service"),
                ("Scope", "Per confirmed signal"),
            ),
        ),
        _pipeline_stage_card_html(
            "4. Option Context",
            options_stage_status,
            options_stage_class,
            (
                ("Linked", options_ready_count),
                ("Missing", missing_options),
                ("Link window", "120 seconds"),
                ("Snapshot", freshness_text),
            ),
        ),
        _pipeline_stage_card_html(
            "5. Feature Store",
            feature_status,
            feature_class,
            (
                ("CORE inputs", feature_ready),
                ("Market layer", market_ready_count),
                ("Volume layer", volume_ready_count),
                ("Options layer", options_ready_count),
            ),
        ),
        _pipeline_stage_card_html(
            "6. Eligibility",
            eligibility_status,
            eligibility_class,
            (
                ("CORE ready", core_ready),
                ("HYBRID ready", hybrid_ready),
                ("CORE rule", "Market + Volume"),
                ("HYBRID rule", "CORE + Options"),
            ),
        ),
    )
    st.markdown(
        "<div class='rb-pipeline-flow'>"
        + "".join(pipeline_cards)
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='rb-pipeline-health'>"
        f"<strong>Pipeline health:</strong> "
        f"<span class='rb-data-{pipeline_health_class}'>"
        f"{pipeline_status_value}</span> · "
        f"<strong>Errors:</strong> {pipeline_errors} · "
        f"<strong>EOD validation:</strong> {pipeline.get('eod_status')}"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Each enrichment stage is fault-isolated. Missing intelligence is "
        "reported here but does not change the frozen strategy or execution "
        "authority."
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
