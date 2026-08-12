from red_bar_lab.ui._shared import *


def render_page(settings, layout, database, token, underlying_name, instrument_key, interval) -> None:
    st.subheader("Trade History")
    st.markdown("#### Paper Trades / Exit Evaluation")
    st.caption(
        "Every ACTIVE signal is evaluated independently against fixed "
        "20/30/40/50 point targets. Stop = setup 5-minute Candle A low "
        "for bullish trades and Candle A high for bearish trades."
    )

    available_trade_dates = RedBarHistoricalService.available_dates_static(
        layout,
        instrument_key,
        interval_minutes=1,
    ) if hasattr(RedBarHistoricalService, "available_dates_static") else []

    if not available_trade_dates:
        try:
            _provider = None
            _hist = RedBarHistoricalService(
                RedBarUpstoxService("placeholder"), layout
            )
            available_trade_dates = _hist.available_dates(
                instrument_key, interval_minutes=1
            )
        except Exception:
            available_trade_dates = []

    if not available_trade_dates:
        st.info("Download historical candles before evaluating trades.")
    else:
        selected_trade_date = st.selectbox(
            "Trade evaluation date",
            available_trade_dates,
            index=len(available_trade_dates) - 1,
            key="trade_evaluation_date",
        )
        if st.button("Build / Refresh Paper Trades", type="primary"):
            try:
                # No provider call is needed; read already-cached data only.
                historical_reader = RedBarHistoricalService(
                    RedBarUpstoxService("cache-only"), layout
                )
                frame = historical_reader.read_day(
                    instrument_key,
                    selected_trade_date,
                    interval_minutes=1,
                )
                attempts_rows = database.read_signal_attempts(
                    instrument_key,
                    selected_trade_date.isoformat(),
                )
                from red_bar_lab.strategy.models import (
                    Direction,
                    SignalAttempt,
                    SignalState,
                )
                attempts = []
                for row in attempts_rows:
                    if row["state"] != "ACTIVE":
                        continue
                    attempts.append(
                        SignalAttempt(
                            state=SignalState.ACTIVE,
                            direction=Direction(row["direction"]),
                            level_type=row["level_type"],
                            level_value=float(row["level_value"]),
                            cross_timestamp=pd.Timestamp(
                                row["cross_timestamp"]
                            ).to_pydatetime()
                            if row["cross_timestamp"] else None,
                            confirmation_timestamp=pd.Timestamp(
                                row["confirmation_timestamp"]
                            ).to_pydatetime()
                            if row["confirmation_timestamp"] else None,
                            underlying_entry=float(row["underlying_entry"])
                            if row["underlying_entry"] is not None else None,
                            cross_open=float(row["cross_open"])
                            if row["cross_open"] is not None else None,
                            cross_high=float(row["cross_high"])
                            if row["cross_high"] is not None else None,
                            cross_low=float(row["cross_low"])
                            if row["cross_low"] is not None else None,
                            cross_close=float(row["cross_close"])
                            if row["cross_close"] is not None else None,
                            confirmation_open=float(row["confirmation_open"])
                            if row["confirmation_open"] is not None else None,
                            confirmation_high=float(row["confirmation_high"])
                            if row["confirmation_high"] is not None else None,
                            confirmation_low=float(row["confirmation_low"])
                            if row["confirmation_low"] is not None else None,
                            confirmation_close=float(row["confirmation_close"])
                            if row["confirmation_close"] is not None else None,
                            confirmation_delay_minutes=row.get(
                                "confirmation_delay_minutes"
                            ),
                        )
                    )

                outcomes = evaluate_active_signals(
                    frame,
                    attempts,
                    instrument_key=instrument_key,
                    trading_date=selected_trade_date.isoformat(),
                    session_complete=_is_session_complete(
                        selected_trade_date
                    ),
                )
                database.replace_paper_trade_outcomes(
                    instrument_key,
                    selected_trade_date.isoformat(),
                    outcomes,
                )
                st.success(
                    f"Stored {len(outcomes)} paper-trade outcomes "
                    f"from {len(attempts)} ACTIVE signal(s)."
                )
            except Exception as exc:
                st.exception(exc)

        rows = database.read_paper_trade_outcomes(
            instrument_key,
            selected_trade_date.isoformat(),
        )
        if rows:
            decorated_rows = [
                decorate_trade_row(row) for row in rows
            ]
            summary = database.paper_trade_summary(
                instrument_key,
                selected_trade_date.isoformat(),
            )
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Trade models", summary["trades"])
            c2.metric("Win rate", f'{summary["win_rate"]:.1f}%')
            c3.metric("Net points", f'{summary["net_points"]:.2f}')
            pf = summary["profit_factor"]
            c4.metric(
                "Profit factor",
                "∞" if pf is None and summary["winners"] else (
                    f"{pf:.2f}" if pf is not None else "—"
                ),
            )

            st.markdown("#### Signal outcome summary")
            st.dataframe(
                _arrow_safe_rows(
                    summarize_signal_trade_models(decorated_rows)
                ),
                width="stretch",
                hide_index=True,
            )

            st.markdown("#### Trade model outcomes")
            st.caption(
                "Models 1–10 are actionable and determine signal completion. "
                "EOD_HOLD is model 11 and is informational only."
            )
            st.caption(
                "State shows lifecycle (OPEN/CLOSED). "
                "Trade Result shows WIN/LOSS/BREAKEVEN. "
                "Successful/Failed gives the business outcome, and "
                "Points Gained is the actual underlying result for that model."
            )
            st.dataframe(
                _trade_display_rows(decorated_rows),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "No paper trades stored for the selected date. "
                "Run Signal Replay first, then build paper trades."
            )
