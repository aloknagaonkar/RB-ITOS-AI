from red_bar_lab.ui.shared_strategy import date, pd, st, _arrow_safe_rows
from red_bar_lab.ui.strategy_option_context import build_option_behaviour_snapshot
from red_bar_lab.ui.strategy_input_preparation import prepare_completed_one_minute
from red_bar_lab.ui.strategy_red_bar_bundle import build_red_bar_bundle_resolution
from red_bar_lab.ui.strategy_red_bar_setup import build_red_bar_owned_setup_state
from red_bar_lab.ui.strategy_section_summary import (
    elapsed_ms,
    latest_frame_timestamp,
    latest_timestamp,
    render_option_positioning_summary,
    render_timing_caption,
    section_timer,
    timing_rows,
)
from red_bar_lab.operations.red_bar_v2_ui_snapshot import read_red_bar_v2_ui_snapshot
from red_bar_lab.services.red_bar_v2_market_data_evidence import (
    read_market_data_evidence,
)
from red_bar_lab.ui.red_bar_v2_live_runtime import resolve_red_bar_v2_live_state
from red_bar_lab.ui.red_bar_v2_legacy_panel import render_red_bar_v2_legacy_panel


def _read_cached_candles(layout, instrument_key, trading_date):
    path = layout.candle_path("upstox", instrument_key, 1, trading_date)
    if not path.exists():
        return path, pd.DataFrame()
    try:
        frame = pd.read_csv(path)
    except Exception:
        return path, pd.DataFrame()
    return path, frame


def _render_rows(rows, empty_message):
    if rows:
        st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)
    else:
        st.info(empty_message)


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Red Bar Strategy")
    # Active config header — user always sees what strategy / exit
    # policy / thresholds are in effect.
    from red_bar_lab.ui.live_cadence import render_active_paper_config

    render_active_paper_config(st)
    st.caption(
        "Independent Red Bar strategy observability. Sections 1-4 are read-only and do "
        "not create signals, bundles, contracts, orders or positions."
    )

    # Reference panel: what this strategy actually checks. Tells the
    # user the rules without making them read the code.
    with st.expander("What Red Bar V2 checks (reference)", expanded=False):
        st.markdown(
            "**A signal is admitted if all five boolean gates are True.**  \n"
            "Each gate is recorded in `process_evidence` as a separate "
            "`red_bar_v2_strategy :: check:*` row, so the per-signal "
            "audit log shows exactly which gate passed or failed."
        )
        st.markdown(
            "**The 4 gating conditions (all must be True for admission):**\n\n"
            "| Gate | Condition | Threshold |\n"
            "|---|---|---|\n"
            "| **Reference ready** | Section 1 outcome = `REFERENCE_READY` | N/A (depends on candle freshness) |\n"
            "| **Context fresh** | Latest 1m candle timestamp | Age < 120s |\n"
            "| **RedBar reference aligned** | Latest close vs reference midpoint, in signal direction | LONG: close > midpoint, SHORT: close < midpoint |\n"
            "| **VWAP aligned** | Latest close vs session VWAP, in signal direction | LONG: close ≥ VWAP, SHORT: close ≤ VWAP |\n\n"
            "**Informational (does NOT gate admission):**\n\n"
            "| Signal | What it means |\n"
            "|---|---|\n"
            "| **RSI(14)** | Reference only. Logged as `check:rsi_informational` in the audit row. |\n"
            "| **PCR (current 5m)** | Reference only. Logged as `check:pcr_informational` in the audit row. |\n"
            "| **PCR (morning fixed-level)** | Reference only. Same audit row, as `morning_pcr` artifact field. |\n"
            "| **PCR shift** | `current - morning`; positive = more bullish than open. |\n"
        )
        st.markdown(
            "**Time-windowed rules:**\n\n"
            "| Rule | Window | Effect |\n"
            "|---|---|---|\n"
            "| **Entry window** | Until 3:00 PM IST | New candidates are refused "
            "after the cutoff with `ENTRY_WINDOW_CLOSED`. Open positions keep "
            "running under the exit policy. |\n\n"
            "**Reference precedence (which level is in force):**\n\n"
            "| Location of the close | Governing reference | Gate |\n"
            "|---|---|---|\n"
            "| Inside the red bar's low-to-high band | Red bar (frozen all day) "
            "| Close vs midpoint **and** futures vs their VWAP |\n"
            "| Outside the band, on the side the deputy was born on | Working "
            "reference | Close beyond the deputy candle's high or low. No VWAP. |\n"
            "| Outside the band, on the far side | Red bar | The deputy is "
            "discarded and the full gate applies again. |\n\n"
            "**Re-entry rules (after a position closes):**\n\n"
            "| Rule | What it does |\n"
            "|---|---|\n"
            "| **Working reference** | The first completed 5m candle of the "
            "opposite colour, with a body at least half its own range, becomes a "
            "temporary reference. |\n"
            "| **Re-entry touch** | A level touch (midpoint or VWAP) starts the "
            "wait. |\n"
            "| **Re-entry VWAP confirm** | The next 5m candle's underlying close "
            "must be on the same side of the underlying futures VWAP as the touch "
            "direction. |\n"
            "| **Re-entry wait** | Logs `check:reentry_validation` with state "
            "`waiting_midpoint` / `validated` / `failed`. |"
        )
        st.markdown(
            "**Event types** (the trigger that fires):\n"
            "- `INITIAL_DISPLACEMENT` — first 5m candle in the direction "
            "of the day's NEXT_RED_CANDLE reference\n"
            "- `REVERSAL` — first close back through the reference after a "
            "counter-trend run\n"
            "- `MIDPOINT_UPGRADE` — close through the reference midpoint "
            "after an initial displacement"
        )
        st.caption(
            "Source: `red_bar_lab/strategy/red_bar_v2.py:172-360` "
            "(`evaluate_initial_direction`, `evaluate_reversal_direction`, "
            "`evaluate_midpoint_upgrade`)"
        )

    selected_date = st.date_input(
        "Trading date", value=date.today(), key="red_bar_strategy_date"
    )
    trading_date = selected_date.isoformat()

    section1_started = section_timer()
    candle_path, candles = _read_cached_candles(layout, instrument_key, trading_date)
    prepared_candles = prepare_completed_one_minute(candles, trading_date)
    levels = database.read_reference_levels(instrument_key, trading_date)
    option_context = build_option_behaviour_snapshot(database, instrument_key, trading_date)
    red_refs = [
        row for row in levels
        if str(row.get("level_type") or "") == "NEXT_RED_CANDLE"
    ]
    red_ref = red_refs[-1] if red_refs else {}

    required_columns = {"timestamp", "open", "high", "low", "close"}
    candle_columns_ready = required_columns.issubset(candles.columns)
    raw_candle_count = int(len(candles)) if candle_columns_ready else 0
    candle_count = int(len(prepared_candles))
    normalized_ready = bool(candle_count)
    reference_ready = bool(red_ref)
    readiness = "READY" if normalized_ready and reference_ready else (
        "PARTIAL" if normalized_ready else "NOT READY"
    )
    section1_refreshed = latest_timestamp(
        latest_frame_timestamp(prepared_candles),
        option_context.get("latest_timestamp"),
        red_ref.get("source_timestamp"),
        red_ref.get("updated_at"),
    )
    section1_ms = elapsed_ms(section1_started)

    st.markdown("### 1. Input Readiness")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Detection readiness", readiness)
    a2.metric("Market behaviour", option_context.get("directional_bias") or "UNAVAILABLE")
    a3.metric("Option inputs", option_context.get("status") or "NOT READY")
    a4.metric("Contract safeguards", option_context.get("execution_status") or "NOT EVALUATED")

    st.markdown("#### Core strategy inputs")
    c1, c2, c3 = st.columns(3)
    c1.metric("1-minute candles", candle_count)
    c2.metric("OHLC normalized", "YES" if normalized_ready else "NO")
    c3.metric("Red Bar reference", "READY" if reference_ready else "PENDING")

    render_option_positioning_summary(st, option_context.get("directional_bias"))
    render_timing_caption(st, refreshed_at=section1_refreshed, prepared_ms=section1_ms)

    rows = [
        {"stage": "Collected candle file", "status": "AVAILABLE" if candle_path.exists() else "MISSING", "detail": str(candle_path)},
        {"stage": "Required OHLC columns", "status": "READY" if candle_columns_ready else "MISSING", "detail": ", ".join(sorted(required_columns))},
        {"stage": "Session candle normalization", "status": "READY" if normalized_ready else "NOT READY", "detail": f"raw={raw_candle_count}; completed_valid={candle_count}"},
        {"stage": "NEXT_RED_CANDLE reference", "status": "READY" if reference_ready else "PENDING", "detail": str(red_ref.get("source_timestamp") or "Not detected/persisted")},
        {
            "stage": "Reference geometry",
            "status": "READY" if reference_ready else "PENDING",
            "detail": (
                f"High={red_ref.get('source_high')}, Low={red_ref.get('source_low')}, "
                f"Midpoint={red_ref.get('level_value') or red_ref.get('midpoint')}"
                if reference_ready else "Awaiting Red Bar reference"
            ),
        },
    ]

    with st.expander("View candle and feature preparation details"):
        st.dataframe(_arrow_safe_rows(rows), width="stretch", hide_index=True)
    with st.expander("View option behaviour details"):
        _render_rows(option_context.get("rows") or [], str(option_context.get("detail") or "Option context is unavailable."))
    with st.expander("View refresh and performance details"):
        st.dataframe(
            _arrow_safe_rows(timing_rows(
                section_name="Section 1 preparation",
                refreshed_at=section1_refreshed,
                prepared_ms=section1_ms,
            )), width="stretch", hide_index=True,
        )
    with st.expander("View live candle download evidence"):
        market_data = read_market_data_evidence(settings.artifacts_root)
        datasets = market_data.get("datasets") if isinstance(market_data.get("datasets"), list) else []
        if datasets:
            st.dataframe(_arrow_safe_rows(datasets), width="stretch", hide_index=True)
            st.caption(
                f"Correlation ID: {market_data.get('correlation_id') or 'Not available'}; "
                f"recorded after execution processing: {market_data.get('recorded_at') or 'Not available'}"
            )
        else:
            st.info(
                "WAITING: the paper monitor has not yet published live NIFTY and "
                "futures candle download evidence."
            )
    with st.expander("View preparation flow"):
        st.code(
            "1-minute candles collected\n"
            "-> Session candles normalized\n"
            "-> Opening and previous-session context loaded\n"
            "-> Red candle candidates evaluated\n"
            "-> NEXT_RED_CANDLE reference calculated\n"
            "-> High, low and midpoint persisted\n"
            "-> Stored option behaviour added as supporting evidence",
            language=None,
        )

    if readiness == "READY":
        st.success("Red Bar strategy inputs are prepared for setup detection.")
    elif readiness == "PARTIAL":
        st.warning("Candle inputs are available, but the NEXT_RED_CANDLE reference is not yet persisted.")
    else:
        st.error("Red Bar input preparation cannot start until cached 1-minute OHLC data is available.")

    section2_started = section_timer()
    setup = build_red_bar_owned_setup_state(
        database,
        instrument_key,
        trading_date,
        reference=red_ref,
        option_bias=option_context.get("directional_bias"),
    )
    section2_refreshed = latest_timestamp(
        red_ref.get("source_timestamp"),
        red_ref.get("updated_at"),
        *[
            row.get("observed")
            for row in setup.get("rows", [])
            if row.get("observed") not in (None, "", "Not persisted", "Unavailable", "Not detected", "Not confirmed")
        ],
    )
    section2_ms = elapsed_ms(section2_started)

    st.markdown("### 2. Strategy Decision")
    st.caption(
        "Read-only trace of Red Bar-owned reference creation, midpoint crossing and confirmation. "
        "RSI and DRI signal attempts are excluded."
    )
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Engine state", setup["status"])
    s2.metric("Direction", setup["direction"])
    s3.metric("Setup ID", setup["setup_id"])
    s4.metric("Option alignment", setup["option_alignment"])
    st.write(f"**Waiting for:** {setup['waiting_for']}")
    st.write(f"**Current blocker:** {setup['blocker']}")
    render_timing_caption(st, refreshed_at=section2_refreshed, prepared_ms=section2_ms)

    with st.expander("View condition-by-condition trace"):
        st.dataframe(_arrow_safe_rows(setup["rows"]), width="stretch", hide_index=True)
    with st.expander("View Section 2 refresh and performance details"):
        st.dataframe(
            _arrow_safe_rows(timing_rows(
                section_name="Section 2 setup trace",
                refreshed_at=section2_refreshed,
                prepared_ms=section2_ms,
            )), width="stretch", hide_index=True,
        )

    section3_started = section_timer()
    bundle = build_red_bar_bundle_resolution(
        database=database,
        instrument_key=instrument_key,
        trading_date=trading_date,
        reference=red_ref,
    )
    section3_ms = elapsed_ms(section3_started)

    st.markdown("### 3. Signal Bundle")
    st.caption(
        "The bundle contains only Red Bar reference, midpoint-cross and confirmation evidence. "
        "RSI and DRI signals, cooldowns and consumption states do not affect it."
    )
    n1, n2, n3, n4 = st.columns(4)
    n1.metric("Signal state", bundle["signal_state"])
    n2.metric("Normalized intent", bundle["normalized_intent"])
    n3.metric("Bundle state", bundle["bundle_state"])
    n4.metric("Final result", bundle["final_outcome"])

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Strategy owner", bundle["strategy_owner"])
    b2.metric("Bundle ID", bundle["bundle_id"])
    b3.metric("Signal age", bundle["signal_age"])
    b4.metric("Entry capacity", bundle["entry_capacity"])

    st.write(f"**Decision reason:** {bundle['decision_reason']}")
    st.write(f"**Applied lifecycle rule:** {bundle['applied_rule']}")
    st.write(f"**Next architectural step:** {bundle['next_step']}")
    render_timing_caption(st, refreshed_at=bundle.get("refreshed_at"), prepared_ms=section3_ms)

    with st.expander("View confirmed Red Bar event"):
        _render_rows(bundle["signal_rows"], "No confirmed Red Bar event is available for the selected date.")
    with st.expander("View Red Bar bundle"):
        _render_rows(bundle["bundle_rows"], "No Red Bar bundle can be built until reference, cross and confirmation are complete.")
    with st.expander("View Red Bar consumption lifecycle"):
        _render_rows(bundle["lifecycle_rows"], "No strategy-and-bundle-scoped Red Bar execution events were found.")
    with st.expander("How was this Red Bar bundle created?"):
        st.write(f"**Strategy owner:** {bundle['strategy_owner']}")
        st.write(f"**Signal ID:** {bundle['signal_id']}")
        st.write(f"**Bundle ID:** {bundle['bundle_id']}")
        st.write(f"**Normalized intention:** {bundle['normalized_intent']}")
        st.write(f"**Entry capacity:** {bundle['entry_capacity']}")
        st.write(f"**Applied rule:** {bundle['applied_rule']}")
        st.write(f"**Outcome:** {bundle['final_outcome']}")
        st.write(f"**Reason:** {bundle['decision_reason']}")
        st.write(f"**Next step:** {bundle['next_step']}")
    with st.expander("View Section 3 refresh and performance details"):
        st.dataframe(
            _arrow_safe_rows(timing_rows(
                section_name="Section 3 Red Bar bundle lifecycle",
                refreshed_at=bundle.get("refreshed_at"),
                prepared_ms=section3_ms,
            )), width="stretch", hide_index=True,
        )

    file_snapshot = read_red_bar_v2_ui_snapshot(settings.artifacts_root)
    resolved_snapshot, runtime_diagnostics = resolve_red_bar_v2_live_state(
        database,
        file_snapshot,
        instrument_key=instrument_key,
        trading_date=trading_date,
    )
    render_red_bar_v2_legacy_panel(
        st,
        resolved_snapshot,
        option_context=option_context,
        runtime_diagnostics=runtime_diagnostics,
    )

    st.info(
        "Sections 1-4 are read-only. The displayed Red Bar bundle is constructed in memory "
        "for observability; opening this page does not persist, forward, consume or execute it."
    )
