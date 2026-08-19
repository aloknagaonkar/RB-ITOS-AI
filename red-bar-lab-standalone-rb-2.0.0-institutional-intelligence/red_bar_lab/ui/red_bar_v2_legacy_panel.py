from __future__ import annotations

from typing import Any

from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot


def _value(value: Any, fallback: str = "—") -> Any:
    return fallback if value in (None, "") else value


def _price(value: float | None) -> str:
    return "—" if value is None else f"{value:,.2f}"


def _flag(value: bool | None) -> str:
    if value is None:
        return "WAITING"
    return "YES" if value else "NO"


def render_red_bar_v2_legacy_panel(st, snapshot: RedBarV2UISnapshot | None) -> None:
    st.markdown("### 4. Red Bar V2 Live State")
    st.caption(
        "Read-only Red Bar V2 observability. Values come from the persisted V2 "
        "strategy snapshot; this page does not recalculate RSI, VWAP, midpoint, "
        "direction, admission or trade state."
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

    with st.expander("View V2 source and timestamp details"):
        rows = [
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
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
