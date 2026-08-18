from __future__ import annotations

from typing import Mapping

import streamlit as st


def render_contract_data_readiness_5a(result: Mapping[str, object]) -> None:
    """Render the canonical Section 5 heading and 5A data-readiness stage."""
    st.markdown("### 5. Strategy-Owned CE/PE Contract Selection")
    st.markdown("#### 5A. Contract Data Readiness")
    st.caption(
        "Selects the nearest no-look-ahead option snapshot at or before the strategy "
        "bundle timestamp and normalizes requested-side contract rows. Read-only only."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result.get("outcome") or "UNAVAILABLE"))
    c2.metric("Requested side", str(result.get("requested_side") or "Unavailable"))
    c3.metric("Side contracts", int(result.get("requested_side_contracts") or 0))
    c4.metric("Base rows ready", int(result.get("ready_for_ranking") or 0))
    st.write(f"**Strategy owner:** {result.get('strategy_owner') or 'Unavailable'}")
    st.write(f"**Signal ID:** {result.get('signal_id') or 'Not created'}")
    st.write(f"**Bundle ID:** {result.get('bundle_id') or 'Not created'}")
    st.write(f"**Bundle timestamp:** {result.get('bundle_timestamp') or 'Unavailable'}")
    st.write(f"**Snapshot timestamp:** {result.get('snapshot_timestamp') or 'Unavailable'}")
    st.write(f"**Snapshot relation:** {result.get('snapshot_relation') or 'UNAVAILABLE'}")
    st.write(f"**Decision reason:** {result.get('reason') or 'Unavailable'}")
    with st.expander("View Section 5A readiness checks"):
        rows = list(result.get("checks") or [])
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No Section 5A readiness checks are available.")
    st.write("**Mutation boundary:** no ranking, selection, persistence, reservation, consumption, or execution.")


def render_contract_market_context_5b(result: Mapping[str, object]) -> None:
    """Render point-in-time spot and ATM context as canonical Section 5B."""
    st.markdown("#### 5B. Point-in-Time Market Context")
    st.caption(
        "Resolves underlying spot and ATM from the exact no-look-ahead Section 5A "
        "snapshot. This stage does not rank, persist, reserve, or execute a contract."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result.get("market_context_status") or "UNAVAILABLE"))
    c2.metric("Spot", str(result.get("spot_price") or "Unavailable"))
    c3.metric("ATM strike", str(result.get("atm_strike") or "Unavailable"))
    c4.metric("Snapshot", str(result.get("snapshot_timestamp") or "Unavailable"))
    st.write(f"**Spot source:** {result.get('spot_source') or 'UNAVAILABLE'}")
    st.write(f"**ATM source:** {result.get('atm_source') or 'UNAVAILABLE'}")
    st.write(f"**Decision reason:** {result.get('market_context_reason') or result.get('reason') or 'Unavailable'}")
    st.write("**Mutation boundary:** read-only; no ranking, reservation, persistence, or execution.")


def render_contract_execution_metadata_5c(result: Mapping[str, object]) -> None:
    """Render exact-snapshot execution metadata as canonical Section 5C."""
    rows = [dict(row) for row in (result.get("contract_rows") or [])]
    complete = int(result.get("metadata_complete_count") or 0)
    st.markdown("#### 5C. Contract Execution Metadata")
    st.caption(
        "Validates instrument token, trading symbol, exchange, lot size, tick size and "
        "expiry from the exact Section 5A artifact. Missing values remain unavailable."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(result.get("metadata_context_status") or "UNAVAILABLE"))
    c2.metric("Contract rows", len(rows))
    c3.metric("Metadata complete", complete)
    c4.metric("Read-only", "YES")
    st.write(f"**Decision reason:** {result.get('metadata_context_reason') or 'Unavailable'}")
    with st.expander("View execution metadata completeness"):
        if rows:
            st.dataframe(
                [
                    {
                        "instrument_token": row.get("instrument_token"),
                        "instrument_key": row.get("instrument_key"),
                        "trading_symbol": row.get("trading_symbol"),
                        "exchange": row.get("exchange"),
                        "lot_size": row.get("lot_size"),
                        "tick_size": row.get("tick_size"),
                        "expiry": row.get("expiry"),
                        "complete": row.get("execution_metadata_complete"),
                        "sources": str(row.get("execution_metadata_sources") or {}),
                    }
                    for row in rows
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No Section 5A contract rows are available for metadata validation.")
    st.write("**Mutation boundary:** read-only; no fabricated metadata and no execution side effects.")


__all__ = [
    "render_contract_data_readiness_5a",
    "render_contract_market_context_5b",
    "render_contract_execution_metadata_5c",
]
