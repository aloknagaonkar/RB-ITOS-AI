from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping

from red_bar_lab.config import RedBarSettings
from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot
from red_bar_lab.storage.database import RedBarDatabase
from red_bar_lab.ui.strategy_option_context import build_option_behaviour_snapshot


def _value(value: Any, fallback: str = "—") -> Any:
    return fallback if value in (None, "") else value


def _price(value: float | None) -> str:
    return "—" if value is None else f"{value:,.2f}"


def _flag(value: bool | None) -> str:
    if value is None:
        return "WAITING"
    return "YES" if value else "NO"


def _ratio(value: Any) -> str:
    try:
        return "—" if value in (None, "") else f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "—"


def _rsi_position(value: float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value >= 70.0:
        return "OVERBOUGHT / BULLISH THRESHOLD PASSED"
    if value > 55.0:
        return "BULLISH THRESHOLD PASSED (>55)"
    if value < 30.0:
        return "OVERSOLD / BEARISH THRESHOLD PASSED"
    if value < 45.0:
        return "BEARISH THRESHOLD PASSED (<45)"
    return "NEUTRAL STRATEGY ZONE (45–55)"


def _vwap_position(close: float | None, vwap: float | None) -> str:
    if close is None or vwap is None:
        return "UNAVAILABLE"
    if close > vwap:
        return "ABOVE VWAP"
    if close < vwap:
        return "BELOW VWAP"
    return "AT VWAP"


def _vwap_gap(close: float | None, vwap: float | None) -> tuple[str, str]:
    if close is None or vwap is None:
        return "—", "—"
    points = float(close) - float(vwap)
    percentage = (points / float(vwap) * 100.0) if float(vwap) else 0.0
    return f"{points:+,.2f}", f"{percentage:+.3f}%"


def _rsi_vwap_context(snapshot: RedBarV2UISnapshot) -> str:
    if (
        snapshot.index_rsi is None
        or snapshot.futures_close is None
        or snapshot.futures_vwap is None
    ):
        return "UNAVAILABLE"
    rsi_bullish = snapshot.index_rsi > 55.0
    rsi_bearish = snapshot.index_rsi < 45.0
    futures_above_vwap = snapshot.futures_close > snapshot.futures_vwap
    futures_below_vwap = snapshot.futures_close < snapshot.futures_vwap
    if rsi_bullish and futures_above_vwap:
        return "BULLISH CONTEXT"
    if rsi_bearish and futures_below_vwap:
        return "BEARISH CONTEXT"
    if 45.0 <= snapshot.index_rsi <= 55.0:
        return "NEUTRAL RSI / VWAP CONTEXT ONLY"
    return "MIXED CONTEXT"


def _number(row: Mapping[str, Any], field: str) -> float | None:
    value = row.get(field)
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _exit_level(row: Mapping[str, Any]) -> str:
    current = _number(row, "current_price")
    stop = _number(row, "stop_price")
    target1 = _number(row, "target1_price")
    target2 = _number(row, "target2_price")
    if current is None:
        return "WAITING FOR PRICE"
    if stop is not None and current <= stop:
        return "AT / BELOW STOP"
    if target2 is not None and current >= target2:
        return "TARGET 2 REACHED"
    if target1 is not None and current >= target1:
        return "TARGET 1 REACHED"
    entry = _number(row, "entry_price")
    if entry is not None and current >= entry:
        return "PROFIT ZONE"
    return "BETWEEN ENTRY AND STOP"


def _exit_progress_rows(open_orders: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for order in open_orders:
        entry = _number(order, "entry_price")
        current = _number(order, "current_price")
        pnl_pct = (
            ((current - entry) / entry * 100.0)
            if entry not in (None, 0.0) and current is not None
            else None
        )
        rows.append({
            "Trade": _value(order.get("tradingsymbol")),
            "Source": _value(order.get("execution_strategy_source")),
            "Entry": _price(entry),
            "Current": _price(current),
            "Stop": _price(_number(order, "stop_price")),
            "Target 1": _price(_number(order, "target1_price")),
            "Target 2": _price(_number(order, "target2_price")),
            "Current level": _exit_level(order),
            "Move %": "—" if pnl_pct is None else f"{pnl_pct:+.2f}%",
            "Unrealized P&L": _price(_number(order, "unrealized_pnl")),
            "MFE": _price(_number(order, "mfe_points")),
            "MAE": _price(_number(order, "mae_points")),
            "Exit mode": _value(order.get("exit_mode")),
        })
    return rows


def _load_open_orders() -> list[dict[str, Any]]:
    try:
        settings = RedBarSettings.from_env()
        database = RedBarDatabase(settings.database_path)
        database.initialize()
        return list(database.read_open_paper_execution_orders("PAPER-STD"))
    except Exception:
        return []


def _load_option_context() -> dict[str, Any]:
    try:
        settings = RedBarSettings.from_env()
        database = RedBarDatabase(settings.database_path)
        database.initialize()
        return dict(
            build_option_behaviour_snapshot(
                database,
                "NSE_INDEX|Nifty 50",
                date.today().isoformat(),
            )
            or {}
        )
    except Exception:
        return {}


def _diagnostic_value(diagnostics: Any, field: str):
    if diagnostics is None:
        return None
    if isinstance(diagnostics, Mapping):
        return diagnostics.get(field)
    return getattr(diagnostics, field, None)


def _alignment_rows(diagnostics: Any, snapshot: RedBarV2UISnapshot) -> list[dict[str, Any]]:
    reasons = _diagnostic_value(diagnostics, "alignment_blocking_reasons") or ()
    conflicts = _diagnostic_value(diagnostics, "state_conflicts") or ()
    suppressed = _diagnostic_value(diagnostics, "stale_fields_suppressed") or ()
    return [
        {"Alignment input": "Market context ready", "Result": _flag(_diagnostic_value(diagnostics, "market_context_ready"))},
        {"Alignment input": "Volume structure ready", "Result": _flag(_diagnostic_value(diagnostics, "volume_structure_ready"))},
        {"Alignment input": "Options context ready", "Result": _flag(_diagnostic_value(diagnostics, "options_context_ready"))},
        {"Alignment input": "NEXT_RED_CANDLE reference found", "Result": _flag(_diagnostic_value(diagnostics, "reference_found"))},
        {"Alignment input": "Reference data quality", "Result": _value(_diagnostic_value(diagnostics, "reference_data_quality"), "UNKNOWN")},
        {"Alignment input": "Final alignment", "Result": snapshot.alignment_status},
        {"Alignment input": "Blocking reason", "Result": ", ".join(reasons) or "NONE"},
        {"Alignment input": "Snapshot state coherent", "Result": _flag(_diagnostic_value(diagnostics, "state_coherent"))},
        {"Alignment input": "State conflict", "Result": ", ".join(conflicts) or "NONE"},
        {"Alignment input": "Suppressed stale fields", "Result": ", ".join(suppressed) or "NONE"},
    ]


def render_red_bar_v2_legacy_panel(
    st,
    snapshot: RedBarV2UISnapshot | None,
    open_orders: Iterable[Mapping[str, Any]] | None = None,
    option_context: Mapping[str, Any] | None = None,
    runtime_diagnostics: Any | None = None,
) -> None:
    st.markdown("### 4. Red Bar V2 Live State")
    st.caption(
        "Persisted strategy values: RSI, prices, VWAP, reference geometry, direction, "
        "admission and trade state. UI-derived observations: RSI threshold position, "
        "futures VWAP gap/context, option freshness and OI-positioning interpretation."
    )

    if snapshot is None:
        st.warning(
            "No Red Bar V2 UI snapshot is available yet. Run the V2 shadow/live "
            "evaluation cycle to publish the first snapshot."
        )
        return

    engine, mode, scope, alignment = st.columns(4)
    engine.metric("Red Bar engine", snapshot.strategy_version)
    mode.metric("V2 mode", snapshot.mode)
    scope.metric("Execution scope", snapshot.execution_scope)
    alignment.metric("Data alignment", snapshot.alignment_status)

    st.markdown("#### Alignment inputs and blockers")
    st.dataframe(_alignment_rows(runtime_diagnostics, snapshot), width="stretch", hide_index=True)
    conflicts = _diagnostic_value(runtime_diagnostics, "state_conflicts") or ()
    if conflicts:
        st.warning(
            "STATE MISALIGNED: the current reference, strategy lifecycle and trade state "
            "do not form one coherent Red Bar V2 snapshot. Strategy-dependent stale "
            f"fields were suppressed. Conflicts: {', '.join(conflicts)}"
        )
    st.caption(
        "Option freshness is shown separately as an advisory observation. It does not "
        "silently change the persisted pipeline options_context_ready flag."
    )

    st.markdown("#### Reference and market inputs")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Reference status", snapshot.reference_status)
    r2.metric("Reference high", _price(snapshot.reference_high))
    r3.metric("Reference low", _price(snapshot.reference_low))
    r4.metric("Reference midpoint", _price(snapshot.reference_midpoint))

    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Index close", _price(snapshot.index_close))
    i2.metric("Index RSI", _price(snapshot.index_rsi))
    i3.metric("Futures close", _price(snapshot.futures_close))
    i4.metric("Futures VWAP", _price(snapshot.futures_vwap))
    st.caption("RSI source: NIFTY INDEX · VWAP source: CURRENT-MONTH NIFTY FUTURES")

    st.markdown("#### RSI, futures VWAP and option positioning")
    gap_points, gap_percentage = _vwap_gap(snapshot.futures_close, snapshot.futures_vwap)
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("RSI strategy position", _rsi_position(snapshot.index_rsi))
    p2.metric("Futures vs VWAP", _vwap_position(snapshot.futures_close, snapshot.futures_vwap))
    p3.metric("VWAP gap", gap_points)
    p4.metric("RSI + futures VWAP context", _rsi_vwap_context(snapshot))

    option_context = dict(option_context or _load_option_context())
    o1, o2, o3, o4 = st.columns(4)
    o1.metric("PCR (OI)", _ratio(option_context.get("pcr")))
    o2.metric("OI positioning", _value(option_context.get("directional_bias"), "UNAVAILABLE"))
    o3.metric("Option snapshot", _value(option_context.get("status"), "NOT READY"))
    o4.metric("Option freshness", _value(option_context.get("freshness"), "UNKNOWN"))
    st.caption(
        f"Futures-to-VWAP percentage gap: {gap_percentage}. This is market context only; "
        "it does not imply Red Bar admission, confirmation, contract eligibility or trade approval."
    )

    st.markdown("##### OI positioning evidence")
    oi_rows = [
        {"Evidence": "Call OI", "Value": _value(option_context.get("call_oi")), "Interpretation": "Aggregate open interest"},
        {"Evidence": "Put OI", "Value": _value(option_context.get("put_oi")), "Interpretation": "Aggregate open interest"},
        {"Evidence": "Call change in OI", "Value": _value(option_context.get("call_change_oi")), "Interpretation": "Addition if positive; unwinding if negative"},
        {"Evidence": "Put change in OI", "Value": _value(option_context.get("put_change_oi")), "Interpretation": "Addition if positive; unwinding if negative"},
        {"Evidence": "Bullish evidence count", "Value": _value(option_context.get("bullish_evidence_count")), "Interpretation": "Put addition / call unwinding"},
        {"Evidence": "Bearish evidence count", "Value": _value(option_context.get("bearish_evidence_count")), "Interpretation": "Call addition / put unwinding"},
        {"Evidence": "Final result", "Value": _value(option_context.get("directional_bias"), "UNAVAILABLE"), "Interpretation": "Binary count-based supporting evidence"},
    ]
    st.dataframe(oi_rows, width="stretch", hide_index=True)

    st.markdown("#### Direction, reversal and midpoint")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Directional state", snapshot.directional_state)
    d2.metric("Direction", _value(snapshot.direction))
    d3.metric("Option side", _value(snapshot.option_side))
    d4.metric("Trend strength", _value(snapshot.trend_strength))

    m1, m2, m3 = st.columns(3)
    m1.metric("Reversal status", snapshot.reversal_status)
    m2.metric("Provisional / confirmed", snapshot.provisional_confirmed_state)
    m3.metric("Midpoint confirmation", snapshot.midpoint_confirmation)

    st.markdown("#### Trade and admission")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Trade status", snapshot.trade_status)
    t2.metric("Trade ID", _value(snapshot.trade_id))
    t3.metric("Admission result", _flag(snapshot.admission_allowed))
    t4.metric("Admission code", _value(snapshot.admission_code))
    st.write(f"**Admission reason:** {_value(snapshot.admission_reason, 'No admission decision published.')}")

    st.markdown("#### Open trade exit-policy progress")
    active_orders = list(open_orders) if open_orders is not None else _load_open_orders()
    progress = _exit_progress_rows(active_orders)
    if progress:
        st.dataframe(progress, width="stretch", hide_index=True)
        st.caption(
            "Current level is descriptive only. The existing paper exit engine remains "
            "the authority for stop, target, trailing, confirmed reversal, time and EOD exits."
        )
    else:
        st.caption("No open paper trade is currently being monitored.")

    with st.expander("View V2 source and timestamp details"):
        rows = [
            {"field": "Correlation ID", "value": _value(snapshot.correlation_id)},
            {"field": "Runtime source", "value": _value(_diagnostic_value(runtime_diagnostics, "source_status"))},
            {"field": "Reference type", "value": _value(_diagnostic_value(runtime_diagnostics, "reference_level_type"), "NEXT_RED_CANDLE")},
            {"field": "Reference timestamp", "value": _value(snapshot.reference_timestamp)},
            {"field": "Index timestamp", "value": _value(snapshot.index_timestamp)},
            {"field": "Futures timestamp", "value": _value(snapshot.futures_timestamp)},
            {"field": "Last V2 evaluation", "value": _value(snapshot.last_evaluation_timestamp)},
            {"field": "Snapshot recorded", "value": _value(snapshot.recorded_at)},
            {"field": "Session completeness", "value": snapshot.session_completeness},
            {"field": "Futures instrument", "value": _value(snapshot.futures_instrument_key)},
            {"field": "Futures symbol", "value": _value(snapshot.futures_symbol)},
            {"field": "Futures expiry", "value": _value(snapshot.futures_expiry)},
            {"field": "Midpoint aligned", "value": _flag(snapshot.midpoint_aligned)},
            {"field": "PCR (OI)", "value": _ratio(option_context.get("pcr"))},
            {"field": "OI positioning", "value": _value(option_context.get("directional_bias"), "UNAVAILABLE")},
            {"field": "Option snapshot timestamp", "value": _value(option_context.get("latest_timestamp"))},
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
