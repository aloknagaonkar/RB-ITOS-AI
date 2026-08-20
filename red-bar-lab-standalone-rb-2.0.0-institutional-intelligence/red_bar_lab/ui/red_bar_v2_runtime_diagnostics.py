from __future__ import annotations

from typing import Any, Mapping


_NOT_AVAILABLE = "—"


def _value(value: object) -> object:
    return _NOT_AVAILABLE if value in (None, "") else value


def _flag(value: object) -> str:
    if value is None:
        return "UNAVAILABLE"
    return "READY" if bool(value) else "NOT READY"


def render_red_bar_v2_runtime_diagnostics(st: Any, diagnostics: Mapping[str, object]) -> None:
    """Render the current-day persisted runtime trace below the legacy V2 card."""
    status = str(diagnostics.get("source_status") or "UNAVAILABLE")
    st.markdown("#### Current-day V2 runtime diagnostics")
    st.caption(
        "Read-only database trace. This panel does not recalculate indicators or "
        "change signal, committee, entry, or exit decisions."
    )

    if status != "CURRENT_DAY_RUNTIME":
        st.warning(f"Current-day V2 runtime evidence is unavailable: {status}")
        return

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Signal ID", _value(diagnostics.get("signal_id")))
    a2.metric("Confirmation time", _value(diagnostics.get("confirmation_timestamp")))
    a3.metric("Signal age", (
        f"{float(diagnostics['signal_age_seconds']):.1f}s"
        if diagnostics.get("signal_age_seconds") is not None
        else _NOT_AVAILABLE
    ))
    a4.metric("Committee decision", _value(diagnostics.get("committee_decision")))

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Market context", _flag(diagnostics.get("market_context_ready")))
    r2.metric("Volume structure", _flag(diagnostics.get("volume_structure_ready")))
    r3.metric("Options context", _flag(diagnostics.get("options_context_ready")))
    r4.metric("Core / hybrid", (
        f"{_flag(diagnostics.get('core_eligible'))} / {_flag(diagnostics.get('hybrid_eligible'))}"
    ))

    st.write(
        {
            "Candidate": _value(diagnostics.get("candidate_symbol")),
            "Candidate score": _value(diagnostics.get("candidate_score")),
            "Committee reason": _value(diagnostics.get("committee_reason")),
            "Terminal condition": _value(diagnostics.get("terminal_condition")),
            "Monitor state": _value(diagnostics.get("monitor_state")),
            "Monitor heartbeat": _value(diagnostics.get("monitor_heartbeat")),
            "Pipeline updated": _value(diagnostics.get("pipeline_updated_at")),
            "Trading date": _value(diagnostics.get("trading_date")),
        }
    )


__all__ = ["render_red_bar_v2_runtime_diagnostics"]
