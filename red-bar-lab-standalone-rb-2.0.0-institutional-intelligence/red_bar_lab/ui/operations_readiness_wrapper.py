from __future__ import annotations

from datetime import date
from functools import wraps
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from red_bar_lab.operations.service import _readiness_signal_scope
from red_bar_lab.services.evidence_bundle import (
    build_evidence_bundles,
    evidence_bundles_csv,
    evidence_bundles_json,
    persist_evidence_bundles,
)
from red_bar_lab.services.observed_field_coverage import assess_observed_field_coverage
from red_bar_lab.services.operations_readiness_gate import build_operations_readiness_gate
from red_bar_lab.services.operations_readiness_outcomes import (
    build_persistent_operations_outcomes,
)
from red_bar_lab.services.option_chain_window import select_atm_option_chain_window
from red_bar_lab.services.red_bar_v2_reference_readiness import (
    RED_BAR_V2_REFERENCE_TYPE,
)
from red_bar_lab.services.rsi_readiness import assess_rsi_readiness
from red_bar_lab.services.signal_enrichment_outcome_store import (
    persist_signal_enrichment_outcomes,
    read_signal_enrichment_outcomes,
)
from red_bar_lab.ui.operations_readiness_view import build_operations_readiness_view_model


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
        return result.tz_localize("Asia/Kolkata")
    return result.tz_convert("Asia/Kolkata")


def _reference_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "reference_type": str(
            row.get("reference_type") or row.get("level_type") or ""
        ).upper(),
        "reference_timestamp": (
            row.get("reference_timestamp")
            or row.get("timestamp")
            or row.get("candle_timestamp")
        ),
        "reference_high": row.get("reference_high", row.get("high")),
        "reference_low": row.get("reference_low", row.get("low")),
        "reference_midpoint": row.get("reference_midpoint", row.get("midpoint")),
        "data_quality": row.get("data_quality"),
    }


def _references_by_signal(signals, reference_rows) -> dict[str, dict[str, Any]]:
    candidates = []
    for row in reference_rows:
        payload = _reference_payload(row)
        if payload["reference_type"] != RED_BAR_V2_REFERENCE_TYPE:
            continue
        timestamp = _timestamp(payload.get("reference_timestamp"))
        if timestamp is not None:
            candidates.append((timestamp, payload))
    candidates.sort(key=lambda item: item[0])

    resolved = {}
    for signal in signals:
        signal_id = _signal_id(signal)
        confirmation = _timestamp(
            signal.get("confirmation_timestamp")
            or signal.get("confirmed_at")
            or signal.get("signal_timestamp")
        )
        if not signal_id or confirmation is None:
            continue
        eligible = [payload for stamp, payload in candidates if stamp <= confirmation]
        if eligible:
            resolved[signal_id] = eligible[-1]
    return resolved


def _database_path(database: object) -> Path | None:
    for attribute in ("path", "database_path", "_path"):
        value = getattr(database, attribute, None)
        if value not in (None, ""):
            return Path(value)
    return None


def _latest_enrichment_diagnostics(database, confirmed_ids):
    path = _database_path(database)
    if path is None or not path.exists():
        return {}
    try:
        rows = read_signal_enrichment_outcomes(path)
    except Exception:
        return {}

    latest = {}
    for original in rows:
        row = dict(original)
        signal_id = _signal_id(row)
        stage = str(row.get("stage") or "").upper()
        if signal_id not in confirmed_ids or stage not in {"MARKET", "VOLUME"}:
            continue
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        merged = {**payload, **row}
        key = (signal_id, stage)
        previous = latest.get(key)
        if previous is None or str(merged.get("attempt_timestamp") or "") >= str(
            previous.get("attempt_timestamp") or ""
        ):
            latest[key] = merged
    return latest


def _outcomes(
    confirmed_ids,
    rows,
    *,
    ready_predicate,
    missing_code,
    stage,
    diagnostics=None,
):
    by_id = {_signal_id(row): row for row in rows if _signal_id(row)}
    results = []
    for signal_id in sorted(confirmed_ids):
        row = by_id.get(signal_id)
        diagnostic = dict((diagnostics or {}).get((signal_id, stage), {}))
        coverage = assess_observed_field_coverage(stage, row)
        ready = bool(row) and bool(ready_predicate(row)) and coverage.status == "READY"
        diagnostic_status = str(diagnostic.get("status") or "MISSING").upper()
        status = (
            "READY"
            if ready
            else diagnostic_status
            if diagnostic_status in {"FAILED", "STALE", "NOT_APPLICABLE"}
            else "MISSING"
        )
        results.append(
            {
                "signal_id": signal_id,
                "status": status,
                "reason_code": None
                if ready
                else coverage.reason_code
                or diagnostic.get("reason_code")
                or missing_code,
                "input_source": diagnostic.get("input_source"),
                "input_cutoff_timestamp": diagnostic.get("input_cutoff_timestamp"),
                "latest_source_timestamp": diagnostic.get("latest_source_timestamp"),
                "no_lookahead_passed": diagnostic.get("no_lookahead_passed"),
                "fallback_used": bool(diagnostic.get("fallback_used")),
                "row_count": int(diagnostic.get("row_count") or 0),
                "mandatory_present": coverage.mandatory_present,
                "mandatory_expected": coverage.mandatory_expected,
                "mandatory_coverage_pct": coverage.mandatory_coverage_pct,
                "optional_present": coverage.optional_present,
                "optional_expected": coverage.optional_expected,
                "optional_coverage_pct": coverage.optional_coverage_pct,
                "missing_mandatory_fields": coverage.missing_mandatory_fields,
                "missing_optional_fields": coverage.missing_optional_fields,
                "field_coverage_policy_version": coverage.policy_version,
            }
        )
    return results


def _call_optional(database, method_names, *, instrument_key, trading_date):
    for name in method_names:
        method = getattr(database, name, None)
        if not callable(method):
            continue
        for args, kwargs in (
            ((), {"instrument_key": instrument_key, "trading_date": trading_date}),
            ((instrument_key, trading_date), {}),
            ((instrument_key,), {}),
            ((), {}),
        ):
            try:
                return method(*args, **kwargs)
            except TypeError:
                continue
            except Exception:
                return None
    return None


def _rsi_observation(database, signals, *, instrument_key, trading_date):
    observed = _call_optional(
        database,
        ("read_rsi_readiness", "read_latest_rsi_snapshot", "read_rsi_snapshot"),
        instrument_key=instrument_key,
        trading_date=trading_date,
    )
    if isinstance(observed, Mapping):
        return dict(observed)
    if isinstance(observed, (list, tuple)) and observed:
        return dict(observed[-1])

    for signal in reversed(signals):
        value = signal.get("rsi_value", signal.get("rsi", signal.get("rsi_7")))
        timestamp = (
            signal.get("rsi_timestamp")
            or signal.get("source_timestamp")
            or signal.get("confirmation_timestamp")
        )
        if value is not None or timestamp is not None:
            return {
                "rsi_value": value,
                "period": signal.get("rsi_period", 7 if signal.get("rsi_7") is not None else None),
                "candle_count": signal.get("rsi_candle_count"),
                "source_timestamp": timestamp,
            }
    return None


def _option_chain_window(database, option_rows, *, instrument_key, trading_date):
    raw = _call_optional(
        database,
        ("read_latest_option_chain_snapshot", "read_option_chain_rows", "read_option_chain_snapshot"),
        instrument_key=instrument_key,
        trading_date=trading_date,
    )
    if isinstance(raw, pd.DataFrame):
        rows = raw.to_dict("records")
    elif isinstance(raw, Mapping):
        rows = list(raw.get("rows") or raw.get("chain") or ())
    else:
        rows = list(raw or ()) if isinstance(raw, (list, tuple)) else []

    latest_option = dict(option_rows[-1]) if option_rows else {}
    return select_atm_option_chain_window(
        rows,
        spot=latest_option.get("option_spot_price") or latest_option.get("spot"),
        atm_strike=latest_option.get("atm_strike"),
        strikes_each_side=4,
    ).as_dict()


def _persist_artifacts(database, gate, bundles, *, trading_date):
    path = _database_path(database)
    if path is None:
        skipped = {"status": "SKIPPED", "persisted_count": 0, "reason": "DATABASE_PATH_UNAVAILABLE"}
        return skipped, skipped
    attempt = f"{trading_date}T00:00:00+00:00"
    try:
        outcome_ids = persist_signal_enrichment_outcomes(
            path,
            build_persistent_operations_outcomes(gate, attempt_timestamp=attempt),
        )
        outcome_result = {"status": "READY", "persisted_count": len(outcome_ids), "reason": None}
    except Exception as exc:
        outcome_result = {"status": "FAILED", "persisted_count": 0, "reason": f"{type(exc).__name__}: {exc}"}
    try:
        bundle_ids = persist_evidence_bundles(path, bundles)
        bundle_result = {"status": "READY", "persisted_count": len(bundle_ids), "reason": None}
    except Exception as exc:
        bundle_result = {"status": "FAILED", "persisted_count": 0, "reason": f"{type(exc).__name__}: {exc}"}
    return outcome_result, bundle_result


def build_live_operations_readiness_view(
    database,
    *,
    instrument_key: str,
    trading_date: str,
    persist_outcomes: bool = True,
) -> dict[str, Any]:
    all_signals = [dict(row) for row in database.read_signal_attempts(instrument_key, trading_date)]
    scoped_signals, scope_name = _readiness_signal_scope(all_signals)
    confirmed = [dict(row) for row in scoped_signals if row.get("confirmation_timestamp")]
    confirmed_ids = {_signal_id(row) for row in confirmed if _signal_id(row)}

    references = [dict(row) for row in database.read_reference_levels(instrument_key, trading_date)]
    market_rows = [dict(row) for row in database.read_market_context_snapshots(instrument_key, trading_date, trading_date)]
    volume_rows = [dict(row) for row in database.read_volume_structure_snapshots(instrument_key, trading_date, trading_date)]
    option_rows = [dict(row) for row in database.read_option_context_snapshots(instrument_key, trading_date, trading_date)]
    diagnostics = _latest_enrichment_diagnostics(database, confirmed_ids)

    option_by_id = {_signal_id(row): row for row in option_rows if _signal_id(row) in confirmed_ids}
    for signal_id in confirmed_ids - set(option_by_id):
        row = database.read_option_context_by_signal(signal_id)
        if row:
            option_by_id[signal_id] = dict(row)

    market_outcomes = _outcomes(
        confirmed_ids, market_rows, ready_predicate=lambda row: True,
        missing_code="MARKET_CONTEXT_MISSING", stage="MARKET", diagnostics=diagnostics,
    )
    volume_outcomes = _outcomes(
        confirmed_ids, volume_rows, ready_predicate=lambda row: True,
        missing_code="VOLUME_STRUCTURE_MISSING", stage="VOLUME", diagnostics=diagnostics,
    )
    option_outcomes = _outcomes(
        confirmed_ids, list(option_by_id.values()),
        ready_predicate=lambda row: bool(row.get("entry_aligned")),
        missing_code="OPTION_CONTEXT_NOT_ALIGNED", stage="OPTIONS",
    )

    gate = build_operations_readiness_gate(
        confirmed_signals=confirmed,
        references_by_signal=_references_by_signal(confirmed, references),
        market_outcomes=market_outcomes,
        volume_outcomes=volume_outcomes,
        option_outcomes=option_outcomes,
        market_data_blockers=(),
        independent_strategy_blockers=(),
        execution_blockers=("EXECUTION_POLICY_NOT_APPROVED",),
    )
    bundles = build_evidence_bundles(gate)
    if persist_outcomes:
        persistence, bundle_persistence = _persist_artifacts(
            database, gate, bundles, trading_date=trading_date
        )
    else:
        persistence = {"status": "SKIPPED", "persisted_count": 0, "reason": "PERSISTENCE_DISABLED"}
        bundle_persistence = dict(persistence)

    confirmations = [
        stamp for stamp in (_timestamp(row.get("confirmation_timestamp")) for row in confirmed)
        if stamp is not None
    ]
    as_of = (
        pd.Timestamp.now(tz="Asia/Kolkata")
        if trading_date == date.today().isoformat()
        else max(confirmations) if confirmations else f"{trading_date}T15:30:00+05:30"
    )
    rsi = assess_rsi_readiness(
        _rsi_observation(database, all_signals, instrument_key=instrument_key, trading_date=trading_date),
        as_of_timestamp=as_of,
    ).as_dict()

    view = build_operations_readiness_view_model(gate)
    view.update(
        {
            "readiness_scope": scope_name,
            "outcome_persistence": persistence,
            "evidence_bundle_persistence": bundle_persistence,
            "evidence_bundles": tuple(bundle.as_dict() for bundle in bundles),
            "rsi_readiness": rsi,
            "option_chain_window": _option_chain_window(
                database, option_rows, instrument_key=instrument_key, trading_date=trading_date
            ),
        }
    )
    return view


def _stage_metric(column, label, stage):
    column.metric(label, f"{stage.get('ready_count', 0)}/{stage.get('total_count', 0)}", help=f"Status: {stage.get('status', 'UNKNOWN')}")


def render_operations_readiness_v2(database, *, instrument_key: str, trading_date: str) -> None:
    view = build_live_operations_readiness_view(
        database, instrument_key=instrument_key, trading_date=trading_date
    )
    stages = view["stages"]

    st.subheader("Operations Center")
    st.markdown("### Authoritative Signal Readiness v2")
    st.caption(
        "Exact signal-ID readiness, observed field coverage, point-in-time sources, "
        "truthful RSI readiness, and auditable evidence bundles. Observational only."
    )

    columns = st.columns(7)
    _stage_metric(columns[0], "Reference", stages["reference"])
    _stage_metric(columns[1], "Market", stages["market"])
    _stage_metric(columns[2], "Volume", stages["volume"])
    _stage_metric(columns[3], "Options", stages["options"])
    _stage_metric(columns[4], "CORE", stages["core"])
    _stage_metric(columns[5], "HYBRID", stages["hybrid"])
    rsi = view["rsi_readiness"]
    columns[6].metric("RSI(7)", rsi.get("status"), help=rsi.get("reason_code") or "Observed RSI is ready")

    st.dataframe(
        [
            {
                "Readiness domain": name.replace("_", " ").title(),
                "Status": payload.get("status"),
                "Primary reason": payload.get("primary_reason") or "—",
                "All reasons": ", ".join(payload.get("reasons") or ()) or "—",
            }
            for name, payload in view["domains"].items()
        ],
        width="stretch",
        hide_index=True,
    )

    drilldown = list(view.get("drilldown") or ())
    if drilldown:
        st.markdown("#### Per-signal readiness, field coverage and sources")
        st.dataframe(drilldown, width="stretch", hide_index=True)
    else:
        st.info("No confirmed signals are available for the selected session.")

    st.markdown("#### RSI readiness evidence")
    st.dataframe(
        [{
            "Status": rsi.get("status"),
            "RSI": rsi.get("rsi_value"),
            "Period": rsi.get("period"),
            "Candles": rsi.get("candle_count"),
            "Source timestamp": rsi.get("source_timestamp"),
            "Age seconds": rsi.get("age_seconds"),
            "No-lookahead": rsi.get("no_lookahead_passed"),
            "Reason": rsi.get("reason_code") or "—",
        }],
        width="stretch",
        hide_index=True,
    )

    chain = view["option_chain_window"]
    st.markdown("#### Option chain — ATM ±4 strikes")
    if chain.get("status") == "READY":
        st.caption(f"ATM: {chain.get('atm_strike')} · Displayed strikes: {len(chain.get('selected_strikes') or ())}")
        st.dataframe(list(chain.get("rows") or ()), width="stretch", hide_index=True)
    else:
        st.info(f"Option-chain window unavailable: {chain.get('reason_code')}")

    bundles = list(view.get("evidence_bundles") or ())
    st.markdown("#### Per-signal evidence bundles")
    if bundles:
        selected_id = st.selectbox(
            "Evidence bundle",
            options=[bundle["bundle_id"] for bundle in bundles],
            format_func=lambda value: next(
                f"{bundle['signal_id']} · {value}"
                for bundle in bundles if bundle["bundle_id"] == value
            ),
        )
        selected = next(bundle for bundle in bundles if bundle["bundle_id"] == selected_id)
        st.json(selected)
        export_columns = st.columns(2)
        export_columns[0].download_button(
            "Download bundles JSON",
            evidence_bundles_json(bundles),
            file_name=f"operations_evidence_{trading_date}.json",
            mime="application/json",
        )
        export_columns[1].download_button(
            "Download bundles CSV",
            evidence_bundles_csv(bundles),
            file_name=f"operations_evidence_{trading_date}.csv",
            mime="text/csv",
        )
    else:
        st.info("No evidence bundles are available for the selected session.")

    for label, payload in (
        ("Outcome persistence", view.get("outcome_persistence") or {}),
        ("Evidence-bundle persistence", view.get("evidence_bundle_persistence") or {}),
    ):
        message = f"{label}: {payload.get('status', 'UNKNOWN')} · Rows: {payload.get('persisted_count', 0)}"
        if payload.get("reason"):
            message += f" · {payload['reason']}"
        st.warning(message) if payload.get("status") == "FAILED" else st.caption(message)

    st.caption(
        f"Scope: {view.get('readiness_scope')} · Policy: {view.get('policy_version')} · "
        f"Authority: {view.get('authority')}"
    )


def build_operations_readiness_page_wrapper(render_page):
    @wraps(render_page)
    def wrapped(settings, layout, database, token, underlying_name, instrument_key, interval):
        render_operations_readiness_v2(
            database,
            instrument_key=instrument_key,
            trading_date=date.today().isoformat(),
        )
        with st.expander("Legacy Operations Centre diagnostics", expanded=False):
            render_page(
                settings,
                layout,
                database,
                token,
                underlying_name,
                instrument_key,
                interval,
            )

    return wrapped


__all__ = [
    "build_live_operations_readiness_view",
    "build_operations_readiness_page_wrapper",
    "render_operations_readiness_v2",
]
