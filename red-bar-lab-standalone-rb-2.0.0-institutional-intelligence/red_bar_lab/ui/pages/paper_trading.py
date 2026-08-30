from time import perf_counter

from red_bar_lab.ui._shared import *



def _parse_directional_reference_detail(
    detail: object,
) -> dict[str, str]:
    values: dict[str, str] = {}
    for token in str(detail or "").split(";"):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _latest_directional_reference(
    database,
    signal_id: str,
) -> dict[str, str] | None:
    rows = database.read_execution_state_events(
        signal_id=signal_id,
        limit=50,
    )
    for row in rows:
        if row.get("state") != "DIRECTIONAL_REGIME_REFERENCE":
            continue
        parsed = _parse_directional_reference_detail(
            row.get("detail")
        )
        parsed["timestamp"] = str(row.get("timestamp") or "")
        return parsed
    return None

def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    _perf_started = perf_counter()
    _perf_last = _perf_started
    _perf_rows = []

    def _perf_mark(section: str) -> None:
        nonlocal _perf_last
        now = perf_counter()
        _perf_rows.append(
            {
                "Section": section,
                "Seconds": round(now - _perf_last, 3),
            }
        )
        _perf_last = now

    st.subheader("Paper Trading Command Center")
    st.caption(
        "RB-1.4.1 · Primary-Only Execution Authority + Expectancy Committee. "
        "Recommendations on this page are RULE-BASED PAPER decisions, "
        "not AI recommendations. Live broker execution remains disabled."
    )
    # Active config header — same as the Red Bar Strategy page.
    from red_bar_lab.ui.live_cadence import render_active_paper_config

    render_active_paper_config(st)

    live_foundation = ZerodhaLiveExecutionProvider(
        kill_switch_active=True
    )
    paper_access_token = (
        token.strip()
        or os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    )
    paper_data_ready = bool(paper_access_token)
    paper_market = None
    market_intelligence = None
    intelligence_snapshot = None

    # ---------- Market data ----------
    if paper_data_ready:
        try:
            (
                upstox_provider,
                market_intelligence,
                paper_market,
            ) = _cached_paper_market_stack(
                paper_access_token,
                underlying_name,
                instrument_key,
            )
            intelligence_snapshot = market_intelligence.snapshot(
                underlying_key=instrument_key,
            )
        except Exception as exc:
            paper_data_ready = False
            st.error(
                "Upstox Market Intelligence could not be initialized: "
                f"{exc}"
            )

    _perf_mark("Market intelligence")

    # ---------- Portfolio / history ----------
    paper_capital = st.number_input(
        "Virtual Capital (₹)",
        min_value=10000.0,
        max_value=10000000.0,
        value=100000.0,
        step=10000.0,
        key="paper_virtual_capital",
    )
    paper_engine = RedBarPaperExecutionEngine(
        database,
        settings,
        initial_capital=float(paper_capital),
    )
    portfolio = paper_engine.portfolio_summary()

    all_paper_orders = database.read_paper_execution_orders(
        "PAPER-STD"
    )
    open_orders = [
        row for row in all_paper_orders
        if row.get("status") == "OPEN"
    ]
    closed_orders = [
        row for row in all_paper_orders
        if row.get("status") == "CLOSED"
    ]

    _perf_mark("Portfolio / history")

    # ---------- Today signal / decision ----------
    today_text = date.today().isoformat()
    todays_signals = database.read_signal_attempts(
        instrument_key,
        today_text,
    )
    confirmed_today = [
        row
        for row in todays_signals
        if row.get("confirmation_timestamp")
        and row.get("direction") in {"BULLISH", "BEARISH"}
    ]
    latest_signal = (
        sorted(
            confirmed_today,
            key=lambda row: str(
                row.get("confirmation_timestamp") or ""
            ),
        )[-1]
        if confirmed_today else None
    )
    latest_direction = (
        str(latest_signal.get("direction"))
        if latest_signal else "WAIT"
    )
    paper_action = (
        "LOOK FOR CE"
        if latest_direction == "BULLISH"
        else "LOOK FOR PE"
        if latest_direction == "BEARISH"
        else "WAIT"
    )

    _perf_mark("Signal context")

    # ---------- Top command strip ----------
    st.markdown("### Command Status")
    status_cols = st.columns(6)
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    market_open = (
        now_ist.weekday() < 5
        and time(9, 15) <= now_ist.time() < time(15, 30)
    )
    status_cols[0].metric(
        "Market",
        "OPEN" if market_open else "CLOSED",
    )
    status_cols[1].metric("Execution", "PAPER")
    status_cols[2].metric("Market Data", "UPSTOX")
    status_cols[3].metric("Automation", "ENABLED")
    status_cols[4].metric("Live Orders", "HARD DISABLED")
    status_cols[5].metric(
        "Kill Switch",
        "ACTIVE"
        if live_foundation.kill_switch_active else "OFF",
    )

    auto_refresh = st.toggle(
        "Auto-refresh live paper status every 5 seconds",
        value=True,
        key="paper_auto_refresh",
        help=(
            "Refreshes only monitor heartbeat, open-position count and "
            "open P&L. It does NOT reload the browser or rerun candidate "
            "ranking. Use Refresh & Rank Candidates for a new market ranking."
        ),
    )

    if not paper_access_token:
        st.warning(
            "UPSTOX_ACCESS_TOKEN is not configured. "
            "Set it in the sidebar/environment to populate live paper data."
        )

    if auto_refresh:
        _render_paper_live_status_fragment(database)
        st.caption(
            "Live status refresh: ON · 5s fragment · no full-page reload. "
            "Committee decisions are foreground-persisted; the background monitor "
            "is the source of truth for execution/position management only."
        )
    else:
        _render_paper_monitor_status(database)
        st.caption(
            "Live status refresh: OFF · displayed values are read once "
            "for this page render."
        )

    # ---------- Market + account ----------
    st.markdown("### Market Health & Paper Account")
    mh1, mh2 = st.columns(2)
    with mh1:
        market_cards = st.columns(4)
        market_cards[0].metric(
            "Spot",
            (
                f"{float(intelligence_snapshot.spot_price):,.2f}"
                if intelligence_snapshot
                and intelligence_snapshot.spot_price is not None
                else "—"
            ),
        )
        market_cards[1].metric(
            "PCR (OI)",
            (
                f"{float(intelligence_snapshot.pcr_oi):.2f}"
                if intelligence_snapshot
                and intelligence_snapshot.pcr_oi is not None
                else "—"
            ),
        )
        market_cards[2].metric(
            "Call / Put Wall",
            (
                f"{intelligence_snapshot.call_wall or '—'} / "
                f"{intelligence_snapshot.put_wall or '—'}"
                if intelligence_snapshot else "—"
            ),
        )
        market_cards[3].metric(
            "Max Pain",
            (
                intelligence_snapshot.max_pain
                if intelligence_snapshot else "—"
            ),
        )
        if intelligence_snapshot:
            st.caption(
                f"Expiry {intelligence_snapshot.expiry} · "
                f"Snapshot {intelligence_snapshot.captured_at}"
            )

    with mh2:
        account_cards = st.columns(4)
        account_cards[0].metric(
            "Available",
            f"₹{portfolio.available_capital:,.2f}",
        )
        account_cards[1].metric(
            "Deployed",
            f"₹{portfolio.deployed_capital:,.2f}",
        )
        account_cards[2].metric(
            "Net P&L",
            f"₹{portfolio.net_pnl:+,.2f}",
        )
        account_cards[3].metric(
            "Open / Closed",
            f"{portfolio.open_positions} / "
            f"{portfolio.closed_positions}",
        )

    # ---------- Current Red Bar decision ----------
    st.markdown("### Current Red Bar Decision")
    decision_cols = st.columns(5)
    decision_cols[0].metric(
        "Signal",
        (
            str(latest_signal.get("signal_id"))
            if latest_signal else "NONE"
        ),
    )
    decision_cols[1].metric("Direction", latest_direction)
    decision_cols[2].metric("Paper Action", paper_action)
    decision_cols[3].metric(
        "Signal State",
        (
            str(latest_signal.get("state") or "—")
            if latest_signal else "WAITING"
        ),
    )
    decision_cols[4].metric(
        "Confirmation",
        (
            str(latest_signal.get("confirmation_timestamp") or "—")
            if latest_signal else "—"
        ),
    )

    st.markdown("#### Automatic Execution Eligibility")
    latest_diag_rows = (
        database.read_paper_signal_diagnostics(
            signal_id=(
                str(latest_signal.get("signal_id"))
                if latest_signal else None
            ),
            limit=1,
        )
        if latest_signal
        else []
    )
    latest_diag = latest_diag_rows[0] if latest_diag_rows else None

    if latest_signal:
        current_signal_age = None
        try:
            current_signal_ts = pd.Timestamp(
                latest_signal.get("confirmation_timestamp")
            )
            if current_signal_ts.tzinfo is None:
                current_signal_ts = current_signal_ts.tz_localize(
                    "Asia/Kolkata"
                )
            else:
                current_signal_ts = current_signal_ts.tz_convert(
                    "Asia/Kolkata"
                )
            current_signal_age = (
                pd.Timestamp(
                    datetime.now(ZoneInfo("Asia/Kolkata"))
                )
                - current_signal_ts
            ).total_seconds()
        except Exception:
            current_signal_age = None

        el_cols = st.columns(6)
        el_cols[0].metric(
            "Confirmed",
            "YES",
        )
        el_cols[1].metric(
            "Signal Age",
            (
                f"{current_signal_age:.0f}s"
                if current_signal_age is not None
                else "UNKNOWN"
            ),
        )
        el_cols[2].metric(
            "Freshness Gate",
            (
                "PASS"
                if current_signal_age is not None
                and 0 <= current_signal_age <= 180
                else "EXPIRED → OPPORTUNITY"
            ),
        )
        el_cols[3].metric(
            "Signal State",
            latest_signal.get("state") or "—",
        )
        el_cols[4].metric(
            "Already Executed",
            (
                "NO"
                if not database.paper_execution_exists_for_signal(
                    signal_id=str(latest_signal.get("signal_id")),
                    account_id="PAPER-STD",
                )
                else "YES"
            ),
        )
        el_cols[5].metric(
            "Monitor Result",
            (
                latest_diag.get("final_decision") or "NOT SCANNED"
                if latest_diag else "NOT SCANNED"
            ),
        )

        if latest_diag:
            st.caption(
                "Automatic execution reason: "
                f"{latest_diag.get('reason') or '—'}"
            )
        elif current_signal_age is not None and current_signal_age > 180:
            st.info(
                "Signal age is informational in RB-1.5.0. Older Red Bars remain eligible when current "
                "Opportunity Health is strong; only current opportunity invalidation or execution safety can block entry."
            )
    else:
        st.info(
            "No confirmed Red Bar signal is available for automatic "
            "paper-execution validation."
        )

    st.markdown("### Directional Regime Intelligence")
    directional_ui = (
        _latest_directional_reference(
            database,
            str(latest_signal.get("signal_id") or ""),
        )
        if latest_signal
        else None
    )

    if directional_ui:
        status = directional_ui.get("status", "UNAVAILABLE")
        status_cols = st.columns(7)
        status_cols[0].metric("Status", status)
        status_cols[1].metric(
            "Regime",
            directional_ui.get("regime", "UNKNOWN"),
        )
        status_cols[2].metric(
            "Bundle Direction",
            directional_ui.get("bundle_direction", "NA"),
        )
        status_cols[3].metric(
            "Setup",
            directional_ui.get("setup", "NA"),
        )
        status_cols[4].metric(
            "Alignment",
            directional_ui.get("alignment_score", "0"),
        )
        status_cols[5].metric(
            "Policy",
            directional_ui.get("policy_action", "CONTINUE"),
        )
        status_cols[6].metric(
            "Candidate Bonus",
            directional_ui.get("candidate_bonus", "0"),
        )

        reason = directional_ui.get("reason", "—")
        mode = directional_ui.get(
            "mode",
            "ACTIVE_CONFIRMATION_FILTER",
        )
        if status == "CONFLICT":
            st.error(
                "Directional conflict: the current confirmed Paper Trading "
                "signal is held before candidate and order creation."
            )
        elif status == "ALIGNED":
            st.success(
                "Directional alignment confirmed. The configured candidate "
                "score bonus is applied, capped at 100."
            )
        elif status in {"PARTIAL_ALIGNMENT", "NEUTRAL"}:
            st.info(
                "Directional context is non-blocking. Paper Trading continues "
                "without a score adjustment."
            )
        else:
            st.warning(
                "Directional reference is unavailable. Paper Trading uses "
                "fail-open behavior and continues with the existing signal."
            )
        st.caption(
            f"Reason: {reason} | Mode: {mode} | "
            f"Bundle: {directional_ui.get('bundle_id', 'NA')}"
        )
    else:
        st.info(
            "No Directional Regime reference has been recorded for the latest "
            "signal yet. Run or refresh the Paper Trading evaluation cycle."
        )

    # RB-0.9.3 foreground decision phase: evaluate the newest confirmed signal
    # without opening a position. The background monitor consumes APPROVED queue
    # items separately, so the UI can explain the decision immediately.
    foreground_committee_error = None
    if paper_data_ready and latest_signal:
        try:
            signal_id_for_eval = str(latest_signal.get("signal_id") or "")
            existing_committee = database.read_institutional_execution_evaluations(
                signal_id=signal_id_for_eval, limit=1
            )
            should_foreground_evaluate = not existing_committee
            if existing_committee:
                try:
                    evaluated_ts = datetime.fromisoformat(
                        str(existing_committee[0].get("evaluated_at"))
                    )
                    if evaluated_ts.tzinfo is None:
                        evaluated_ts = evaluated_ts.replace(
                            tzinfo=ZoneInfo("Asia/Kolkata")
                        )
                    should_foreground_evaluate = (
                        datetime.now(ZoneInfo("Asia/Kolkata")) - evaluated_ts
                    ).total_seconds() >= 55
                except Exception:
                    should_foreground_evaluate = True
            if should_foreground_evaluate:
                foreground_automation = RedBarPaperAutomationService(
                    zerodha=paper_market,
                    database=database,
                    settings=settings,
                    underlying_name=underlying_name,
                    initial_capital=float(paper_capital),
                    minimum_candidate_score=65.0,
                )
                foreground_automation.process_new_signals(
                    trading_date=today_text, lots=1, queue_only=True
                )
        except Exception as exc:
            foreground_committee_error = str(exc)

    if foreground_committee_error:
        st.warning(
            "Foreground committee evaluation could not refresh: "
            f"{foreground_committee_error}"
        )

    st.markdown("### Candidate Lifecycle Manager")
    lifecycle_candidates = (
        database.read_candidate_lifecycle(
            signal_id=(str(latest_signal.get("signal_id")) if latest_signal else None),
            limit=25,
        ) if latest_signal else []
    )
    if lifecycle_candidates:
        newest_lifecycle = lifecycle_candidates[0]
        l1, l2, l3, l4, l5, l6 = st.columns(6)
        l1.metric("State", str(newest_lifecycle.get("state") or "—"))
        l2.metric("Age", f"{float(newest_lifecycle.get('age_seconds') or 0):.0f}s")
        l3.metric("Health", f"{float(newest_lifecycle.get('health_score') or 0):.1f}%")
        l4.metric("Session", str(newest_lifecycle.get("current_session") or "—"))
        l5.metric("Market Drift", str(newest_lifecycle.get("market_drift") or "—"))
        l6.metric("Action", str(newest_lifecycle.get("action") or "—"))
        st.dataframe(
            _arrow_safe_rows([
                {
                    "Candidate": row.get("candidate_symbol") or "SIGNAL",
                    "State": row.get("state"),
                    "Health %": row.get("health_score"),
                    "Age s": row.get("age_seconds"),
                    "Created Session": row.get("created_session"),
                    "Current Session": row.get("current_session"),
                    "Drift": row.get("market_drift"),
                    "Duplicate": "YES" if row.get("duplicate") else "NO",
                    "Reason": row.get("reason"),
                    "Action": row.get("action"),
                    "Replacement Signal": row.get("replacement_signal_id") or "—",
                }
                for row in lifecycle_candidates
            ]),
            width="stretch", hide_index=True,
        )
        if str(newest_lifecycle.get("state")) == "EXPIRED":
            st.warning(
                "This candidate has been retired before committee evaluation. "
                "A fresh Red Bar must come from the signal detector; RB-1.3.0 does not fabricate replacement signals."
            )
    elif latest_signal:
        st.info("Candidate lifecycle will populate during the next foreground evaluation.")
    else:
        st.caption("Candidate Lifecycle Manager is waiting for a confirmed Red Bar.")

    st.markdown("### Market Session Manager")
    session_now = datetime.now(ZoneInfo("Asia/Kolkata"))
    session_code = (
        "PRE_OPEN" if session_now.time() < time(9, 15) else
        "OPENING" if session_now.time() < time(9, 30) else
        "MORNING" if session_now.time() < time(11, 30) else
        "MIDDAY" if session_now.time() < time(13, 30) else
        "AFTERNOON" if session_now.time() < time(14, 45) else
        "CLOSING" if session_now.time() < time(15, 25) else "CLOSED"
    )
    st.caption(
        f"Current session: **{session_code}**. A candidate crossing into another session is retired and must be replaced by a new confirmed Red Bar."
    )

    st.markdown("### Opportunity Health Engine")
    latest_opportunity_rows = (
        database.read_opportunity_evaluations(
            signal_id=(
                str(latest_signal.get("signal_id"))
                if latest_signal else None
            ),
            limit=1,
        )
        if latest_signal else []
    )
    latest_opportunity = (
        latest_opportunity_rows[0]
        if latest_opportunity_rows else None
    )

    if latest_opportunity:
        op1, op2, op3, op4, op5, op6 = st.columns(6)
        op1.metric(
            "Entry Mode",
            latest_opportunity.get("entry_mode") or "—",
        )
        op2.metric(
            "Signal Age",
            f"{float(latest_opportunity.get('signal_age_seconds') or 0):.0f}s",
        )
        op3.metric(
            "Opportunity Health",
            f"{float(latest_opportunity.get('opportunity_score') or 0):.1f}/100",
        )
        op4.metric(
            "Reward Remaining",
            f"{float(latest_opportunity.get('reward_remaining_pct') or 0):.1f}%",
        )
        op5.metric(
            "Move Consumed",
            f"{float(latest_opportunity.get('move_consumed_pct') or 0):.1f}%",
        )
        op6.metric(
            "Decision",
            latest_opportunity.get("decision") or "—",
        )

        structure_ok = bool(
            latest_opportunity.get("structure_valid")
        )
        opposite = bool(
            latest_opportunity.get("opposite_red_bar")
        )
        eligible = bool(latest_opportunity.get("eligible"))

        status_rows = [
            {
                "Module": "Red Bar Structure",
                "Status": "PASS" if structure_ok else "FAIL",
                "Score": latest_opportunity.get("structure_score"),
            },
            {
                "Module": "Momentum Continuation",
                "Status": (
                    "PASS"
                    if float(
                        latest_opportunity.get("momentum_score") or 0
                    ) >= 12
                    else "WARNING"
                ),
                "Score": latest_opportunity.get("momentum_score"),
            },
            {
                "Module": "Reward Remaining",
                "Status": (
                    "PASS"
                    if float(
                        latest_opportunity.get(
                            "reward_remaining_pct"
                        ) or 0
                    ) >= 40
                    else "FAIL"
                ),
                "Score": latest_opportunity.get("reward_score"),
            },
            {
                "Module": "Option Health",
                "Status": (
                    "PASS"
                    if float(
                        latest_opportunity.get(
                            "option_health_score"
                        ) or 0
                    ) >= 12
                    else "WARNING"
                ),
                "Score": latest_opportunity.get(
                    "option_health_score"
                ),
            },
            {
                "Module": "Market Context",
                "Status": "INFO",
                "Score": latest_opportunity.get(
                    "market_context_score"
                ),
            },
            {
                "Module": "Signal Age Score (Informational)",
                "Status": "INFO",
                "Score": latest_opportunity.get("time_score"),
            },
            {
                "Module": "Opposite Red Bar",
                "Status": "FAIL" if opposite else "PASS",
                "Score": None,
            },
        ]
        st.dataframe(
            _arrow_safe_rows(status_rows),
            width="stretch",
            hide_index=True,
        )

        if (
            latest_opportunity.get("entry_mode")
            == "OPPORTUNITY_EXTENSION"
        ):
            if eligible:
                st.success(
                    "OLDER SIGNAL / STRONG OPPORTUNITY: signal age is informational and current "
                    "Opportunity Health still qualifies the setup for PAPER execution."
                )
            else:
                st.warning(
                    "OLDER SIGNAL / WEAK OPPORTUNITY: age did not block the setup; current "
                    "Opportunity Health or a true opportunity invalidation did."
                )
        else:
            st.info(
                "Fresh signal: the Current Decision Engine remains the "
                "execution authority. Opportunity Health is also recorded "
                "for later comparison."
            )

        st.caption(
            "RB-1.5.0 Opportunity Health is a 0–100 current-strength score: structure 20, VWAP 15, "
            "EMA 15, momentum 15, volume 10, OI 10, liquidity 10 and spread 5. Age has zero execution weight. "
            "Health ≥75 is portfolio-eligible unless structure/opposite-Red-Bar/reward/execution-quality invalidates it."
        )
        st.caption(
            f"Latest opportunity reason: "
            f"{latest_opportunity.get('reason') or '—'}"
        )

        load_opportunity_evidence = st.toggle(
            "Load Opportunity Extension Evidence",
            value=False,
            key="load_opportunity_extension_evidence",
            help=(
                "Loads recorded opportunity evaluations and fresh-vs-"
                "extension paper results for validation."
            ),
        )
        if load_opportunity_evidence:
            evidence_rows = database.read_opportunity_evaluations(
                limit=100
            )
            if evidence_rows:
                st.markdown("#### Opportunity Evaluation History")
                st.dataframe(
                    _arrow_safe_rows(
                        [
                            {
                                "Time": row.get("evaluated_at"),
                                "Signal": row.get("signal_id"),
                                "Mode": row.get("entry_mode"),
                                "Age": row.get("signal_age_seconds"),
                                "Candidate": row.get(
                                    "candidate_symbol"
                                ),
                                "Candidate Score": row.get(
                                    "candidate_score"
                                ),
                                "Opportunity": row.get(
                                    "opportunity_score"
                                ),
                                "Reward Remaining %": row.get(
                                    "reward_remaining_pct"
                                ),
                                "Consumed %": row.get(
                                    "move_consumed_pct"
                                ),
                                "Eligible": (
                                    "YES"
                                    if row.get("eligible")
                                    else "NO"
                                ),
                                "Decision": row.get("decision"),
                                "Reason": row.get("reason"),
                            }
                            for row in evidence_rows
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )

            completed = [
                row for row in database.read_paper_execution_orders(
                    "PAPER-STD"
                )
                if row.get("status") == "CLOSED"
                and row.get("entry_mode")
                in {"FRESH_SIGNAL", "OPPORTUNITY_EXTENSION"}
            ]
            if completed:
                comparison_rows = []
                for mode in (
                    "FRESH_SIGNAL",
                    "OPPORTUNITY_EXTENSION",
                ):
                    group = [
                        row for row in completed
                        if row.get("entry_mode") == mode
                    ]
                    pnl_values = [
                        float(row.get("realized_pnl") or 0.0)
                        for row in group
                    ]
                    wins = sum(value > 0 for value in pnl_values)
                    comparison_rows.append(
                        {
                            "Entry Mode": mode,
                            "Closed Trades": len(group),
                            "Wins": wins,
                            "Win Rate %": (
                                round(wins / len(group) * 100, 1)
                                if group else None
                            ),
                            "Total P&L": round(
                                sum(pnl_values), 2
                            ),
                            "Average P&L": (
                                round(
                                    sum(pnl_values) / len(group),
                                    2,
                                )
                                if group else None
                            ),
                        }
                    )
                st.markdown(
                    "#### Fresh vs Opportunity Extension Results"
                )
                st.dataframe(
                    _arrow_safe_rows(comparison_rows),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.caption(
                    "Fresh-vs-extension outcome statistics will appear "
                    "after tagged paper trades close."
                )
    elif latest_signal:
        st.info(
            "Opportunity Health is enabled. The foreground decision "
            "pipeline will populate this panel as soon as market data is available."
        )
    else:
        st.caption(
            "Opportunity Health is waiting for a confirmed Red Bar."
        )

    st.markdown("### Performance Trade Selection")
    latest_selection_rows = (
        database.read_trade_selection_evaluations(
            signal_id=(str(latest_signal.get("signal_id")) if latest_signal else None),
            limit=25,
        )
        if latest_signal else []
    )
    if latest_selection_rows:
        newest_eval_time = latest_selection_rows[0].get("evaluated_at")
        current_selection = [
            row for row in latest_selection_rows
            if row.get("evaluated_at") == newest_eval_time
        ]
        qualified_count = sum(bool(row.get("eligible")) for row in current_selection)
        evidence_count = sum(bool(row.get("evidence_ready")) for row in current_selection)
        ps1, ps2, ps3, ps4 = st.columns(4)
        ps1.metric("Candidates Evaluated", len(current_selection))
        ps2.metric("Qualified to Execute", qualified_count)
        ps3.metric("History-Backed", evidence_count)
        ps4.metric("Fixed Trade Limit", "NONE")
        st.dataframe(
            _arrow_safe_rows([
                {
                    "Rank": row.get("candidate_rank"),
                    "Candidate": row.get("candidate_symbol"),
                    "Candidate Score": row.get("candidate_score"),
                    "Opportunity": row.get("opportunity_score"),
                    "Reward Remaining %": row.get("reward_remaining_pct"),
                    "R:R": row.get("reward_risk_ratio"),
                    "History N": row.get("history_sample_size"),
                    "Win Rate %": row.get("history_win_rate_pct"),
                    "Profit Factor": row.get("history_profit_factor"),
                    "Expectancy %": row.get("history_expectancy_pct"),
                    "MAE %": row.get("history_avg_mae_pct"),
                    "MFE %": row.get("history_avg_mfe_pct"),
                    "TSS": row.get("selection_score"),
                    "Execute": "YES" if row.get("eligible") else "NO",
                    "Reason": row.get("reason"),
                }
                for row in sorted(
                    current_selection,
                    key=lambda item: int(item.get("candidate_rank") or 999),
                )
            ]),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Every candidate is evaluated independently. RB-1.5.0 then admits the strongest qualified "
            "candidates through the Portfolio Risk Manager; Rank #1 is priority only, not an execution gate."
        )
    elif latest_signal:
        st.info(
            "Performance selection is awaiting foreground candidate evaluation "
            "for this confirmed signal."
        )
    else:
        st.caption("Performance selection is waiting for a confirmed Red Bar.")

    st.markdown("### Institutional Execution Committee")
    committee_rows = (
        database.read_institutional_execution_evaluations(
            signal_id=(str(latest_signal.get("signal_id")) if latest_signal else None),
            limit=25,
        )
        if latest_signal else []
    )
    if committee_rows:
        newest_committee_time = committee_rows[0].get("evaluated_at")
        current_committee = [
            row for row in committee_rows
            if row.get("evaluated_at") == newest_committee_time
        ]
        approved = sum(bool(row.get("eligible")) for row in current_committee)
        positive_ev = sum(float(row.get("expected_value_pct") or 0.0) > 0 for row in current_committee)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Candidates", len(current_committee))
        c2.metric("Committee Approved", approved)
        c3.metric("Positive Expectancy", positive_ev)
        best_prob = max(
            (float(row.get("execution_probability_pct") or 0.0) for row in current_committee),
            default=0.0,
        )
        c4.metric("Best Est. Probability", f"{best_prob:.1f}%")

        st.dataframe(
            _arrow_safe_rows([
                {
                    "Rank": row.get("candidate_rank"),
                    "Candidate": row.get("candidate_symbol"),
                    "Primary %": row.get("primary_confidence_pct") if row.get("primary_confidence_pct") is not None else row.get("rule_quality_score"),
                    "Shadow": row.get("shadow_decision"),
                    "Shadow %": row.get("shadow_confidence_pct"),
                    "Agreement": row.get("agreement"),
                    "Shadow Adj": row.get("shadow_adjustment_pct"),
                    "Final Confidence %": row.get("execution_probability_pct"),
                    "Expectancy %": row.get("expectancy_pct") if row.get("expectancy_pct") is not None else row.get("expected_value_pct"),
                    "Expected Win %": row.get("expected_win_pct"),
                    "Expected Loss %": row.get("expected_loss_pct"),
                    "Intelligence": row.get("intelligence_score"),
                    "Rule Quality": row.get("rule_quality_score"),
                    "Opportunity": row.get("opportunity_score"),
                    "Historical": row.get("historical_score"),
                    "TSS": row.get("selection_score"),
                    "History Weight %": row.get("adaptive_history_weight_pct"),
                    "Execute": "YES" if row.get("eligible") else "NO",
                    "Decision": row.get("decision"),
                    "Reason": row.get("reason"),
                }
                for row in sorted(
                    current_committee,
                    key=lambda item: int(item.get("candidate_rank") or 999),
                )
            ]),
            width="stretch",
            hide_index=True,
        )

        selected_committee = max(
            current_committee,
            key=lambda row: float(row.get("expected_value_pct") or -999.0),
        )
        expert_votes = selected_committee.get("expert_votes") or []
        if expert_votes:
            with st.expander(
                f"Primary Decision + Shadow Information · {selected_committee.get('candidate_symbol')}",
                expanded=True,
            ):
                st.dataframe(
                    _arrow_safe_rows([
                        {
                            "Expert": item.get("expert"),
                            "Vote Score %": item.get("score"),
                            "Weight %": item.get("effective_weight"),
                            "Contribution pts": item.get("contribution"),
                            "Source": item.get("source"),
                            "Detail": item.get("detail"),
                        }
                        for item in expert_votes
                    ]),
                    width="stretch",
                    hide_index=True,
                )
                st.caption(
                    "The Primary Rule Engine supplies the authoritative execution confidence. Shadow Intelligence is informational-only "
                    "with zero execution weight, bonus, or penalty."
                )

        modules = selected_committee.get("modules") or []
        if modules:
            with st.expander(
                f"Adaptive intelligence weights · {selected_committee.get('candidate_symbol')}",
                expanded=False,
            ):
                st.dataframe(
                    _arrow_safe_rows([
                        {
                            "Module": item.get("module"),
                            "Current": item.get("current_recommendation"),
                            "Support": item.get("current_support"),
                            "Confidence %": item.get("current_confidence"),
                            "Historical Samples": item.get("supportive_samples"),
                            "Historical Win Rate %": item.get("win_rate_pct"),
                            "Reliability": item.get("reliability_score"),
                            "Adaptive Weight %": item.get("adaptive_weight"),
                        }
                        for item in modules
                    ]),
                    width="stretch",
                    hide_index=True,
                )
        st.caption(
            "RB-1.0.0 committee approval requires no hard execution-quality/safety blocker, "
            "an estimated execution probability of at least 70%, and positive expected value. "
            "TSS/history remain evidence. Signal age is informational; Opportunity Health is current-market evidence. "
            "Portfolio risk/capital controls how many committee-qualified trades enter simultaneously."
        )
    elif latest_signal:
        st.info(
            "Institutional Execution Committee is awaiting foreground evaluation. "
            "It no longer depends on the background monitor to make the decision."
        )
    else:
        st.caption("Execution Committee is waiting for a confirmed Red Bar.")

    st.markdown("### Execution Queue")
    queue_rows = database.read_execution_queue(
        signal_id=(str(latest_signal.get("signal_id")) if latest_signal else None),
        limit=50,
    ) if latest_signal else []
    if queue_rows:
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Portfolio Approved", sum(str(r.get("status")) == "APPROVED" for r in queue_rows))
        q2.metric("Executing / Active", sum(str(r.get("status")) in {"EXECUTING", "ACTIVE"} for r in queue_rows))
        q3.metric("Watchlist / Waiting", sum(str(r.get("status")) in {"WAITING", "QUALIFIED"} for r in queue_rows))
        q4.metric("Rejected", sum(str(r.get("status")) == "REJECTED" for r in queue_rows))
        st.dataframe(
            _arrow_safe_rows([
                {
                    "Rank": row.get("candidate_rank"),
                    "Candidate": row.get("candidate_symbol"),
                    "Probability %": row.get("execution_probability_pct"),
                    "EV %": row.get("expected_value_pct"),
                    "TSS": row.get("selection_score"),
                    "Status": row.get("status"),
                    "Reason": row.get("reason"),
                    "Order": row.get("order_id") or "—",
                    "Updated": row.get("updated_at"),
                }
                for row in queue_rows
            ]),
            width="stretch", hide_index=True,
        )
        st.caption(
            "The Committee qualifies trades; the RB-1.5.0 Portfolio Risk Manager chooses multiple best candidates "
            "that fit current open-trade, same-direction, capital and risk budgets. Non-admitted qualified trades stay on the watchlist."
        )
    elif latest_signal:
        st.info("Execution Queue is waiting for the foreground committee evaluation.")
    else:
        st.caption("Execution Queue is waiting for a confirmed Red Bar.")

    st.markdown("### Trade Lifecycle / Decision Replay")
    lifecycle_rows = database.read_execution_state_events(
        signal_id=(str(latest_signal.get("signal_id")) if latest_signal else None),
        limit=100,
    ) if latest_signal else []
    if lifecycle_rows:
        st.dataframe(
            _arrow_safe_rows([
                {
                    "Time": row.get("timestamp"),
                    "State": row.get("state"),
                    "Order": row.get("order_id") or "—",
                    "Score": row.get("candidate_score"),
                    "Detail": row.get("detail"),
                }
                for row in reversed(lifecycle_rows)
            ]),
            width="stretch", hide_index=True,
        )
        st.caption(
            "This persisted timeline is the foundation for Decision Replay: signal → "
            "candidate → committee → queue → execution → protection → exit."
        )
    elif latest_signal:
        st.info("Lifecycle events will appear as this signal moves through the decision pipeline.")
    else:
        st.caption("Decision Replay is waiting for a confirmed Red Bar.")

    _perf_mark("Market / account / Red Bar")

    # ---------- Rule-based ranking ----------
    st.markdown("### Top CE / PE Candidates")
    st.caption(
        "The ranking uses spread, liquidity, volume, OI, option VWAP, "
        "EMA9/EMA21 and momentum. Ranking is discovery order only: automatic "
        "paper execution is now decided independently for every candidate by "
        "Performance Trade Selection."
    )

    default_direction = (
        latest_direction
        if latest_direction in {"BULLISH", "BEARISH"}
        else "BULLISH"
    )
    rank_controls = st.columns(4)
    with rank_controls[0]:
        selected_direction = st.radio(
            "Direction",
            ("BULLISH", "BEARISH"),
            index=0 if default_direction == "BULLISH" else 1,
            horizontal=True,
            key="paper_direction",
        )
    with rank_controls[1]:
        auto_min_score = st.number_input(
            "Minimum Score",
            min_value=0.0,
            max_value=100.0,
            value=65.0,
            step=1.0,
            key="paper_auto_min_score",
        )
    with rank_controls[2]:
        auto_lots = st.number_input(
            "Lots",
            min_value=1,
            max_value=20,
            value=1,
            step=1,
            key="paper_auto_lots",
        )
    with rank_controls[3]:
        refresh_candidates = st.button(
            "Refresh & Rank Candidates",
            key="paper_rank_candidates",
            disabled=not paper_data_ready,
        )

    ranked_rows = st.session_state.get(
        "paper_ranked_candidates", []
    )
    ranked_contracts = st.session_state.get(
        "paper_ranked_contracts", []
    )
    last_ranked_direction = st.session_state.get(
        "paper_ranked_direction"
    )
    last_ranked_at = st.session_state.get("paper_ranked_at")
    rank_age_seconds = None
    if last_ranked_at:
        try:
            last_rank_ts = datetime.fromisoformat(
                str(last_ranked_at)
            )
            if last_rank_ts.tzinfo is None:
                last_rank_ts = last_rank_ts.replace(
                    tzinfo=ZoneInfo("Asia/Kolkata")
                )
            rank_age_seconds = (
                datetime.now(ZoneInfo("Asia/Kolkata")) - last_rank_ts
            ).total_seconds()
        except Exception:
            rank_age_seconds = None

    auto_rank_due = bool(
        paper_data_ready
        and (
            not ranked_rows
            or last_ranked_direction != selected_direction
            or (
                auto_refresh
                and (
                    rank_age_seconds is None
                    or rank_age_seconds >= 55
                )
            )
        )
    )
    should_rank = bool(refresh_candidates or auto_rank_due)

    if paper_data_ready and should_rank:
        try:
            automation = RedBarPaperAutomationService(
                zerodha=paper_market,
                database=database,
                settings=settings,
                underlying_name=underlying_name,
                initial_capital=float(paper_capital),
                minimum_candidate_score=float(auto_min_score),
            )
            spot = (
                float(intelligence_snapshot.spot_price)
                if intelligence_snapshot
                and intelligence_snapshot.spot_price is not None
                else None
            )
            if spot is None:
                raise ValueError("Underlying spot price is unavailable.")

            scores = automation.score_candidates(
                direction=selected_direction,
                spot_price=spot,
            )
            ranked_rows = []
            ranked_contracts = []
            for rank, score in enumerate(scores, start=1):
                contract = score.contract
                q = paper_market.quote(
                    [f"{contract.exchange}:{contract.tradingsymbol}"]
                ).get(
                    f"{contract.exchange}:{contract.tradingsymbol}",
                    {},
                )
                ranked_rows.append(
                    {
                        "Rank": rank,
                        "Option": contract.tradingsymbol,
                        "Type": contract.option_type,
                        "Strike": contract.strike,
                        "Score": score.total_score,
                        "LTP": score.ltp,
                        "Bid": score.best_bid,
                        "Ask": score.best_ask,
                        "Spread Score": score.spread_score,
                        "Liquidity": score.liquidity_score,
                        "Volume Score": score.volume_score,
                        "OI Score": score.oi_score,
                        "VWAP Score": score.vwap_score,
                        "EMA Score": score.ema_score,
                        "Momentum": score.momentum_score,
                        "Momentum %": score.momentum_pct,
                        "Candle Bars": score.candle_count,
                        "Delta": q.get("delta"),
                        "Gamma": q.get("gamma"),
                        "IV": q.get("iv"),
                        "Theta": q.get("theta"),
                        "Vega": q.get("vega"),
                        "Decision": (
                            "PAPER BUY"
                            if score.total_score >= float(auto_min_score)
                            else "WAIT"
                        ),
                    }
                )
                ranked_contracts.append(
                    {
                        "instrument_token": contract.instrument_token,
                        "tradingsymbol": contract.tradingsymbol,
                        "exchange": contract.exchange,
                        "option_type": contract.option_type,
                        "strike": contract.strike,
                        "expiry": str(contract.expiry),
                        "lot_size": contract.lot_size,
                    }
                )
            st.session_state["paper_ranked_candidates"] = ranked_rows
            st.session_state["paper_ranked_contracts"] = ranked_contracts
            st.session_state["paper_ranked_direction"] = selected_direction
            st.session_state["paper_ranked_at"] = datetime.now(
                ZoneInfo("Asia/Kolkata")
            ).isoformat()
        except Exception as exc:
            st.exception(exc)

    if ranked_rows:
        best = ranked_rows[0]
        entry_reference = float(
            best.get("Ask") or best.get("LTP") or 0.0
        )
        paper_stop = (
            round(entry_reference * 0.85, 2)
            if entry_reference > 0 else None
        )
        paper_target1 = (
            round(entry_reference * 1.25, 2)
            if entry_reference > 0 else None
        )
        paper_target2 = (
            round(entry_reference * 1.40, 2)
            if entry_reference > 0 else None
        )
        rule_score = float(best.get("Score") or 0.0)
        spread_component = float(
            best.get("Spread Score") or 0.0
        )
        liquidity_component = float(
            best.get("Liquidity") or 0.0
        )
        risk_band = (
            "LOW"
            if rule_score >= 85
            and spread_component >= 12
            and liquidity_component >= 15
            else "MEDIUM"
            if rule_score >= 75
            else "HIGH"
        )
        trade_status = (
            "READY"
            if best.get("Decision") == "PAPER BUY"
            and latest_direction in {"BULLISH", "BEARISH"}
            else "WAIT"
        )
        trade_side = (
            "BUY CE"
            if best.get("Type") == "CE"
            else "BUY PE"
        )

        st.markdown("### Trader Recommendation")
        tr1, tr2, tr3, tr4 = st.columns(4)
        tr1.metric("Action", trade_side)
        tr2.metric("Contract", best.get("Option") or "—")
        tr3.metric("Rule Confidence", f"{rule_score:.1f}%")
        tr4.metric("Status", trade_status)

        tr5, tr6, tr7, tr8, tr9 = st.columns(5)
        tr5.metric(
            "Entry Reference",
            f"₹{entry_reference:.2f}"
            if entry_reference > 0 else "—",
        )
        tr6.metric(
            "Paper Stop",
            f"₹{paper_stop:.2f}"
            if paper_stop is not None else "—",
        )
        tr7.metric(
            "Target 1",
            f"₹{paper_target1:.2f}"
            if paper_target1 is not None else "—",
        )
        tr8.metric(
            "Target 2*",
            f"₹{paper_target2:.2f}"
            if paper_target2 is not None else "—",
        )
        tr9.metric("Risk", risk_band)
        st.caption(
            "*Target 2 is informational in RB-0.7.4.9. "
            "The automatic paper engine currently executes its configured "
            "SL / Target 1 / EOD policy. Holding time is not estimated "
            "until we have enough completed paper evidence."
        )

    else:
        st.info(
            "Click 'Refresh & Rank Candidates' during a valid Upstox "
            "session to populate the CE/PE ranking."
        )

    # Rank is discovery order only in RB-0.9.3; committee/queue owns execution.
    current_best = ranked_rows[0] if ranked_rows else None

    _render_candidate_workbench_fragment(
        ranked_rows,
        ranked_contracts,
        paper_engine,
        paper_market,
        today_text,
        paper_data_ready,
        st.session_state.get("paper_ranked_at"),
        database,
        intelligence_snapshot,
        latest_signal,
        latest_direction,
        market_open,
        float(auto_min_score),
        open_orders,
    )

    _perf_mark("Candidate ranking + analysis")

    # ---------- Automated lifecycle ----------
    st.markdown("### Paper Execution")
    exec_cols = st.columns(3)
    with exec_cols[0]:
        if st.button(
            "Run Automatic Paper Cycle Now",
            key="run_automatic_paper_cycle",
            disabled=not paper_data_ready,
        ):
            try:
                automation = RedBarPaperAutomationService(
                    zerodha=paper_market,
                    database=database,
                    settings=settings,
                    underlying_name=underlying_name,
                    initial_capital=float(paper_capital),
                    minimum_candidate_score=float(auto_min_score),
                )
                auto_report = automation.run_cycle(
                    trading_date=today_text,
                    lots=int(auto_lots),
                )
                st.success(
                    "Automatic paper cycle completed: "
                    f"opened={auto_report.paper_orders_opened}, "
                    f"closed={auto_report.paper_orders_closed}, "
                    f"skipped={auto_report.skipped}."
                )
                if auto_report.errors:
                    st.warning(" | ".join(auto_report.errors[:5]))
                st.rerun()
            except Exception as exc:
                st.exception(exc)

    with exec_cols[1]:
        if st.button(
            "Refresh Open Positions",
            key="refresh_paper_positions",
            disabled=not paper_data_ready,
        ):
            try:
                paper_engine.refresh_open_positions(
                    zerodha=paper_market
                )
                st.success("Virtual positions marked from Upstox.")
                st.rerun()
            except Exception as exc:
                st.exception(exc)

    with exec_cols[2]:
        st.metric(
            "Auto Exit",
            "SL / BE / TRAIL / THESIS / TECH / TARGET / EOD",
        )

    # ---------- Manual virtual entry for validation ----------
    if ranked_rows and ranked_contracts:
        with st.expander(
            "Manual Paper Entry / Validation",
            expanded=False,
        ):
            symbols = [
                str(row["tradingsymbol"])
                for row in ranked_contracts
            ]
            chosen_symbol = st.selectbox(
                "Contract",
                symbols,
                key="paper_selected_contract",
            )
            selected_dict = next(
                row for row in ranked_contracts
                if row["tradingsymbol"] == chosen_symbol
            )
            selected_contract = PaperContract(
                instrument_token=int(
                    selected_dict["instrument_token"]
                ),
                tradingsymbol=str(
                    selected_dict["tradingsymbol"]
                ),
                exchange=str(selected_dict["exchange"]),
                option_type=str(selected_dict["option_type"]),
                strike=float(selected_dict["strike"]),
                expiry=date.fromisoformat(
                    str(selected_dict["expiry"])
                ),
                lot_size=int(selected_dict["lot_size"]),
            )
            quantity = int(auto_lots) * selected_contract.lot_size

            qrow = next(
                row for row in ranked_rows
                if row["Option"] == chosen_symbol
            )
            reference = float(
                qrow.get("Ask")
                or qrow.get("LTP")
                or 0.0
            )
            default_stop = (
                round(reference * 0.85, 2)
                if reference > 0 else 0.0
            )
            default_target = (
                round(reference * 1.25, 2)
                if reference > 0 else 0.0
            )
            mc1, mc2, mc3 = st.columns(3)
            with mc1:
                manual_stop = st.number_input(
                    "Paper Stop",
                    min_value=0.0,
                    value=float(default_stop),
                    step=0.05,
                    key="paper_manual_stop",
                )
            with mc2:
                manual_target = st.number_input(
                    "Paper Target",
                    min_value=0.0,
                    value=float(default_target),
                    step=0.05,
                    key="paper_manual_target",
                )
            with mc3:
                st.metric("Quantity", quantity)

            if st.button(
                "Open Virtual Position",
                key="paper_manual_open",
                disabled=not paper_data_ready,
            ):
                try:
                    opened = paper_engine.open_long_option(
                        zerodha=paper_market,
                        contract=selected_contract,
                        quantity=quantity,
                        signal_id=(
                            str(latest_signal.get("signal_id"))
                            if latest_signal else None
                        ),
                        underlying_name=underlying_name,
                        underlying_price=(
                            float(intelligence_snapshot.spot_price)
                            if intelligence_snapshot
                            and intelligence_snapshot.spot_price
                            is not None
                            else None
                        ),
                        stop_price=(
                            float(manual_stop)
                            if manual_stop > 0 else None
                        ),
                        target1_price=(
                            float(manual_target)
                            if manual_target > 0 else None
                        ),
                        reason="MANUAL_COMMAND_CENTER_PAPER_ENTRY",
                    )
                    st.success(
                        f"Virtual BUY {opened.get('tradingsymbol')} @ "
                        f"₹{float(opened.get('entry_price')):.2f}"
                    )
                    st.rerun()
                except Exception as exc:
                    st.exception(exc)

    # Refresh data after potential actions.
    open_orders = database.read_open_paper_execution_orders(
        "PAPER-STD"
    )
    all_paper_orders = database.read_paper_execution_orders(
        "PAPER-STD"
    )
    closed_orders = [
        row for row in all_paper_orders
        if row.get("status") == "CLOSED"
    ]

    # RB-1.3.2 performance: preload signal metadata once for the rows rendered on
    # the normal page path. Lifecycle can extend this lookup lazily below.
    visible_signal_ids = {
        str(row.get("signal_id") or "")
        for row in (list(open_orders) + list(closed_orders[:200]))
        if row.get("signal_id")
    }
    signal_meta_by_id = database.read_signal_attempts_by_ids(visible_signal_ids)

    # ---------- Trade lifecycle and provenance ----------
    show_trade_lifecycle = st.toggle(
        "Load Trade Lifecycle & Provenance",
        value=False,
        key="paper_load_trade_lifecycle",
        help=(
            "Loads detailed per-trade signal and event history only when needed."
        ),
    )
    if show_trade_lifecycle:
        st.markdown("### Trade Lifecycle & Provenance")
        lifecycle_signal_ids = {
            str(row.get("signal_id") or "")
            for row in all_paper_orders
            if row.get("signal_id")
        }
        missing_signal_ids = lifecycle_signal_ids.difference(signal_meta_by_id)
        if missing_signal_ids:
            signal_meta_by_id.update(
                database.read_signal_attempts_by_ids(missing_signal_ids)
            )
        events_by_signal = database.read_execution_state_events_for_signals(
            lifecycle_signal_ids, per_signal_limit=50
        )
        lifecycle_rows = []
        for row in all_paper_orders:
            signal_id = str(row.get("signal_id") or "")
            signal_meta = signal_meta_by_id.get(signal_id) if signal_id else None
            events = events_by_signal.get(signal_id, []) if signal_id else []
            event_states = [
                str(item.get("state") or "")
                for item in reversed(events)
            ]

            entry_reason = str(row.get("entry_reason") or "")
            if entry_reason.startswith("AUTO_"):
                execution_source = "AUTO PAPER"
            elif "MANUAL" in entry_reason:
                execution_source = "MANUAL PAPER"
            else:
                execution_source = (
                    row.get("execution_provider")
                    or "PAPER"
                )

            status = str(row.get("status") or "")
            realized = float(row.get("realized_pnl") or 0.0)
            unrealized = float(row.get("unrealized_pnl") or 0.0)
            if status == "CLOSED":
                result = (
                    "PROFIT" if realized > 0
                    else "LOSS" if realized < 0
                    else "BREAKEVEN"
                )
                current_lifecycle = (
                    "CLOSED_PROFIT" if realized > 0
                    else "CLOSED_LOSS" if realized < 0
                    else "CLOSED_BREAKEVEN"
                )
            else:
                result = "OPEN"
                current_lifecycle = (
                    event_states[-1]
                    if event_states else "MONITORING"
                )

            execution_delay_text = "—"
            if (
                signal_meta
                and signal_meta.get("confirmation_timestamp")
                and row.get("entry_timestamp")
            ):
                try:
                    signal_time_value = datetime.fromisoformat(
                        str(signal_meta.get("confirmation_timestamp"))
                    )
                    entry_time_value = datetime.fromisoformat(
                        str(row.get("entry_timestamp"))
                    )
                    execution_delay_text = (
                        f"{max(0.0, (entry_time_value - signal_time_value).total_seconds()):.1f}s"
                    )
                except Exception:
                    execution_delay_text = "—"

            holding_text = "—"
            try:
                entry_ts = datetime.fromisoformat(
                    str(row.get("entry_timestamp"))
                )
                exit_raw = row.get("exit_timestamp")
                end_ts = (
                    datetime.fromisoformat(str(exit_raw))
                    if exit_raw
                    else datetime.now(ZoneInfo("Asia/Kolkata"))
                )
                if entry_ts.tzinfo is None:
                    entry_ts = entry_ts.replace(
                        tzinfo=ZoneInfo("Asia/Kolkata")
                    )
                if end_ts.tzinfo is None:
                    end_ts = end_ts.replace(
                        tzinfo=ZoneInfo("Asia/Kolkata")
                    )
                holding_seconds = max(
                    0.0,
                    (end_ts - entry_ts).total_seconds(),
                )
                holding_text = (
                    f"{int(holding_seconds // 60)}m "
                    f"{int(holding_seconds % 60)}s"
                )
            except Exception:
                pass

            lifecycle_rows.append(
                {
                    "Trade": row.get("order_id"),
                    "Signal": signal_id or "—",
                    "Signal Type": (
                        signal_meta.get("level_type")
                        if signal_meta else "—"
                    ),
                    "Direction": (
                        signal_meta.get("direction")
                        if signal_meta else "—"
                    ),
                    "Signal Time": (
                        signal_meta.get("confirmation_timestamp")
                        if signal_meta else "—"
                    ),
                    "Execution Delay": execution_delay_text,
                    "Opened By": execution_source,
                    "Option": row.get("tradingsymbol"),
                    "Entry Time": row.get("entry_timestamp"),
                    "Entry": row.get("entry_price"),
                    "Current / Exit": (
                        row.get("exit_price")
                        if status == "CLOSED"
                        else row.get("current_price")
                    ),
                    "P&L ₹": (
                        realized if status == "CLOSED"
                        else unrealized
                    ),
                    "Result": result,
                    "Lifecycle": current_lifecycle,
                    "Exit Reason": row.get("exit_reason"),
                    "Holding": holding_text,
                }
            )

        if lifecycle_rows:
            st.dataframe(
                _arrow_safe_rows(lifecycle_rows),
                width="stretch",
                hide_index=True,
            )

            lifecycle_trade_ids = [
                str(row["Trade"]) for row in lifecycle_rows
            ]
            selected_lifecycle_trade = st.selectbox(
                "Inspect Trade Lifecycle",
                lifecycle_trade_ids,
                key="paper_lifecycle_trade",
            )
            selected_lifecycle_order = (
                database.read_paper_execution_order(
                    selected_lifecycle_trade
                )
            )
            selected_signal_id = (
                str(selected_lifecycle_order.get("signal_id") or "")
                if selected_lifecycle_order else ""
            )
            selected_signal_meta = (
                signal_meta_by_id.get(selected_signal_id)
                if selected_signal_id else None
            )

            if selected_lifecycle_order:
                prov_cols = st.columns(7)
                prov_cols[0].metric(
                    "Signal",
                    selected_signal_id or "—",
                )
                prov_cols[1].metric(
                    "Signal Type",
                    (
                        selected_signal_meta.get("level_type")
                        if selected_signal_meta else "—"
                    ),
                )
                prov_cols[2].metric(
                    "Direction",
                    (
                        selected_signal_meta.get("direction")
                        if selected_signal_meta else "—"
                    ),
                )
                prov_cols[3].metric(
                    "Option",
                    selected_lifecycle_order.get(
                        "tradingsymbol"
                    ) or "—",
                )
                source_reason = str(
                    selected_lifecycle_order.get(
                        "entry_reason"
                    ) or ""
                )
                prov_cols[4].metric(
                    "Opened By",
                    (
                        "AUTO PAPER"
                        if source_reason.startswith("AUTO_")
                        else "MANUAL PAPER"
                        if "MANUAL" in source_reason
                        else "PAPER"
                    ),
                )
                trade_realized = float(
                    selected_lifecycle_order.get(
                        "realized_pnl"
                    ) or 0.0
                )
                trade_unrealized = float(
                    selected_lifecycle_order.get(
                        "unrealized_pnl"
                    ) or 0.0
                )
                prov_cols[5].metric(
                    "P&L",
                    (
                        f"₹{trade_realized:+,.2f}"
                        if selected_lifecycle_order.get(
                            "status"
                        ) == "CLOSED"
                        else f"₹{trade_unrealized:+,.2f}"
                    ),
                )
                prov_cols[6].metric(
                    "Status",
                    selected_lifecycle_order.get(
                        "status"
                    ) or "—",
                )

                st.markdown("#### Trade Timeline")
                timeline_events = (
                    database.read_execution_state_events(
                        signal_id=selected_signal_id,
                        limit=100,
                    )
                    if selected_signal_id else []
                )
                marks = database.read_paper_execution_marks(
                    selected_lifecycle_trade
                )
                timeline_rows = []

                if selected_signal_meta:
                    timeline_rows.append(
                        {
                            "Time": selected_signal_meta.get(
                                "confirmation_timestamp"
                            ),
                            "Stage": "SIGNAL_CONFIRMED",
                            "Detail": (
                                f"{selected_signal_meta.get('level_type')} · "
                                f"{selected_signal_meta.get('direction')}"
                            ),
                            "Price / P&L": (
                                selected_signal_meta.get(
                                    "underlying_entry"
                                )
                            ),
                        }
                    )

                for event in reversed(timeline_events):
                    timeline_rows.append(
                        {
                            "Time": event.get("timestamp"),
                            "Stage": event.get("state"),
                            "Detail": event.get("detail"),
                            "Price / P&L": event.get(
                                "candidate_score"
                            ),
                        }
                    )

                for mark in marks:
                    if mark.get("event_type") in {
                        "ENTRY", "EXIT"
                    }:
                        timeline_rows.append(
                            {
                                "Time": mark.get("timestamp"),
                                "Stage": (
                                    "PAPER_ENTRY"
                                    if mark.get("event_type")
                                    == "ENTRY"
                                    else "PAPER_EXIT"
                                ),
                                "Detail": (
                                    f"Option price "
                                    f"{mark.get('price')}"
                                ),
                                "Price / P&L": mark.get(
                                    "unrealized_pnl"
                                ),
                            }
                        )

                timeline_rows = sorted(
                    timeline_rows,
                    key=lambda item: str(
                        item.get("Time") or ""
                    ),
                )
                if timeline_rows:
                    st.dataframe(
                        _arrow_safe_rows(timeline_rows),
                        width="stretch",
                        hide_index=True,
                    )
        else:
            st.info(
                "No paper trades exist yet for lifecycle tracking."
            )

    else:
        st.caption(
            "Trade Lifecycle is lazy-loaded to keep normal refreshes fast."
        )

    _perf_mark("Execution / lifecycle")

    # ---------- Open trade ----------
    st.markdown("### Open Paper Position")
    if open_orders:
        open_display = []
        for row in open_orders:
            entry = float(row.get("entry_price") or 0.0)
            current = float(
                row.get("current_price") or entry
            )
            open_signal_id = str(
                row.get("signal_id") or ""
            )
            open_signal_meta = (
                signal_meta_by_id.get(open_signal_id)
                if open_signal_id else None
            )
            open_reason = str(
                row.get("entry_reason") or ""
            )
            open_display.append(
                {
                    "Order": row.get("order_id"),
                    "Signal": row.get("signal_id"),
                    "Signal Type": (
                        open_signal_meta.get("level_type")
                        if open_signal_meta else "—"
                    ),
                    "Direction": (
                        open_signal_meta.get("direction")
                        if open_signal_meta else "—"
                    ),
                    "Opened By": (
                        "AUTO PAPER"
                        if open_reason.startswith("AUTO_")
                        else "MANUAL PAPER"
                        if "MANUAL" in open_reason
                        else "PAPER"
                    ),
                    "Entry Mode": (
                        row.get("entry_mode")
                        or (
                            "OPPORTUNITY_EXTENSION"
                            if "OPPORTUNITY_EXTENSION" in open_reason
                            else "FRESH_SIGNAL"
                            if open_reason.startswith("AUTO_")
                            else "MANUAL"
                        )
                    ),
                    "Signal Age": row.get("signal_age_at_entry"),
                    "Opportunity": row.get("opportunity_score"),
                    "Reward Remaining %": row.get(
                        "reward_remaining_pct"
                    ),
                    "Option": row.get("tradingsymbol"),
                    "Type": row.get("option_type"),
                    "Strike": row.get("strike"),
                    "Entry Time": row.get("entry_timestamp"),
                    "Entry": entry,
                    "Current": current,
                    "Points": current - entry,
                    "P&L ₹": row.get("unrealized_pnl"),
                    "MFE": row.get("mfe_points"),
                    "MAE": row.get("mae_points"),
                    "Stop": row.get("stop_price"),
                    "Target": row.get("target1_price"),
                    "Status": row.get("status"),
                }
            )
        st.dataframe(
            _arrow_safe_rows(open_display),
            width="stretch",
            hide_index=True,
        )

        open_ids = [
            str(row["order_id"]) for row in open_orders
        ]
        selected_open_id = st.selectbox(
            "Position to inspect",
            open_ids,
            key="paper_open_inspect",
        )
        selected_open = database.read_paper_execution_order(
            selected_open_id
        )
        if selected_open:
            entry = float(
                selected_open.get("entry_price") or 0.0
            )
            current = float(
                selected_open.get("current_price") or entry
            )
            position_cols = st.columns(7)
            position_cols[0].metric(
                "Option",
                selected_open.get("tradingsymbol") or "—",
            )
            position_cols[1].metric("Entry", f"₹{entry:.2f}")
            position_cols[2].metric("Current", f"₹{current:.2f}")
            position_cols[3].metric(
                "P&L",
                f"₹{float(selected_open.get('unrealized_pnl') or 0):+,.2f}",
            )
            position_cols[4].metric(
                "MFE",
                f"{float(selected_open.get('mfe_points') or 0):+.2f}",
            )
            position_cols[5].metric(
                "MAE",
                f"{float(selected_open.get('mae_points') or 0):+.2f}",
            )
            position_cols[6].metric(
                "Status",
                selected_open.get("status") or "—",
            )

            _render_paper_exit_engine_panel(
                position=selected_open,
                paper_engine=paper_engine,
                paper_market=paper_market,
                database=database,
                intelligence_snapshot=intelligence_snapshot,
                instrument_key=instrument_key,
                today_text=today_text,
            )

            if st.button(
                "Close Selected Virtual Position",
                key="paper_close_selected",
                disabled=not paper_data_ready,
            ):
                try:
                    closed = paper_engine.close_position(
                        zerodha=paper_market,
                        order_id=selected_open_id,
                        exit_reason="MANUAL_COMMAND_CENTER_EXIT",
                    )
                    st.success(
                        f"Virtual position closed @ "
                        f"₹{float(closed.get('exit_price')):.2f}; "
                        f"P&L ₹"
                        f"{float(closed.get('realized_pnl')):+,.2f}"
                    )
                    st.rerun()
                except Exception as exc:
                    st.exception(exc)

            # Actual selected CE/PE candles.
            st.markdown("### Selected Option Candle")
            if paper_data_ready:
                try:
                    candle_frame = paper_engine.option_candles(
                        zerodha=paper_market,
                        instrument_token=int(
                            selected_open["instrument_token"]
                        ),
                        date_from=today_text,
                        date_to=today_text,
                        interval="minute",
                    )
                    if not candle_frame.empty:
                        chart = candle_frame.set_index(
                            "timestamp"
                        )[
                            ["close", "ema9", "ema21", "vwap"]
                        ]
                        st.line_chart(
                            chart,
                            width="stretch",
                        )
                        last = candle_frame.iloc[-1]
                        candle_cols = st.columns(5)
                        candle_cols[0].metric(
                            "Option Close",
                            f"{float(last.get('close') or 0):.2f}",
                        )
                        candle_cols[1].metric(
                            "VWAP",
                            f"{float(last.get('vwap') or 0):.2f}",
                        )
                        candle_cols[2].metric(
                            "EMA9",
                            f"{float(last.get('ema9') or 0):.2f}",
                        )
                        candle_cols[3].metric(
                            "EMA21",
                            f"{float(last.get('ema21') or 0):.2f}",
                        )
                        candle_cols[4].metric(
                            "Volume",
                            int(last.get("volume") or 0),
                        )
                    else:
                        st.info(
                            "No Upstox option candles available yet."
                        )
                except Exception as exc:
                    st.warning(
                        f"Option candle unavailable: {exc}"
                    )
    else:
        st.info("No open virtual paper position.")
        _render_paper_exit_engine_idle_panel()

    # ---------- Evidence breakdown ----------
    st.markdown("### Why This Option? — Execution Candidate Evidence (Rank #1)")
    if ranked_rows:
        top = ranked_rows[0]
        evidence = [
            {
                "Evidence": "Bid/Ask Spread",
                "Score": top.get("Spread Score"),
                "Maximum": 15,
            },
            {
                "Evidence": "Liquidity",
                "Score": top.get("Liquidity"),
                "Maximum": 20,
            },
            {
                "Evidence": "Volume",
                "Score": top.get("Volume Score"),
                "Maximum": 15,
            },
            {
                "Evidence": "Open Interest",
                "Score": top.get("OI Score"),
                "Maximum": 10,
            },
            {
                "Evidence": "Above VWAP",
                "Score": top.get("VWAP Score"),
                "Maximum": 10,
            },
            {
                "Evidence": "EMA9 / EMA21",
                "Score": top.get("EMA Score"),
                "Maximum": 10,
            },
            {
                "Evidence": "Momentum",
                "Score": top.get("Momentum"),
                "Maximum": 10,
            },
        ]
        st.dataframe(
            _arrow_safe_rows(evidence),
            width="stretch",
            hide_index=True,
        )
        ev1, ev2, ev3, ev4, ev5 = st.columns(5)
        ev1.metric("Delta", top.get("Delta") or "—")
        ev2.metric("Gamma", top.get("Gamma") or "—")
        ev3.metric("IV", top.get("IV") or "—")
        ev4.metric("Theta", top.get("Theta") or "—")
        ev5.metric("Vega", top.get("Vega") or "—")
        st.caption(
            "Greeks remain informational/shadow evidence. "
            "They are not yet included in the rule score."
        )
    else:
        st.caption(
            "Candidate evidence appears after ranking CE/PE contracts."
        )

    show_advanced_audit = st.toggle(
        "Load Advanced Diagnostics, Timeline & Journal",
        value=False,
        key="paper_load_advanced_audit",
        help=(
            "Keeps expensive historical/audit queries out of the normal "
            "market refresh path."
        ),
    )
    if show_advanced_audit:
        _perf_mark("Open position + exit engine")

    # ---------- Automation diagnostics ----------
        st.markdown("### Why Was / Wasn't a Paper Trade Executed?")
        diagnostic_rows = database.read_paper_signal_diagnostics(
            limit=50
        )
        if diagnostic_rows:
            diagnostic_display = [
                {
                    "Time": row.get("timestamp"),
                    "Signal": row.get("signal_id"),
                    "Signal State": row.get("signal_state"),
                    "Direction": row.get("direction"),
                    "Age Sec": row.get("signal_age_seconds"),
                    "Market Hours": (
                        "PASS" if row.get("market_hours_ok") else "FAIL"
                    ),
                    "Fresh": (
                        "PASS" if row.get("freshness_ok") else "FAIL"
                    ),
                    "Duplicate Free": (
                        "PASS" if row.get("duplicate_free") else "FAIL"
                    ),
                    "Candidate": row.get("best_candidate"),
                    "Score": row.get("best_score"),
                    "Minimum": row.get("minimum_score"),
                    "Score Gate": (
                        "PASS" if row.get("score_ok") else "FAIL"
                    ),
                    "Decision": row.get("final_decision"),
                    "Reason": row.get("reason"),
                }
                for row in diagnostic_rows
            ]
            st.dataframe(
                _arrow_safe_rows(diagnostic_display),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "No automatic execution diagnostic scans are stored yet. "
                "The background paper monitor must be running."
            )

        # ---------- Execution timeline ----------
        st.markdown("### Execution Timeline")
        audit_rows = database.read_execution_state_events(limit=100)
        if audit_rows:
            timeline = [
                {
                    "Time": row.get("timestamp"),
                    "Signal": row.get("signal_id"),
                    "Order": row.get("order_id"),
                    "State": row.get("state"),
                    "Score": row.get("candidate_score"),
                    "Detail": row.get("detail"),
                }
                for row in audit_rows
            ]
            st.dataframe(
                _arrow_safe_rows(timeline),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "No automatic execution timeline events have been recorded yet."
            )

        # ---------- Journal and statistics ----------
        st.markdown("### Paper Trade Journal & Statistics")
        if closed_orders:
            pnl_values = [
                float(row.get("realized_pnl") or 0.0)
                for row in closed_orders
            ]
            winners = [value for value in pnl_values if value > 0]
            losers = [value for value in pnl_values if value < 0]
            win_rate = (
                len(winners) / len(pnl_values) * 100.0
                if pnl_values else 0.0
            )
            gross_profit = sum(winners)
            gross_loss = abs(sum(losers))
            profit_factor = (
                gross_profit / gross_loss
                if gross_loss > 0 else None
            )

            stat_cols = st.columns(6)
            stat_cols[0].metric("Closed", len(closed_orders))
            stat_cols[1].metric("Winners", len(winners))
            stat_cols[2].metric("Losers", len(losers))
            stat_cols[3].metric("Win Rate", f"{win_rate:.1f}%")
            stat_cols[4].metric(
                "Net Realized",
                f"₹{sum(pnl_values):+,.2f}",
            )
            stat_cols[5].metric(
                "Profit Factor",
                (
                    f"{profit_factor:.2f}"
                    if profit_factor is not None else "—"
                ),
            )

            journal = []
            for row in closed_orders[:200]:
                closed_signal_id = str(
                    row.get("signal_id") or ""
                )
                closed_signal_meta = (
                    signal_meta_by_id.get(closed_signal_id)
                    if closed_signal_id else None
                )
                closed_pnl = float(
                    row.get("realized_pnl") or 0.0
                )
                closed_reason = str(
                    row.get("entry_reason") or ""
                )
                closed_holding = "—"
                try:
                    c_entry = datetime.fromisoformat(
                        str(row.get("entry_timestamp"))
                    )
                    c_exit = datetime.fromisoformat(
                        str(row.get("exit_timestamp"))
                    )
                    seconds = max(
                        0,
                        int((c_exit - c_entry).total_seconds()),
                    )
                    closed_holding = (
                        f"{seconds // 60}m {seconds % 60}s"
                    )
                except Exception:
                    pass

                journal.append(
                    {
                        "Order": row.get("order_id"),
                        "Signal": row.get("signal_id"),
                        "Signal Type": (
                            closed_signal_meta.get(
                                "level_type"
                            )
                            if closed_signal_meta else "—"
                        ),
                        "Direction": (
                            closed_signal_meta.get(
                                "direction"
                            )
                            if closed_signal_meta else "—"
                        ),
                        "Opened By": (
                            "AUTO PAPER"
                            if closed_reason.startswith("AUTO_")
                            else "MANUAL PAPER"
                            if "MANUAL" in closed_reason
                            else "PAPER"
                        ),
                        "Entry Mode": (
                            row.get("entry_mode")
                            or (
                                "OPPORTUNITY_EXTENSION"
                                if "OPPORTUNITY_EXTENSION"
                                in closed_reason
                                else "FRESH_SIGNAL"
                                if closed_reason.startswith("AUTO_")
                                else "MANUAL"
                            )
                        ),
                        "Signal Age": row.get("signal_age_at_entry"),
                        "Opportunity": row.get("opportunity_score"),
                        "Reward Remaining %": row.get(
                            "reward_remaining_pct"
                        ),
                        "Option": row.get("tradingsymbol"),
                    "Type": row.get("option_type"),
                    "Strike": row.get("strike"),
                    "Entry Time": row.get("entry_timestamp"),
                    "Entry": row.get("entry_price"),
                    "Exit Time": row.get("exit_timestamp"),
                    "Exit": row.get("exit_price"),
                    "Qty": row.get("quantity"),
                    "P&L ₹": row.get("realized_pnl"),
                    "MFE": row.get("mfe_points"),
                    "MAE": row.get("mae_points"),
                        "Result": (
                            "PROFIT" if closed_pnl > 0
                            else "LOSS" if closed_pnl < 0
                            else "BREAKEVEN"
                        ),
                        "Holding": closed_holding,
                        "Exit Reason": row.get("exit_reason"),
                    }
                )
            st.dataframe(
                _arrow_safe_rows(journal),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "No closed paper option trades yet. Statistics will populate "
                "as the paper engine completes trades."
            )

    else:
        st.caption(
            "Diagnostics, execution timeline and closed-trade journal "
            "are loaded only on demand."
        )

    st.markdown("### AI Status")
    st.info(
        "AI Learning has not started yet. RB-0.7.4.8 collects and "
        "organizes the exact evidence the AI will consume later: "
        "signal context, candidate scores, Greeks, option candles, "
        "execution path, MFE/MAE and final outcome."
    )

    _perf_mark("Diagnostics / journal / final render")
    _perf_total = round(perf_counter() - _perf_started, 3)
    with st.expander("Performance Diagnostics", expanded=False):
        st.caption(
            "Measures this Paper Trading render only. Live 5-second status "
            "updates run in a separate Streamlit fragment."
        )
        perf_rows = list(_perf_rows) + [
            {
                "Section": "TOTAL PAGE RENDER",
                "Seconds": _perf_total,
            }
        ]
        st.dataframe(
            _arrow_safe_rows(perf_rows),
            width="stretch",
            hide_index=True,
        )
        slowest = max(
            _perf_rows,
            key=lambda row: float(row["Seconds"]),
            default=None,
        )
        if slowest:
            st.metric(
                "Slowest Section",
                slowest["Section"],
                delta=f"{float(slowest['Seconds']):.3f}s",
                delta_color="off",
            )
        st.caption(
            "Live position, execution mark and heartbeat reads are intentionally "
            "not cached to avoid stale trading state."
        )
