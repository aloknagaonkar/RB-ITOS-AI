from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot


_NOT_AVAILABLE = "—"


def _value(value: object) -> object:
    return _NOT_AVAILABLE if value in (None, "") else value


def _number(value: object, digits: int = 2) -> str:
    if value in (None, ""):
        return _NOT_AVAILABLE
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return _NOT_AVAILABLE


def _percent_gap(value: object, reference: object) -> float | None:
    try:
        current = float(value)
        base = float(reference)
    except (TypeError, ValueError):
        return None
    if base == 0.0:
        return None
    return (current - base) / base * 100.0


def _position(value: object, reference: object, label: str = "VWAP") -> str:
    try:
        current = float(value)
        base = float(reference)
    except (TypeError, ValueError):
        return "UNAVAILABLE"
    if current > base:
        return f"ABOVE {label}"
    if current < base:
        return f"BELOW {label}"
    return f"AT {label}"


def _rsi_position(value: object) -> str:
    try:
        rsi = float(value)
    except (TypeError, ValueError):
        return "UNAVAILABLE"
    if rsi >= 70.0:
        return "OVERBOUGHT"
    if rsi >= 50.0:
        return "ABOVE 50"
    if rsi <= 30.0:
        return "OVERSOLD"
    return "BELOW 50"


def _flatten_json(row: Mapping[str, object]) -> dict[str, object]:
    flattened = dict(row)
    for key, value in list(row.items()):
        if not isinstance(value, str) or not value.strip().startswith(("{", "[")):
            continue
        try:
            payload = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping):
            for nested_key, nested_value in payload.items():
                flattened.setdefault(str(nested_key), nested_value)
    return flattened


def _first(row: Mapping[str, object], names: tuple[str, ...]) -> object:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _read_candidate_metrics(
    database: Any,
    *,
    candidate_symbol: str | None,
    trading_date: str | None,
) -> dict[str, object]:
    """Best-effort read of already-persisted candidate metrics.

    Schema discovery keeps this UI compatible with historical databases. It never
    writes, calls a provider, or recalculates an indicator.
    """
    path = getattr(database, "path", None)
    if not path or not candidate_symbol:
        return {}

    priority_tables = (
        "candidate_lifecycle",
        "option_context_snapshots",
        "option_chain_snapshots",
        "option_telemetry_snapshots",
        "paper_signal_diagnostics",
    )
    symbol_columns = ("candidate_symbol", "tradingsymbol", "trading_symbol", "symbol", "contract_symbol")
    date_columns = ("trading_date", "session_date", "trade_date")
    time_columns = ("updated_at", "observed_timestamp", "timestamp", "created_at", "id")

    merged: dict[str, object] = {}
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            existing = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in priority_tables:
                if table not in existing:
                    continue
                columns = [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]
                symbol_column = next((name for name in symbol_columns if name in columns), None)
                if symbol_column is None:
                    continue
                date_column = next((name for name in date_columns if name in columns), None)
                order_column = next((name for name in time_columns if name in columns), None)
                where = [f'"{symbol_column}" = ?']
                params: list[object] = [candidate_symbol]
                if trading_date and date_column:
                    where.append(f'"{date_column}" = ?')
                    params.append(trading_date)
                query = f'SELECT * FROM "{table}" WHERE ' + " AND ".join(where)
                if order_column:
                    query += f' ORDER BY "{order_column}" DESC'
                query += " LIMIT 1"
                row = conn.execute(query, tuple(params)).fetchone()
                if row is not None:
                    for key, value in _flatten_json(dict(row)).items():
                        if value not in (None, ""):
                            merged.setdefault(str(key), value)
    except (sqlite3.Error, OSError):
        return {}
    return merged


def build_pre_trade_full_card(
    database: Any,
    snapshot: RedBarV2UISnapshot,
    diagnostics: Mapping[str, object],
) -> dict[str, object]:
    candidate = str(diagnostics.get("candidate_symbol") or "") or None
    metrics = _read_candidate_metrics(
        database,
        candidate_symbol=candidate,
        trading_date=str(diagnostics.get("trading_date") or "") or None,
    )
    decision = str(diagnostics.get("committee_decision") or snapshot.admission_code or "WAITING").upper()
    if decision in {"APPROVE", "APPROVED", "OPEN", "EXECUTE", "EXECUTED", "TAKEN"}:
        trade_status = "TAKEN"
    elif decision in {"WAIT", "REJECT", "REJECTED", "SKIP", "BLOCK", "BLOCKED"}:
        trade_status = "NOT TAKEN"
    else:
        trade_status = "WAITING"

    terminal = diagnostics.get("terminal_condition")
    reason = terminal or diagnostics.get("committee_reason") or snapshot.admission_reason
    option_price = _first(metrics, ("option_price", "current_price", "last_price", "ltp", "close", "premium"))
    option_vwap = _first(metrics, ("option_vwap", "premium_vwap", "vwap"))
    pcr = _first(metrics, ("pcr_oi", "pcr", "put_call_ratio", "oi_pcr"))
    delta = _first(metrics, ("delta", "option_delta"))
    option_vwap_gap = _percent_gap(option_price, option_vwap)

    gates = [
        {
            "Stage": "Reference",
            "Condition": "Current-day first-candle reference",
            "Observed": snapshot.reference_status,
            "Required": "REFERENCE_READY",
            "Status": "PASS" if snapshot.reference_status == "REFERENCE_READY" else "FAIL",
        },
        {
            "Stage": "Pipeline",
            "Condition": "Market context",
            "Observed": diagnostics.get("market_context_ready"),
            "Required": True,
            "Status": "PASS" if diagnostics.get("market_context_ready") is True else "FAIL",
        },
        {
            "Stage": "Pipeline",
            "Condition": "Volume structure",
            "Observed": diagnostics.get("volume_structure_ready"),
            "Required": True,
            "Status": "PASS" if diagnostics.get("volume_structure_ready") is True else "FAIL",
        },
        {
            "Stage": "Pipeline",
            "Condition": "Options context",
            "Observed": diagnostics.get("options_context_ready"),
            "Required": True,
            "Status": "PASS" if diagnostics.get("options_context_ready") is True else "FAIL",
        },
        {
            "Stage": "Candidate",
            "Condition": "Selected option candidate",
            "Observed": candidate or _NOT_AVAILABLE,
            "Required": "AVAILABLE",
            "Status": "PASS" if candidate else "FAIL",
        },
        {
            "Stage": "Committee",
            "Condition": "Execution approval",
            "Observed": decision,
            "Required": "APPROVED",
            "Status": "PASS" if trade_status == "TAKEN" else "FAIL",
        },
    ]

    evidence = [
        {"Metric": "PCR", "Value": _number(pcr, 2), "Position": "PERSISTED CANDIDATE METRIC"},
        {"Metric": "Delta", "Value": _number(delta, 3), "Position": "PERSISTED CANDIDATE METRIC"},
        {
            "Metric": "Option vs VWAP",
            "Value": _position(option_price, option_vwap),
            "Position": _NOT_AVAILABLE if option_vwap_gap is None else f"{option_vwap_gap:+.2f}%",
        },
        {"Metric": "Index RSI", "Value": _number(snapshot.index_rsi, 2), "Position": _rsi_position(snapshot.index_rsi)},
        {
            "Metric": "Futures vs VWAP",
            "Value": _position(snapshot.futures_close, snapshot.futures_vwap),
            "Position": _number(_percent_gap(snapshot.futures_close, snapshot.futures_vwap), 3),
        },
    ]

    return {
        "strategy": snapshot.strategy_version,
        "signal_id": diagnostics.get("signal_id"),
        "trading_date": diagnostics.get("trading_date"),
        "confirmation_timestamp": diagnostics.get("confirmation_timestamp"),
        "evaluation_timestamp": snapshot.last_evaluation_timestamp,
        "direction": snapshot.direction,
        "option_side": snapshot.option_side,
        "candidate": candidate,
        "candidate_score": diagnostics.get("candidate_score"),
        "decision": decision,
        "trade_status": trade_status,
        "reason": reason or "No persisted decision reason is available.",
        "terminal_condition": terminal,
        "pcr": pcr,
        "delta": delta,
        "option_price": option_price,
        "option_vwap": option_vwap,
        "option_vwap_position": _position(option_price, option_vwap),
        "option_vwap_gap_pct": option_vwap_gap,
        "index_rsi": snapshot.index_rsi,
        "index_rsi_position": _rsi_position(snapshot.index_rsi),
        "futures_close": snapshot.futures_close,
        "futures_vwap": snapshot.futures_vwap,
        "futures_vwap_position": _position(snapshot.futures_close, snapshot.futures_vwap),
        "gates": gates,
        "evidence": evidence,
        "monitor_state": diagnostics.get("monitor_state"),
        "monitor_heartbeat": diagnostics.get("monitor_heartbeat"),
        "pipeline_updated_at": diagnostics.get("pipeline_updated_at"),
        "source_status": diagnostics.get("source_status"),
        "authority": "READ-ONLY OBSERVABILITY",
    }


def render_pre_trade_full_card(st: Any, card: Mapping[str, object]) -> None:
    st.markdown("### Pre-Trade Full Card")
    st.caption(
        f"{_value(card.get('candidate'))} · {card.get('trade_status')} · "
        f"{card.get('authority')}"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("PCR", _number(card.get("pcr"), 2))
    c2.metric("Delta", _number(card.get("delta"), 3))
    c3.metric("VWAP", _value(card.get("option_vwap_position")))
    c4.metric("RSI", _number(card.get("index_rsi"), 2))

    status = str(card.get("trade_status") or "WAITING")
    reason = str(card.get("reason") or "No persisted reason")
    if status == "TAKEN":
        st.success(f"TRADE TAKEN · {reason}")
    elif status == "NOT TAKEN":
        st.error(f"TRADE NOT TAKEN · Reason: {reason}")
    else:
        st.warning(f"TRADE WAITING · Reason: {reason}")

    with st.expander("View full pre-trade details"):
        section = st.radio(
            "Pre-Trade Full Card Section",
            ("Overview", "PCR · Delta · VWAP · RSI", "Strategy Conditions", "Candidate & Audit"),
            horizontal=True,
            key="pre_trade_full_card_section",
        )
        if section == "Overview":
            st.write(
                {
                    "Strategy": _value(card.get("strategy")),
                    "Signal ID": _value(card.get("signal_id")),
                    "Direction": _value(card.get("direction")),
                    "Option side": _value(card.get("option_side")),
                    "Selected contract": _value(card.get("candidate")),
                    "Candidate score": _value(card.get("candidate_score")),
                    "Trade result": status,
                    "Decision": _value(card.get("decision")),
                    "Main reason": reason,
                    "Confirmation time": _value(card.get("confirmation_timestamp")),
                    "Evaluation time": _value(card.get("evaluation_timestamp")),
                }
            )
        elif section == "PCR · Delta · VWAP · RSI":
            st.dataframe(card.get("evidence") or [], width="stretch", hide_index=True)
            st.caption(
                "Indicator values are persisted evidence. This card does not recalculate "
                "PCR, Delta, VWAP or RSI and does not promote them into new execution gates."
            )
        elif section == "Strategy Conditions":
            st.dataframe(card.get("gates") or [], width="stretch", hide_index=True)
            st.write(
                {
                    "Committee decision": _value(card.get("decision")),
                    "Persisted reason": reason,
                    "Terminal condition": _value(card.get("terminal_condition")),
                }
            )
        else:
            st.write(
                {
                    "Candidate": _value(card.get("candidate")),
                    "Candidate score": _value(card.get("candidate_score")),
                    "Option price": _number(card.get("option_price"), 2),
                    "Option VWAP": _number(card.get("option_vwap"), 2),
                    "Option VWAP distance": (
                        _NOT_AVAILABLE
                        if card.get("option_vwap_gap_pct") is None
                        else f"{float(card['option_vwap_gap_pct']):+.2f}%"
                    ),
                    "Monitor state": _value(card.get("monitor_state")),
                    "Monitor heartbeat": _value(card.get("monitor_heartbeat")),
                    "Pipeline updated": _value(card.get("pipeline_updated_at")),
                    "Trading date": _value(card.get("trading_date")),
                    "Source status": _value(card.get("source_status")),
                    "Authority": card.get("authority"),
                }
            )


__all__ = ["build_pre_trade_full_card", "render_pre_trade_full_card"]
