from __future__ import annotations

import pandas as pd

from red_bar_lab.services.red_bar_v2_canonical.paper_canary_observability import (
    PaperCanaryRuntimeObservabilityService,
)
from red_bar_lab.ui.canonical_market_data_readiness_panel import (
    render_canonical_market_data_readiness_panel,
)


def _text(value: object | None) -> str:
    if value is None: return "—"
    if hasattr(value, "isoformat"): return value.isoformat()
    return str(value)


def _provider_projection(settings) -> tuple[str, str, str]:
    provider = settings.red_bar_v2_paper_canary_market_data_provider
    if provider in {"ZERODHA", "UPSTOX"}: return provider, "READY", "PROVIDER_SELECTED"
    if provider == "UNCONFIGURED": return provider, "MISSING", "MARKET_DATA_PROVIDER_UNCONFIGURED"
    return provider, "INVALID", "MARKET_DATA_PROVIDER_INVALID"


def _render_paper_canary_runtime(st, settings) -> None:
    st.markdown("### 11. Runtime Health")
    st.warning("PAPER ONLY — this panel is read-only. It cannot start the worker, run recovery, submit an order, reset the circuit or repair state.")
    provider, provider_status, provider_reason = _provider_projection(settings)
    st.dataframe(pd.DataFrame([
        ("Market-data provider", provider),
        ("Provider configuration", provider_status),
        ("Provider status reason", provider_reason),
        ("Latest provider evidence timestamp", "—"),
    ], columns=["Field", "Read-only configuration value"], dtype="string"), hide_index=True, use_container_width=True)
    observation = PaperCanaryRuntimeObservabilityService(settings.paper_canary_state_path).load(
        worker_enabled=settings.red_bar_v2_paper_canary_worker_enabled,
        mode=settings.red_bar_v2_canonical_paper_execution_mode,
    )
    st.metric("Runtime state", observation.status)
    if observation.state is None:
        message = {
            "WORKER_DISABLED": "The independent paper-canary worker is disabled by configuration.",
            "OBSERVE_ONLY": "Canonical paper execution remains observe-only.",
            "CONFIGURATION_INVALID": "Runtime configuration is invalid and entry is fail-closed.",
            "RUNTIME_STATE_CORRUPT": "The durable runtime state failed schema or digest validation.",
            "RUNTIME_STATE_UNAVAILABLE": "No verified runtime state is currently available.",
        }.get(observation.status, "No verified runtime state is available.")
        if observation.status in {"RUNTIME_STATE_CORRUPT", "CONFIGURATION_INVALID"}: st.error(message)
        else: st.info(message)
        return
    state = observation.state
    fields = [
        ("Worker configured", "YES" if settings.red_bar_v2_paper_canary_worker_enabled else "NO"),
        ("Runtime mode", settings.red_bar_v2_canonical_paper_execution_mode),
        ("Runtime authority", "PAPER ONLY"),
        ("Worker status", state.worker_status.value),
        ("Circuit state", state.circuit_state.value),
        ("Entry suspended", "YES" if state.entry_suspended else "NO"),
        ("Recovery allowed", "YES"),
        ("Consecutive failures", str(state.consecutive_failures)),
        ("Healthy recovery cycles", str(state.healthy_probe_cycles)),
        ("Last cycle start", _text(state.last_cycle_started_at)),
        ("Last cycle end", _text(state.last_cycle_completed_at)),
        ("Last successful cycle", _text(state.last_successful_cycle_at)),
        ("Next eligible cycle", _text(state.next_eligible_cycle_at)),
        ("Candidate count", str(state.candidate_count)),
        ("Attempted count", str(state.attempted_count)),
        ("Accepted count", str(state.accepted_count)),
        ("Rejected count", str(state.rejected_count)),
        ("Uncertain count", str(state.uncertain_count)),
        ("Daily action count / limit", f"{state.daily_action_count} / {settings.red_bar_v2_paper_canary_max_actions_per_day}"),
        ("Latest reason code", state.latest_reason_code),
        ("Latest canonical execution ID", _text(state.latest_execution_id)),
        ("Worker-state persistence", state.persistence_status),
        ("Evidence freshness policy", f"≤ {settings.red_bar_v2_paper_canary_max_bundle_age_seconds:g} seconds"),
    ]
    st.dataframe(pd.DataFrame(fields, columns=["Field", "Verified runtime value"], dtype="string"), hide_index=True, use_container_width=True)


def render_canonical_paper_canary_panel(st, settings) -> None:
    _render_paper_canary_runtime(st, settings)
    render_canonical_market_data_readiness_panel(st, settings)
