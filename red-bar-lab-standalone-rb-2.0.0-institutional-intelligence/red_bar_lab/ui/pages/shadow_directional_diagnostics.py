from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.ui._shared import *
from red_bar_lab.services.shadow_directional_store import ShadowDirectionalStore
from red_bar_lab.services.shadow_directional_observation import (
    ShadowDirectionalObservationService,
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
    if result["timestamp"].dt.tz is None:
        cutoff = latest_complete.replace(tzinfo=None)
    else:
        cutoff = pd.Timestamp(latest_complete)
    # Candle timestamps are bucket starts; exclude the bucket still forming.
    return result[result["timestamp"] < cutoff].reset_index(drop=True)


def _store(layout, instrument_key: str) -> ShadowDirectionalStore:
    safe = layout._safe_instrument(instrument_key)
    path = layout.settings.runs_root / "shadow_directional" / f"{safe}.jsonl"
    return ShadowDirectionalStore(path)


def _summary_rows(rows):
    return [{
        "Candle": row.get("candle_timestamp") or row.get("timestamp"),
        "Direction": row.get("direction"),
        "Transition": row.get("transition_type"),
        "Decision": row.get("decision"),
        "Confidence": row.get("confidence"),
        "Bullish": row.get("bullish_score"),
        "Bearish": row.get("bearish_score"),
        "Regime": row.get("regime"),
        "Red Bar": row.get("red_bar_support"),
        "Execution": "BLOCKED",
    } for row in rows]


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Shadow Directional Transition")
    st.markdown(
        _decision_badge_html(
            "SPRINT 4.2 · OBSERVATION ONLY · EXECUTION IMPACT = NONE",
            "shadow",
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Independent 5-minute directional-transition opinion using structure, "
        "EMA slope/acceleration, DMI, ADX, ATR displacement and regime. "
        "Red Bar is supporting evidence only and contributes zero score."
    )

    selected_date = st.date_input(
        "Trading date",
        value=date.today(),
        key="shadow_directional_date",
    )
    persist = st.toggle(
        "Persist observation",
        value=True,
        help="Stores one shadow decision per completed 5-minute candle. It never writes to execution tables.",
    )

    c1, c2 = st.columns([1, 2])
    evaluate = c1.button(
        "Evaluate latest completed 5m candle",
        type="primary",
        use_container_width=True,
    )
    c2.info("Execution is permanently blocked for every Sprint 4.2 record.")

    store = _store(layout, instrument_key)

    if evaluate:
        try:
            historical = _historical_service(token, layout)
            frame = historical.read_day(
                instrument_key,
                selected_date,
                interval_minutes=5,
            )
            completed = _completed_five_minute_rows(frame)
            if completed.empty:
                st.warning("No completed 5-minute candles are available for this date.")
            elif len(completed) < 35:
                st.warning(
                    f"Only {len(completed)} completed candles are available. "
                    "At least 35 are needed for stable EMA30, ATR and ADX features."
                )
            else:
                service = ShadowDirectionalObservationService(store)
                record, inserted = service.evaluate_and_store(
                    instrument_key=instrument_key,
                    completed_five_minute_candles=completed,
                ) if persist else (
                    {
                        **service.engine.evaluate(completed).as_record(),
                        "instrument_key": instrument_key,
                        "candle_timestamp": str(completed.iloc[-1]["timestamp"]),
                        "execution_allowed": False,
                    },
                    False,
                )
                st.session_state["latest_shadow_directional"] = record
                if persist:
                    if inserted:
                        st.success("Shadow observation stored.")
                    else:
                        st.info("This completed candle was already evaluated; duplicate storage skipped.")
        except MissingAccessToken:
            st.warning("Enter or configure the Upstox access token to evaluate live/historical candles.")
        except Exception as exc:
            st.error(f"Shadow evaluation failed: {type(exc).__name__}: {exc}")

    latest = st.session_state.get("latest_shadow_directional")
    if latest is None:
        stored = store.latest(instrument_key=instrument_key, limit=1)
        latest = stored[0] if stored else None

    if latest:
        st.markdown("#### Latest Shadow Opinion")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Direction", str(latest.get("direction") or "—"))
        m2.metric("Transition", str(latest.get("transition_type") or "—"))
        m3.metric("Confidence", f"{float(latest.get('confidence') or 0.0):.1f}")
        m4.metric("Regime", str(latest.get("regime") or "—"))
        m5.metric("Execution", "BLOCKED")

        s1, s2, s3 = st.columns(3)
        s1.metric("Bullish Score", f"{float(latest.get('bullish_score') or 0.0):.1f}")
        s2.metric("Bearish Score", f"{float(latest.get('bearish_score') or 0.0):.1f}")
        s3.metric("Red Bar Support", str(latest.get("red_bar_support") or "NOT_AVAILABLE"))

        evidence = latest.get("evidence") or []
        if isinstance(evidence, str):
            evidence_text = evidence
        else:
            evidence_text = "\n".join(f"• {item}" for item in evidence)
        st.markdown("#### Evidence")
        st.code(evidence_text or "No directional evidence.", language=None)

        invalidation = latest.get("invalidation_reason")
        if invalidation:
            st.warning(f"Invalidation / caution: {invalidation}")

        st.markdown("#### Full Audit Record")
        st.dataframe(
            _arrow_safe_rows([latest]),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No Shadow Directional observation is available yet.")

    st.markdown("#### Recent Shadow History")
    history = store.latest(instrument_key=instrument_key, limit=100)
    if history:
        st.dataframe(
            _arrow_safe_rows(_summary_rows(history)),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No persisted observations.")

    st.caption(
        "This page is diagnostics only. It cannot create candidates, call the "
        "Committee, enter paper trades, enter live trades, or modify exits."
    )
