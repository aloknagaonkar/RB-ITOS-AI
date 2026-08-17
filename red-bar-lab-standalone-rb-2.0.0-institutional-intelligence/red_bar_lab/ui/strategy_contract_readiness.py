from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd
import streamlit as st


_SIDE_PREFIX = {"CE": "call", "PE": "put"}


def _row_value(rows, label: str):
    target = label.strip().lower()
    for row in rows or []:
        item = dict(row)
        name = str(item.get("field") or item.get("check") or "").strip().lower()
        if name == target:
            return item.get("value") or item.get("detail")
    return None


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, "", "Unavailable", "Not created"):
        return None
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("Asia/Kolkata")
    return ts.tz_convert("Asia/Kolkata")


def _bundle_timestamp(resolution: Mapping[str, object] | None) -> pd.Timestamp | None:
    result = dict(resolution or {})
    rows = result.get("bundle_rows") or []
    value = (
        _row_value(rows, "Created at")
        or _row_value(rows, "Detected at")
        or result.get("refreshed_at")
    )
    return _timestamp(value)


def _requested_side(gate: Mapping[str, object]) -> str | None:
    intent = str(gate.get("normalized_intent") or "").upper().strip()
    if intent == "BUY CE":
        return "CE"
    if intent == "BUY PE":
        return "PE"
    return None


def _load_artifact(path_value: object) -> pd.DataFrame:
    if not path_value:
        return pd.DataFrame()
    try:
        path = Path(str(path_value))
        if not path.exists() or not path.is_file():
            return pd.DataFrame()
        if path.suffix.lower() == ".json":
            payload = pd.read_json(path)
            return payload if isinstance(payload, pd.DataFrame) else pd.DataFrame()
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _number(row: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = row.get(name)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not pd.isna(number):
            return number
    return None


def _text(row: Mapping[str, object], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def normalize_contract_rows(
    chain: pd.DataFrame,
    *,
    side: str,
    snapshot_timestamp: object,
    expiry: object = None,
) -> list[dict[str, object]]:
    """Convert a wide call/put chain artifact into strategy-neutral contract rows."""
    prefix = _SIDE_PREFIX[side]
    output: list[dict[str, object]] = []
    for raw in chain.to_dict("records"):
        row = dict(raw)
        strike = _number(row, "strike", "strike_price")
        instrument_key = _text(
            row,
            f"{prefix}_instrument_key",
            f"{prefix}_instrument_token",
            f"{prefix}_tradingsymbol",
            f"{prefix}_trading_symbol",
        )
        symbol = _text(
            row,
            f"{prefix}_tradingsymbol",
            f"{prefix}_trading_symbol",
            f"{prefix}_symbol",
        )
        ltp = _number(row, f"{prefix}_ltp", f"{prefix}_last_price", f"{prefix}_close")
        bid = _number(row, f"{prefix}_bid", f"{prefix}_best_bid")
        ask = _number(row, f"{prefix}_ask", f"{prefix}_best_ask")
        volume = _number(row, f"{prefix}_volume", f"{prefix}_traded_volume")
        oi = _number(row, f"{prefix}_oi", f"{prefix}_open_interest")
        oi_change = _number(row, f"{prefix}_oi_change", f"{prefix}_change_in_oi")
        iv = _number(row, f"{prefix}_iv", f"{prefix}_implied_volatility")
        delta = _number(row, f"{prefix}_delta")
        gamma = _number(row, f"{prefix}_gamma")
        theta = _number(row, f"{prefix}_theta")
        vega = _number(row, f"{prefix}_vega")
        row_expiry = _text(row, f"{prefix}_expiry", "expiry", "option_expiry") or (
            str(expiry) if expiry not in (None, "") else None
        )

        reasons: list[str] = []
        if not instrument_key:
            reasons.append("MISSING_INSTRUMENT_ID")
        if strike is None or strike <= 0:
            reasons.append("INVALID_STRIKE")
        if ltp is None or ltp <= 0:
            reasons.append("MISSING_PRICE")
        if bid is None or ask is None:
            reasons.append("MISSING_BID_ASK")
        elif bid < 0 or ask <= 0 or ask < bid:
            reasons.append("INVALID_BID_ASK")
        if volume is None:
            reasons.append("MISSING_VOLUME")
        if oi is None:
            reasons.append("MISSING_OPEN_INTEREST")

        base_ready = not any(
            reason in {"MISSING_INSTRUMENT_ID", "INVALID_STRIKE", "MISSING_PRICE"}
            for reason in reasons
        )
        liquidity_ready = base_ready and not any(
            reason in {
                "MISSING_BID_ASK",
                "INVALID_BID_ASK",
                "MISSING_VOLUME",
                "MISSING_OPEN_INTEREST",
            }
            for reason in reasons
        )
        spread = ask - bid if bid is not None and ask is not None and ask >= bid else None
        spread_pct = spread / ltp * 100.0 if spread is not None and ltp else None

        output.append(
            {
                "instrument_key": instrument_key or "Unavailable",
                "trading_symbol": symbol or "Unavailable",
                "option_side": side,
                "expiry": row_expiry or "Unavailable",
                "strike": strike,
                "ltp": ltp,
                "bid": bid,
                "ask": ask,
                "spread_points": spread,
                "spread_pct": spread_pct,
                "volume": volume,
                "oi": oi,
                "oi_change": oi_change,
                "iv": iv,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "quote_timestamp": str(snapshot_timestamp or "Unavailable"),
                "base_ready": base_ready,
                "liquidity_ready": liquidity_ready,
                "decision": "READY_FOR_RANKING" if liquidity_ready else "WAIT",
                "reasons": ", ".join(reasons) if reasons else "NONE",
            }
        )
    return output


def _select_snapshot(
    database,
    *,
    instrument_key: str,
    bundle_timestamp: pd.Timestamp,
) -> tuple[dict[str, object] | None, str]:
    source_database = getattr(database, "_database", database)
    trading_date = bundle_timestamp.date().isoformat()
    rows = list(
        source_database.read_option_chain_history(
            instrument_key,
            trading_date,
            trading_date,
            limit=2000,
        )
        or []
    )
    eligible: list[tuple[pd.Timestamp, dict[str, object]]] = []
    for raw in rows:
        row = dict(raw)
        if str(row.get("collector_mode") or "").upper() != "ONLINE":
            continue
        ts = _timestamp(row.get("snapshot_timestamp"))
        if ts is None or ts > bundle_timestamp:
            continue
        eligible.append((ts, row))
    if not eligible:
        return None, "No ONLINE option-chain snapshot exists at or before the bundle timestamp."
    eligible.sort(key=lambda item: item[0])
    return eligible[-1][1], "Nearest ONLINE snapshot at or before the bundle timestamp."


def build_contract_data_readiness(
    *,
    gate: Mapping[str, object],
    resolution: Mapping[str, object] | None,
    database,
    instrument_key: str,
    artifact_loader=_load_artifact,
) -> dict[str, object]:
    """Build Section 5A without ranking, persistence, reservation, or execution."""
    if not bool(gate.get("eligible")):
        return {
            "outcome": "NOT_ELIGIBLE",
            "reason": str(gate.get("blocking_reason") or "Section 4 blocked the bundle."),
            "strategy_owner": str(gate.get("strategy_owner") or "Unavailable"),
            "strategy_id": str(gate.get("strategy_id") or "Unavailable"),
            "signal_id": str(gate.get("signal_id") or "Not created"),
            "bundle_id": str(gate.get("bundle_id") or "Not created"),
            "requested_side": _requested_side(gate) or "Unavailable",
            "bundle_timestamp": "Unavailable",
            "snapshot_timestamp": "Unavailable",
            "snapshot_relation": "UNAVAILABLE",
            "contracts_available": 0,
            "requested_side_contracts": 0,
            "ready_for_ranking": 0,
            "contract_rows": [],
            "checks": [],
            "next_step": "Wait for Section 4 to produce an eligible fresh strategy-owned bundle.",
        }

    side = _requested_side(gate)
    bundle_ts = _bundle_timestamp(resolution)
    if side is None or bundle_ts is None:
        return {
            "outcome": "UNAVAILABLE",
            "reason": "Requested CE/PE side or bundle timestamp is unavailable.",
            "strategy_owner": str(gate.get("strategy_owner") or "Unavailable"),
            "strategy_id": str(gate.get("strategy_id") or "Unavailable"),
            "signal_id": str(gate.get("signal_id") or "Not created"),
            "bundle_id": str(gate.get("bundle_id") or "Not created"),
            "requested_side": side or "Unavailable",
            "bundle_timestamp": str(bundle_ts or "Unavailable"),
            "snapshot_timestamp": "Unavailable",
            "snapshot_relation": "UNAVAILABLE",
            "contracts_available": 0,
            "requested_side_contracts": 0,
            "ready_for_ranking": 0,
            "contract_rows": [],
            "checks": [],
            "next_step": "Restore the strategy-owned bundle identity and timestamp before contract evaluation.",
        }

    snapshot, relation_reason = _select_snapshot(
        database,
        instrument_key=instrument_key,
        bundle_timestamp=bundle_ts,
    )
    if snapshot is None:
        return {
            "outcome": "UNAVAILABLE",
            "reason": relation_reason,
            "strategy_owner": str(gate.get("strategy_owner")),
            "strategy_id": str(gate.get("strategy_id")),
            "signal_id": str(gate.get("signal_id")),
            "bundle_id": str(gate.get("bundle_id")),
            "requested_side": side,
            "bundle_timestamp": bundle_ts.isoformat(),
            "snapshot_timestamp": "Unavailable",
            "snapshot_relation": "UNAVAILABLE",
            "contracts_available": 0,
            "requested_side_contracts": 0,
            "ready_for_ranking": 0,
            "contract_rows": [],
            "checks": [],
            "next_step": "Capture a contract-level ONLINE option snapshot before the bundle freshness window expires.",
        }

    snapshot_ts = _timestamp(snapshot.get("snapshot_timestamp"))
    chain = artifact_loader(snapshot.get("chain_artifact_path"))
    if chain.empty:
        outcome = "UNAVAILABLE"
        reason = "The selected snapshot has no readable contract-level chain artifact."
        contracts: list[dict[str, object]] = []
    else:
        contracts = normalize_contract_rows(
            chain,
            side=side,
            snapshot_timestamp=snapshot_ts,
            expiry=snapshot.get("option_expiry"),
        )
        ready = [row for row in contracts if row["liquidity_ready"]]
        base = [row for row in contracts if row["base_ready"]]
        if ready:
            outcome = "READY_FOR_RANKING"
            reason = "Contract rows contain identity, price, bid/ask, volume and OI required for Section 5B ranking."
        elif base:
            outcome = "WAIT"
            reason = "Contracts exist, but one or more liquidity fields required for ranking are unavailable or invalid."
        else:
            outcome = "REJECTED"
            reason = "All requested-side contract rows failed mandatory identity, strike or price readiness checks."

    checks = [
        {"check": "Section 4 source eligible", "status": "PASS", "detail": str(gate.get("final_outcome"))},
        {"check": "Strategy-owned bundle timestamp", "status": "PASS", "detail": bundle_ts.isoformat()},
        {"check": "No look-ahead snapshot", "status": "PASS", "detail": relation_reason},
        {"check": "Contract-level artifact", "status": "PASS" if not chain.empty else "BLOCK", "detail": str(snapshot.get("chain_artifact_path") or "Unavailable")},
        {"check": "Requested option side", "status": "PASS", "detail": side},
    ]
    return {
        "outcome": outcome,
        "reason": reason,
        "strategy_owner": str(gate.get("strategy_owner")),
        "strategy_id": str(gate.get("strategy_id")),
        "signal_id": str(gate.get("signal_id")),
        "bundle_id": str(gate.get("bundle_id")),
        "requested_side": side,
        "bundle_timestamp": bundle_ts.isoformat(),
        "snapshot_timestamp": snapshot_ts.isoformat() if snapshot_ts is not None else "Unavailable",
        "snapshot_relation": "AT_OR_BEFORE_BUNDLE",
        "contracts_available": int(len(chain) * 2) if not chain.empty else 0,
        "requested_side_contracts": len(contracts),
        "ready_for_ranking": sum(bool(row["liquidity_ready"]) for row in contracts),
        "contract_rows": contracts,
        "checks": checks,
        "next_step": (
            "Apply strategy-owned ranking and capacity rules in Section 5B."
            if outcome == "READY_FOR_RANKING"
            else "Do not rank, reserve, persist, consume, or execute a contract."
        ),
    }


def render_contract_data_readiness(result: Mapping[str, object]) -> None:
    st.markdown("### 5. Strategy-Owned CE/PE Contract Selection")
    st.caption(
        "Section 5A — read-only contract data readiness and hard-field safeguards. "
        "No contract is ranked, selected, persisted, reserved, consumed, or executed."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result["outcome"]))
    c2.metric("Requested side", str(result["requested_side"]))
    c3.metric("Side contracts", int(result["requested_side_contracts"]))
    c4.metric("Ready for ranking", int(result["ready_for_ranking"]))

    st.write(f"**Strategy owner:** {result['strategy_owner']}")
    st.write(f"**Signal ID:** {result['signal_id']}")
    st.write(f"**Bundle ID:** {result['bundle_id']}")
    st.write(f"**Bundle timestamp:** {result['bundle_timestamp']}")
    st.write(f"**Snapshot timestamp:** {result['snapshot_timestamp']}")
    st.write(f"**Snapshot relation:** {result['snapshot_relation']}")
    st.write(f"**Decision reason:** {result['reason']}")
    st.write(f"**Next step:** {result['next_step']}")

    with st.expander("View Section 5A readiness checks"):
        rows = list(result.get("checks") or [])
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("Contract checks were not started because Section 4 did not provide an eligible bundle.")

    with st.expander("View requested-side contract readiness"):
        rows = list(result.get("contract_rows") or [])
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No requested-side contract rows were evaluated.")

    if result["outcome"] == "READY_FOR_RANKING":
        st.success("Contract-level data is ready for read-only strategy-owned ranking in Section 5B.")
    elif result["outcome"] == "NOT_ELIGIBLE":
        st.info("Section 4 blocked this bundle, so zero contracts were evaluated.")
    else:
        st.warning("Contract ranking remains blocked until the stated data-readiness issue is resolved.")
