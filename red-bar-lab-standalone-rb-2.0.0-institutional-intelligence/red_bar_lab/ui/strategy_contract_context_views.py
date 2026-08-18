from __future__ import annotations

from typing import Mapping

import streamlit as st


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
    "render_contract_market_context_5b",
    "render_contract_execution_metadata_5c",
]
