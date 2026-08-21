from __future__ import annotations

from datetime import date
from functools import wraps
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from red_bar_lab.operations.service import _readiness_signal_scope
from red_bar_lab.services.operations_readiness_gate import (
    build_operations_readiness_gate,
)
from red_bar_lab.services.operations_readiness_outcomes import (
    build_persistent_operations_outcomes,
)
from red_bar_lab.services.red_bar_v2_reference_readiness import (
    RED_BAR_V2_REFERENCE_TYPE,
)
from red_bar_lab.services.signal_enrichment_outcome_store import (
    persist_signal_enrichment_outcomes,
)
from red_bar_lab.ui.operations_readiness_view import (
    build_operations_readiness_view_model,
)


def _signal_id(row: Mapping[str, Any]) -> str:
    return str(row.get("signal_id") or "").strip()


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if result.tzinfo is None:
        result = result.tz_localize("Asia/Kolkata")
    else:
        result = result.tz_convert("Asia/Kolkata")
    return result


def _reference_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "reference_type": str(
            row.get("reference_type")
            or row.get("level_type")
            or ""
        ).upper(),
        "reference_timestamp": (
            row.get("reference_timestamp")
            or row.get("timestamp")
            or row.get("candle_timestamp")
        ),
        "reference_high": (
            row.get("reference_high")
            if "reference_high" in row
            else row.get("high")
        ),
        "reference_low": (
            row.get("reference_low")
            if "reference_low" in row
            else row.get("low")
        ),
        "reference_midpoint": (
            row.get("reference_midpoint")
            if "reference_midpoint" in row
            else row.get("midpoint")
        ),
        "data_quality": row.get("data_quality") or "VALID",
    }


def _references_by_signal(
    signals: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    candidates = []
    for row in reference_rows:
        payload = _reference_payload(row)
        if payload["reference_type"] != RED_BAR_V2_REFERENCE_TYPE:
            continue
        timestamp = _timestamp(payload.get("reference_timestamp"))
        if timestamp is not None:
            candidates.append((timestamp, payload))
    candidates.sort(key=lambda item: item[0])

    resolved: dict[str, dict[str, Any]] = {}
    for signal in signals:
        signal_id = _signal_id(signal)
        confirmation = _timestamp(
            signal.get("confirmation_timestamp")
            or signal.get("confirmed_at")
            or signal.get("signal_timestamp")
        )
        if not signal_id or confirmation is None:
            continue
        eligible = [payload for ts, payload in candidates if ts <= confirmation]
        if eligible:
            resolved[signal_id] = eligible[-1]
    return resolved


def _outcomes(
    confirmed_ids: set[str],
    rows: list[dict[str, Any]],
    *,
    ready_predicate,
    missing_code: str,
) -> list[dict[str, Any]]:
    by_id = {_signal_id(row): row for row in rows if _signal_id(row)}
    results = []
    for signal_id in sorted(confirmed_ids):
        row = by_id.get(signal_id)
        ready = bool(row) and bool(ready_predicate(row))
        results.append(
            {
                "signal_id": signal_id,
                "status": "READY" if ready else "MISSING",
                "reason_code": None if ready else missing_code,
            }
        )
    return results


def _database_path(database: object) -> Path | None:
    for attribute in ("path", "database_path", "_path"):
        value = getattr(database, attribute, None)
        if value not in (None, ""):
            return Path(value)
    return None


def _persistence_attempt_timestamp(trading_date: str) -> str:
    return f"{trading_date}T00:00:00+00:00"


def _persist_readiness_outcomes(
    database: object,
    gate: Mapping[str, Any],
    *,
    trading_date: str,
) -> dict[str, Any]:
    path = _database_path(database)
    if path is None:
        return {
            "status": "SKIPPED",
            "persisted_count": 0,
            "reason": "DATABASE_PATH_UNAVAILABLE",
        }

    try:
        outcomes = build_persistent_operations_outcomes(
            gate,
            attempt_timestamp=_persistence_attempt_timestamp(trading_date),
        )
        outcome_ids = persist_signal_enrichment_outcomes(path, outcomes)
        return {
            "status": "READY",
            "persisted_count": len(outcome_ids),
            "reason": None,
        }
    except Exception as exc:  # UI persistence must never block diagnostics.
        return {
            "status": "FAILED",
            "persisted_count": 0,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def build_live_operations_readiness_view(
    database,
    *,
    instrument_key: str,
    trading_date: str,
    persist_outcomes: bool = True,
) -> dict[str, Any]:
    all_signals = database.read_signal_attempts(instrument_key, trading_date)
    scoped_signals, scope_name = _readiness_signal_scope(all_signals)
    confirmed = [
        dict(row)
        for row in scoped_signals
        if row.get("confirmation_timestamp")
    ]
    confirmed_ids = {_signal_id(row) for row in confirmed if _signal_id(row)}

    references = database.read_reference_levels(instrument_key, trading_date)
    market_rows = database.read_market_context_snapshots(
        instrument_key, trading_date, trading_date
    )
    volume_rows = database.read_volume_structure_snapshots(
        instrument_key, trading_date, trading_date
    )
    option_rows = database.read_option_context_snapshots(
        instrument_key, trading_date, trading_date
    )

    option_by_id = {
        _signal_id(row): row
        for row in option_rows
        if _signal_id(row) in confirmed_ids
    }
    for signal_id in confirmed_ids - set(option_by_id):
        row = database.read_option_context_by_signal(signal_id)
        if row:
            option_by_id[signal_id] = row

    market_outcomes = _outcomes(
        confirmed_ids,
        [dict(row) for row in market_rows],
        ready_predicate=lambda row: True,
        missing_code="MARKET_CONTEXT_MISSING",
    )
    volume_outcomes = _outcomes(
        confirmed_ids,
        [dict(row) for row in volume_rows],
        ready_predicate=lambda row: True,
        missing_code="VOLUME_STRUCTURE_MISSING",
    )
    option_outcomes = _outcomes(
        confirmed_ids,
        list(option_by_id.values()),
        ready_predicate=lambda row: bool(row.get("entry_aligned")),
        missing_code="OPTION_CONTEXT_NOT_ALIGNED",
    )

    gate = build_operations_readiness_gate(
        confirmed_signals=confirmed,
        references_by_signal=_references_by_signal(
            confirmed, [dict(row) for row in references]
        ),
        market_outcomes=market_outcomes,
        volume_outcomes=volume_outcomes,
        option_outcomes=option_outcomes,
        market_data_blockers=(),
        independent_strategy_blockers=(),
        execution_blockers=("EXECUTION_POLICY_NOT_APPROVED",),
    )
    persistence = (
        _persist_readiness_outcomes(database, gate, trading_date=trading_date)
        if persist_outcomes
        else {
            "status": "SKIPPED",
            "persisted_count": 0,
            "reason": "PERSISTENCE_DISABLED",
        }
    )
    view = build_operations_readiness_view_model(gate)
    view["readiness_scope"] = scope_name
    view["outcome_persistence"] = persistence
    return view


def _stage_metric(column, label: str, stage: Mapping[str, Any]) -> None:
    column.metric(
        label,
        f"{stage.get('ready_count', 0)}/{stage.get('total_count', 0)}",
        help=f"Status: {stage.get('status', 'UNKNOWN')}",
    )


def render_operations_readiness_v2(
    database,
    *,
    instrument_key: str,
    trading_date: str,
) -> None:
    view = build_live_operations_readiness_view(
        database,
        instrument_key=instrument_key,
        trading_date=trading_date,
    )
    stages = view["stages"]

    st.markdown("### Authoritative Signal Readiness v2")
    st.caption(
        "Exact signal-ID readiness using NEXT_RED_CANDLE validation. "
        "This section supersedes aggregate count approximations above and "
        "remains observational only."
    )

    columns = st.columns(6)
    _stage_metric(columns[0], "Reference", stages["reference"])
    _stage_metric(columns[1], "Market", stages["market"])
    _stage_metric(columns[2], "Volume", stages["volume"])
    _stage_metric(columns[3], "Options", stages["options"])
    _stage_metric(columns[4], "CORE", stages["core"])
    _stage_metric(columns[5], "HYBRID", stages["hybrid"])

    domains = view["domains"]
    domain_rows = []
    for name, payload in domains.items():
        domain_rows.append(
            {
                "Readiness domain": name.replace("_", " ").title(),
                "Status": payload.get("status"),
                "Primary reason": payload.get("primary_reason") or "—",
                "All reasons": ", ".join(payload.get("reasons") or ()) or "—",
            }
        )
    st.dataframe(domain_rows, width="stretch", hide_index=True)

    drilldown = list(view.get("drilldown") or ())
    if drilldown:
        st.markdown("#### Per-signal readiness and blockers")
        st.dataframe(drilldown, width="stretch", hide_index=True)
    else:
        st.info("No confirmed signals are available for the selected session.")

    persistence = view.get("outcome_persistence") or {}
    persistence_status = persistence.get("status") or "UNKNOWN"
    persistence_message = (
        f"Outcome persistence: {persistence_status} · "
        f"Rows: {persistence.get('persisted_count', 0)}"
    )
    if persistence.get("reason"):
        persistence_message += f" · {persistence['reason']}"
    if persistence_status == "FAILED":
        st.warning(persistence_message)
    else:
        st.caption(persistence_message)

    st.caption(
        f"Scope: {view.get('readiness_scope')} · "
        f"Policy: {view.get('policy_version')} · "
        f"Authority: {view.get('authority')}"
    )


def build_operations_readiness_page_wrapper(render_page):
    @wraps(render_page)
    def wrapped(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
    ):
        render_page(
            settings,
            layout,
            database,
            token,
            underlying_name,
            instrument_key,
            interval,
        )
        render_operations_readiness_v2(
            database,
            instrument_key=instrument_key,
            trading_date=date.today().isoformat(),
        )

    return wrapped


__all__ = [
    "build_live_operations_readiness_view",
    "build_operations_readiness_page_wrapper",
    "render_operations_readiness_v2",
]
