from red_bar_lab.ui._shared import *
from red_bar_lab.services.committee_diagnostics import build_committee_gate_trace
from red_bar_lab.execution.execution_score_contract import public_execution_scores


def _display_number(value, *, suffix="", signed=False):
    if value in (None, ""):
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    pattern = "+.3f" if signed else ".1f"
    return f"{number:{pattern}}{suffix}"


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Committee Gate Trace")
    st.caption(
        "Read-only explanation of the authoritative Institutional Execution Committee gates. "
        "This page does not change thresholds, Committee decisions, portfolio controls, or execution."
    )

    selected_date = st.date_input("Trading date", value=date.today())
    rows = database.read_institutional_execution_evaluations(
        trading_date=selected_date.isoformat(),
        limit=200,
    )
    if not rows:
        st.info("No Institutional Execution Committee evaluations are stored for this date yet.")
        return

    ordered = sorted(
        rows,
        key=lambda row: str(row.get("evaluated_at") or ""),
        reverse=True,
    )
    options = {}
    for index, row in enumerate(ordered):
        label = (
            f"Rank #{row.get('candidate_rank')} · {row.get('candidate_symbol')} · "
            f"{row.get('decision')} · {row.get('evaluated_at')}"
        )
        options[f"{label} · {index + 1}"] = row

    selected_label = st.selectbox(
        "Inspect Committee evaluation",
        list(options.keys()),
        key="committee_gate_trace_candidate",
    )
    evaluation = options[selected_label]
    public_scores = public_execution_scores(evaluation)
    trace = build_committee_gate_trace(evaluation)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Decision", str(trace.get("decision") or "—"))
    c2.metric(
        "Primary Confidence",
        _display_number(trace.get("primary_confidence_pct"), suffix="%"),
    )
    c3.metric(
        "Selection Heuristic Score",
        _display_number(public_scores.get("selection_heuristic_score")),
    )
    c4.metric(
        "Research Expectancy",
        _display_number(
            public_scores.get("research_expectancy_pct"),
            suffix="%",
            signed=True,
        ),
    )
    c5.metric("Gate Parity", "PASS" if trace.get("parity") else "MISMATCH")

    blockers = trace.get("authoritative_blockers") or []
    if blockers:
        st.error("Committee WAIT / BLOCK caused by: " + ", ".join(str(x) for x in blockers))
    elif trace.get("persisted_eligible"):
        st.success("All authoritative Committee gates passed. The candidate is Committee-qualified.")
    else:
        st.warning(
            "No blocker was reconstructed from the persisted evaluation, but the stored result is not eligible. "
            "Gate parity is MISMATCH and should be investigated."
        )

    st.markdown("#### Authoritative Committee Gates")
    st.dataframe(
        _arrow_safe_rows(trace.get("gates") or []),
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### Persisted Committee Reason")
    st.code(str(trace.get("reason") or "—"), language=None)

    st.markdown("#### Candidate Context")
    context = [{
        "candidate_rank": evaluation.get("candidate_rank"),
        "candidate_symbol": evaluation.get("candidate_symbol"),
        "option_type": evaluation.get("option_type"),
        "rule_quality_score": evaluation.get("rule_quality_score"),
        "opportunity_score": evaluation.get("opportunity_score"),
        "historical_score": evaluation.get("historical_score"),
        "selection_score": evaluation.get("selection_score"),
        "selection_heuristic_score": public_scores.get("selection_heuristic_score"),
        "research_expectancy_pct": public_scores.get("research_expectancy_pct"),
        "calibration_status": public_scores.get("calibration_status"),
        "expectancy_confidence_pct": evaluation.get("expectancy_confidence_pct"),
        "kelly_fraction_pct": evaluation.get("kelly_fraction_pct"),
        "shadow_decision": evaluation.get("shadow_decision"),
        "shadow_confidence_pct": evaluation.get("shadow_confidence_pct"),
        "shadow_adjustment_pct": evaluation.get("shadow_adjustment_pct"),
        "evidence_sample_size": evaluation.get("evidence_sample_size"),
        "evidence_ready": evaluation.get("evidence_ready"),
        "eligible": evaluation.get("eligible"),
        "decision": evaluation.get("decision"),
        "evaluated_at": evaluation.get("evaluated_at"),
    }]
    st.dataframe(_arrow_safe_rows(context), width="stretch", hide_index=True)

    st.caption(
        "Authoritative blockers mirror the current Committee implementation: Performance hard-block, "
        "terminal opportunity invalidity, and the configured selection heuristic threshold. "
        "Research expectancy, Shadow Intelligence, expectancy confidence, historical score, and Half-Kelly "
        "remain informational/evidence only. Probability language is withheld until decile calibration has "
        "at least 200 labelled outcomes in every bucket."
    )
