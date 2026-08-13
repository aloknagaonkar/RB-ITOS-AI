from red_bar_lab.ui._shared import *
from red_bar_lab.intelligence.historical_evidence import HistoricalEvidenceService


def _summary(rows):
    resolved = [
        row for row in rows
        if str(row.get("outcome_result") or "").upper()
        in {"WIN", "LOSS", "BREAKEVEN"}
    ]
    wins = [row for row in resolved if str(row.get("outcome_result") or "").upper() == "WIN"]
    completeness = [
        float(row.get("evidence_completeness_pct") or 0.0)
        for row in rows
    ]
    return {
        "records": len(rows),
        "resolved": len(resolved),
        "wins": len(wins),
        "win_rate": (len(wins) / len(resolved) * 100.0 if resolved else 0.0),
        "reentries": sum(int(row.get("same_signal_reentry") or 0) == 1 for row in rows),
        "completeness": (sum(completeness) / len(completeness) if completeness else 0.0),
    }


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Historical Intelligence")
    st.markdown(
        _decision_badge_html(
            "HISTORICAL EVIDENCE / LEARNING · EXECUTION IMPACT = NONE",
            "shadow",
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Sprint 4.1 creates a canonical evidence layer from paper execution and "
        "Historical Decision Replay. It records what the frozen engine decided, "
        "what happened afterward, and which fields are genuinely available. "
        "It never changes Primary, Committee, Portfolio, Queue or Exit decisions."
    )

    evidence = HistoricalEvidenceService(database)
    evidence.store.initialize()

    today = date.today()
    h1, h2 = st.columns(2)
    with h1:
        date_from = st.date_input(
            "Evidence From",
            value=today - timedelta(days=30),
            key="historical_evidence_from",
        )
    with h2:
        date_to = st.date_input(
            "Evidence To",
            value=today,
            key="historical_evidence_to",
        )

    st.caption(
        "Paper evidence can be rebuilt safely because source order IDs are stable. "
        "Historical replay evidence is refreshed automatically whenever a replay day is run."
    )
    if st.button("Build / Refresh Paper Evidence", type="primary", key="build_historical_paper_evidence"):
        try:
            report = evidence.build_paper_execution_evidence(
                account_id="PAPER-STD",
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
            )
            st.session_state["historical_evidence_paper_report"] = report
            st.success(
                f"Paper evidence refreshed: {report.records_written} record(s), "
                f"{report.resolved_outcomes} resolved outcome(s), "
                f"{report.reentries} same-signal re-entry record(s)."
            )
        except Exception as exc:
            st.exception(exc)

    rows = evidence.store.read(
        instrument_key=instrument_key,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        limit=5000,
    )

    summary = _summary(rows)
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Evidence Records", summary["records"])
    m2.metric("Resolved", summary["resolved"])
    m3.metric("Win Rate", f'{summary["win_rate"]:.1f}%')
    m4.metric("Re-entry Records", summary["reentries"])
    m5.metric("Completeness", f'{summary["completeness"]:.1f}%')
    m6.metric("Execution Impact", "NONE")

    if not rows:
        st.info(
            "No canonical evidence is stored for this range yet. Build paper evidence "
            "or run Historical Decision Replay for a replay-ready date."
        )
        return

    source_values = ["ALL"] + sorted({str(row.get("source_type")) for row in rows if row.get("source_type")})
    outcome_values = ["ALL"] + sorted({str(row.get("outcome_result")) for row in rows if row.get("outcome_result")})
    level_values = ["ALL"] + sorted({str(row.get("level_type")) for row in rows if row.get("level_type")})
    direction_values = ["ALL"] + sorted({str(row.get("direction")) for row in rows if row.get("direction")})

    f1, f2, f3, f4, f5 = st.columns(5)
    with f1:
        source_filter = st.selectbox("Source", source_values, key="historical_evidence_source")
    with f2:
        outcome_filter = st.selectbox("Outcome", outcome_values, key="historical_evidence_outcome")
    with f3:
        level_filter = st.selectbox("Level", level_values, key="historical_evidence_level")
    with f4:
        direction_filter = st.selectbox("Direction", direction_values, key="historical_evidence_direction")
    with f5:
        reentry_filter = st.selectbox(
            "Entry Type",
            ["ALL", "INITIAL", "REENTRY"],
            key="historical_evidence_reentry",
        )

    filtered = []
    for row in rows:
        if source_filter != "ALL" and str(row.get("source_type")) != source_filter:
            continue
        if outcome_filter != "ALL" and str(row.get("outcome_result")) != outcome_filter:
            continue
        if level_filter != "ALL" and str(row.get("level_type")) != level_filter:
            continue
        if direction_filter != "ALL" and str(row.get("direction")) != direction_filter:
            continue
        is_reentry = int(row.get("same_signal_reentry") or 0) == 1
        if reentry_filter == "INITIAL" and is_reentry:
            continue
        if reentry_filter == "REENTRY" and not is_reentry:
            continue
        filtered.append(row)

    filtered_summary = _summary(filtered)
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Filtered Records", filtered_summary["records"])
    s2.metric("Filtered Resolved", filtered_summary["resolved"])
    s3.metric("Filtered Win Rate", f'{filtered_summary["win_rate"]:.1f}%')
    s4.metric("Filtered Completeness", f'{filtered_summary["completeness"]:.1f}%')

    display_rows = []
    for row in filtered:
        missing = row.get("missing_fields") or []
        display_rows.append(
            {
                "Date": row.get("trading_date"),
                "Source": row.get("source_type"),
                "Signal": row.get("signal_id"),
                "Level": row.get("level_type"),
                "Direction": row.get("direction"),
                "Candidate": row.get("candidate_symbol"),
                "Side": row.get("option_type"),
                "Rank": row.get("candidate_rank"),
                "Candidate Score": row.get("candidate_score"),
                "Opportunity": row.get("opportunity_score"),
                "Selection": row.get("selection_score"),
                "Decision": row.get("decision"),
                "Execution": row.get("execution"),
                "Entry Mode": row.get("entry_mode"),
                "Same Signal Re-entry": bool(row.get("same_signal_reentry")),
                "Signal Re-entry #": row.get("signal_reentry_number"),
                "Contract Entry #": row.get("contract_entry_number"),
                "Entry": row.get("entry_price"),
                "Exit": row.get("exit_price"),
                "Return %": row.get("return_pct"),
                "MFE": row.get("mfe_points"),
                "MAE": row.get("mae_points"),
                "Exit Reason": row.get("exit_reason"),
                "Outcome": row.get("outcome_result"),
                "Outcome Basis": row.get("outcome_basis"),
                "Entry 5m Close": row.get("entry_underlying_5m_close"),
                "Entry EMA10": row.get("entry_ema10"),
                "Entry EMA10 State": row.get("entry_ema10_state"),
                "Fidelity": row.get("data_fidelity"),
                "Completeness %": row.get("evidence_completeness_pct"),
                "Missing": ", ".join(str(item) for item in missing),
                "Execution Impact": row.get("shadow_execution_impact"),
            }
        )

    st.markdown("#### Canonical Evidence Records")
    st.dataframe(_arrow_safe_rows(display_rows), width="stretch", hide_index=True)

    incomplete = [row for row in rows if float(row.get("evidence_completeness_pct") or 0.0) < 100.0]
    if incomplete:
        st.info(
            "Incomplete evidence is retained rather than guessed. Missing EMA10/MFE/MAE or "
            "other fields are explicitly listed so later probability calibration can exclude "
            "or stratify lower-fidelity samples instead of silently filling them."
        )
