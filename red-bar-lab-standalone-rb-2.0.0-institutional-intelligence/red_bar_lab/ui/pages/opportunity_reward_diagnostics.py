from red_bar_lab.ui._shared import *
from red_bar_lab.services.opportunity_reward_diagnostics import build_opportunity_reward_trace
from red_bar_lab.services.candidate_contract_price_trace import build_all_candidate_contract_price_trace


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Opportunity Reward Trace")
    st.caption(
        "Read-only explanation of Opportunity Health reward consumption. "
        "This page does not change reward thresholds, Committee decisions, or execution."
    )

    selected_date = st.date_input("Trading date", value=date.today(), key="opportunity_reward_date")
    trading_date = selected_date.isoformat()
    rows = database.read_opportunity_evaluations(limit=500)
    rows = [row for row in rows if str(row.get("trading_date") or "") == trading_date]
    if not rows:
        st.info("No Opportunity Health evaluations are stored for this date yet.")
        return

    ordered = sorted(rows, key=lambda row: str(row.get("evaluated_at") or ""), reverse=True)
    options = {}
    for index, row in enumerate(ordered):
        label = (
            f"{row.get('candidate_symbol')} · {row.get('direction')} · {row.get('decision')} · "
            f"remaining {float(row.get('reward_remaining_pct') or 0.0):.1f}% · {row.get('evaluated_at')}"
        )
        options[f"{label} · {index + 1}"] = row

    selected_label = st.selectbox("Inspect Opportunity evaluation", list(options.keys()), key="opportunity_reward_candidate")
    opportunity = options[selected_label]
    signal_id = str(opportunity.get("signal_id") or "")
    signal_rows = database.read_signal_attempts(instrument_key, trading_date)
    signal = next((row for row in signal_rows if str(row.get("signal_id") or "") == signal_id), None)
    trace = build_opportunity_reward_trace(opportunity, signal)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Reward Gate", str(trace.get("reward_gate_status") or "—"))
    c2.metric("Reward Remaining", f"{float(trace.get('persisted_reward_remaining_pct') or 0.0):.1f}%")
    c3.metric("Move Consumed", f"{float(trace.get('persisted_move_consumed_pct') or 0.0):.1f}%")
    c4.metric("Minimum Remaining", f"{float(trace.get('minimum_reward_remaining_pct') or 0.0):.1f}%")
    c5.metric("Opportunity Score", f"{float(trace.get('opportunity_score') or 0.0):.1f}")

    if trace.get("reward_gate_status") == "BLOCK":
        st.error("REWARD_CONSUMED: " + str(trace.get("reward_gate_reason") or ""))
    else:
        st.success(str(trace.get("reward_gate_reason") or "Reward gate passed."))

    st.markdown("#### Reward Consumption Geometry")
    geometry = [{
        "direction": trace.get("direction"),
        "confirmation_high": trace.get("confirmation_high"),
        "confirmation_low": trace.get("confirmation_low"),
        "confirmation_close": trace.get("confirmation_close"),
        "confirmation_range": trace.get("confirmation_range"),
        "2x_range_full_consumption": trace.get("full_consumption_distance_2x_range"),
        "inferred_progress_points": trace.get("inferred_progress_points"),
        "inferred_evaluation_spot": trace.get("inferred_evaluation_spot"),
        "reward_consumed_threshold_spot": trace.get("reward_consumed_threshold_spot"),
    }]
    st.dataframe(_arrow_safe_rows(geometry), width="stretch", hide_index=True)

    st.markdown("#### Current Reward Rule")
    st.code(
        "candle_range = max(confirmation_high - confirmation_low, abs(confirmation_close) * 0.0005, 0.01)\n"
        "progress = directional move from confirmation_close\n"
        "move_consumed_pct = progress / (2 * candle_range) * 100\n"
        "reward_remaining_pct = 100 - move_consumed_pct\n"
        "REWARD_CONSUMED when reward_remaining_pct < 40%",
        language=None,
    )

    st.markdown("#### Persisted Opportunity Evaluation")
    context = [{
        "signal_id": trace.get("signal_id"),
        "candidate_symbol": trace.get("candidate_symbol"),
        "entry_mode": trace.get("entry_mode"),
        "signal_age_seconds": trace.get("signal_age_seconds"),
        "reward_score": trace.get("reward_score"),
        "structure_valid": trace.get("structure_valid"),
        "opposite_red_bar": trace.get("opposite_red_bar"),
        "eligible": trace.get("eligible"),
        "decision": trace.get("decision"),
        "reason": trace.get("reason"),
        "evaluated_at": trace.get("evaluated_at"),
    }]
    st.dataframe(_arrow_safe_rows(context), width="stretch", hide_index=True)
    st.info(str(trace.get("spot_persistence_note") or ""))

    st.markdown("#### All Selected Candidates — Contract Premium Lifecycle")
    st.caption(
        "For every candidate evaluated in the same scan, this keeps the exact same option contract fixed and pulls its "
        "1-minute premium at signal confirmation, first REWARD_CONSUMED evaluation, and the selected evaluation time."
    )
    scan_id = str(opportunity.get("scan_id") or "")
    scan_rows = [
        row for row in rows
        if str(row.get("scan_id") or "") == scan_id
        and str(row.get("signal_id") or "") == signal_id
    ]
    if not signal:
        st.warning("Signal details are unavailable, so signal-time contract premiums cannot be resolved.")
    else:
        try:
            access_token = resolve_access_token(token)
            _, _, paper_market = _cached_paper_market_stack(
                access_token,
                underlying_name,
                instrument_key,
            )
            premium_rows = build_all_candidate_contract_price_trace(
                market=paper_market,
                underlying_name=underlying_name,
                trading_date=trading_date,
                signal=signal,
                scan_rows=scan_rows,
                all_day_rows=rows,
            )
            selection_rows = database.read_trade_selection_evaluations(
                signal_id=signal_id,
                limit=500,
            )
            rank_map = {
                str(row.get("candidate_symbol") or ""): row.get("candidate_rank")
                for row in selection_rows
                if str(row.get("evaluated_at") or "") == str(opportunity.get("evaluated_at") or "")
            }
            for item in premium_rows:
                item["candidate_rank"] = rank_map.get(str(item.get("candidate_symbol") or ""))
            premium_rows = sorted(
                premium_rows,
                key=lambda item: int(item.get("candidate_rank") or 999),
            )
            display_rows = [{
                "Rank": item.get("candidate_rank"),
                "Contract": item.get("candidate_symbol"),
                "Type": item.get("option_type"),
                "Strike": item.get("strike"),
                "Signal Time": item.get("signal_time"),
                "Signal Premium ₹": item.get("signal_price"),
                "First Consumed Time": item.get("first_consumed_time"),
                "Consumed Premium ₹": item.get("first_consumed_price"),
                "Premium Move to Consumed %": item.get("signal_to_consumed_change_pct"),
                "Evaluation Time": item.get("evaluation_time"),
                "Evaluation Premium ₹": item.get("evaluation_price"),
                "Premium Move to Evaluation %": item.get("signal_to_evaluation_change_pct"),
                "Reward Remaining %": item.get("reward_remaining_pct"),
                "Move Consumed %": item.get("move_consumed_pct"),
                "Decision": item.get("decision"),
                "Reason": item.get("reason"),
                "Price Status": item.get("status"),
            } for item in premium_rows]
            st.dataframe(_arrow_safe_rows(display_rows), width="stretch", hide_index=True)
            good = [item for item in premium_rows if item.get("signal_price") is not None]
            if good:
                best_move = max(
                    good,
                    key=lambda item: float(item.get("signal_to_evaluation_change_pct") or -9999.0),
                )
                st.caption(
                    f"Same-contract comparison enabled for {len(good)}/{len(premium_rows)} candidates. "
                    f"Largest signal→evaluation premium move in this scan: "
                    f"{best_move.get('candidate_symbol')} "
                    f"{float(best_move.get('signal_to_evaluation_change_pct') or 0.0):+.2f}%."
                )
        except MissingAccessToken:
            st.info("Enter/resolve the Upstox access token to pull historical contract premiums for all candidates.")
        except Exception as exc:
            st.warning(f"Contract premium lifecycle is temporarily unavailable: {type(exc).__name__}: {exc}")

    st.caption(
        "Current production model treats two confirmation-candle ranges beyond the confirmation close as "
        "100% consumed and blocks when less than 40% reward remains. Contract premium tracing is diagnostic-only "
        "and does not modify Opportunity, Committee, ranking, or execution decisions."
    )
