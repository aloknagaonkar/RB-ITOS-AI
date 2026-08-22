from __future__ import annotations

from red_bar_lab.ui._shared import *
from red_bar_lab.services.global_readiness_store import read_global_readiness_snapshots
from red_bar_lab.services.market_evidence_bundle_store import (
    read_latest_market_evidence_bundle,
)
from red_bar_lab.services.option_participation_store import (
    read_latest_option_participation,
    summarize_option_participation,
)
from red_bar_lab.ui.pages.market_readiness_legacy import render_legacy_page


def _display_number(value, digits=3):
    return "—" if value is None else f"{float(value):.{digits}f}"


def _display_score(value):
    return "—" if value is None else f"{float(value):.1f}"


def _participation_table_rows(rows):
    result = []
    for item in rows:
        result.append(
            {
                "Side": item.get("option_type") or "—",
                "Strike": _display_number(item.get("strike"), 0),
                "Current premium": _display_number(item.get("current_price"), 2),
                "VWAP": _display_number(item.get("vwap"), 2),
                "Volume": _display_number(item.get("volume"), 0),
                "OI": _display_number(item.get("oi"), 0),
                "Change in OI": _display_number(item.get("oi_change"), 0),
                "Delta": _display_number(item.get("delta")),
                "RSI": _display_number(item.get("option_rsi"), 1),
                "IV (required; 1–150)": _display_number(item.get("iv"), 2),
                "State": item.get("participation_state") or "INSUFFICIENT",
                "Eligibility": item.get("contract_eligibility") or "—",
            }
        )
    return result


def _render_authoritative_page(settings, underlying_name, bundle, readiness_rows) -> None:
    st.caption(
        "Read-only consumer of the single authoritative Market at a Glance "
        "evidence bundle. This tab does not recalculate an independent market "
        "direction."
    )

    if not bundle:
        st.warning(
            "No authoritative market evidence bundle is available yet. "
            "Run the paper monitor/collector."
        )
        return

    st.markdown("### Authoritative market conclusion")
    columns = st.columns(6)
    columns[0].metric(
        "Observed direction",
        bundle.get("observed_direction") or "UNAVAILABLE",
    )
    columns[1].metric(
        "Direction state",
        bundle.get("direction_state") or "UNAVAILABLE",
    )
    columns[2].metric(
        "Evidence readiness",
        bundle.get("evidence_readiness") or "UNAVAILABLE",
    )
    columns[3].metric(
        "Derivatives confirmed",
        "YES" if bundle.get("derivatives_confirmation_passed") else "NO",
    )
    columns[4].metric(
        "Trade eligibility",
        bundle.get("trade_eligibility") or "BLOCKED",
    )
    columns[5].metric("Trade bias", bundle.get("trade_bias") or "WAIT")

    if bundle.get("trade_eligibility") == "ELIGIBLE":
        st.success(
            bundle.get("confirmation")
            or "Authoritative evidence is eligible."
        )
    else:
        st.warning(
            bundle.get("confirmation")
            or "Authoritative evidence remains blocked."
        )

    if bundle.get("primary_blocker"):
        st.error(f"Primary blocker: {bundle['primary_blocker']}")
    if bundle.get("blocking_reasons"):
        st.caption(
            "Blocking reasons: " + ", ".join(bundle["blocking_reasons"])
        )
    if bundle.get("caution_reasons"):
        st.caption("Cautions: " + ", ".join(bundle["caution_reasons"]))

    st.markdown("### Authoritative evidence diagnostics")
    st.dataframe(
        _arrow_safe_rows(bundle.get("checklist") or []),
        width="stretch",
        hide_index=True,
    )

    st.markdown("### Freshness and alignment")
    st.dataframe(
        _arrow_safe_rows(bundle.get("freshness_rows") or []),
        width="stretch",
        hide_index=True,
    )

    participation_rows = read_latest_option_participation(
        settings.database_path,
        underlying_name=underlying_name,
    )
    participation = summarize_option_participation(participation_rows)
    st.markdown("### ATM ±4 option participation")
    st.caption(
        "Contract-quality rule: premium, volume, OI, bid, ask and IV must be "
        "available; bid/ask spread must be at most 3%; IV must be between 1 and 150."
    )
    if participation_rows:
        p1, p2, p3, p4 = st.columns(4)
        p1.metric(
            "Spot",
            _display_number(participation.get("spot_price"), 2),
        )
        p2.metric(
            "ATM",
            _display_number(participation.get("atm_strike"), 0),
        )
        p3.metric(
            "CE pressure",
            _display_score(participation.get("ce_score")),
        )
        p4.metric(
            "PE pressure",
            _display_score(participation.get("pe_score")),
        )
        st.dataframe(
            _arrow_safe_rows(_participation_table_rows(participation_rows)),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No ATM ±4 participation rows are available.")

    st.markdown("### Persisted evidence bundle")
    st.json(bundle)
    st.caption(
        f"Bundle: {bundle.get('bundle_id') or '—'} · "
        f"Safe evidence time: {bundle.get('safe_evidence_time') or '—'} · "
        "Authority: OBSERVATIONAL_ONLY"
    )

    with st.expander("Legacy global readiness diagnostics", expanded=False):
        if readiness_rows:
            st.dataframe(
                _arrow_safe_rows(readiness_rows),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No legacy global readiness snapshots are available.")


def render_page(
    settings,
    layout,
    database,
    token,
    underlying_name,
    instrument_key,
    interval,
) -> None:
    st.subheader("Trade Evidence & Market Readiness")

    # Protected authoritative workspace sections:
    # - Authoritative market conclusion
    # - Authoritative evidence diagnostics
    # - Persisted evidence bundle
    # - Legacy global readiness diagnostics
    # The legacy tab remains available only as non-authoritative diagnostics.
    bundle = read_latest_market_evidence_bundle(
        settings.database_path,
        underlying_name=underlying_name,
    )
    readiness_rows = read_global_readiness_snapshots(
        settings.database_path,
        underlying_name=underlying_name,
        limit=100,
    )

    authoritative_tab, legacy_tab = st.tabs(
        [
            "Authoritative Evidence",
            "Legacy Full Trade Evidence",
        ]
    )

    with authoritative_tab:
        _render_authoritative_page(
            settings,
            underlying_name,
            bundle,
            readiness_rows,
        )

    with legacy_tab:
        st.error(
            "This legacy workspace may calculate a different historical or "
            "independent bias. It is retained only for diagnostics and must not "
            "be used as a competing recommendation. The Authoritative Evidence "
            "tab is the sole market conclusion."
        )
        render_legacy_page(
            settings,
            layout,
            database,
            token,
            underlying_name,
            instrument_key,
            interval,
        )
