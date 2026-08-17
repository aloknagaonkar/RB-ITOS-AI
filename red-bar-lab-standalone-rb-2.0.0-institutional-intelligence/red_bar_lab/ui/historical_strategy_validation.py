from __future__ import annotations

from datetime import date
from typing import Iterable

import pandas as pd
import streamlit as st

from red_bar_lab.services.historical_strategy_validation import StrategyRegistry, StrategyValidationReport, select_validation_dates


def render_strategy_validation_selector(registry: StrategyRegistry, available_dates: Iterable[date]) -> dict[str, object]:
    st.markdown('#### Generic Historical Strategy Validation')
    st.caption('Research-only validation. This module cannot place, queue, modify, or exit paper/live trades.')

    definitions = registry.definitions()
    labels = {f'{item.display_name} ({item.version})': item for item in definitions if item.enabled}
    selected_label = st.selectbox('Historical strategy', list(labels), key='generic_historical_strategy')
    selected = labels[selected_label]
    window_label = st.selectbox(
        'Validation window',
        ['10 trading days', '20 trading days', 'Custom'],
        key='generic_historical_window',
    )
    window = {'10 trading days': '10_DAY', '20 trading days': '20_DAY', 'Custom': 'CUSTOM'}[window_label]
    dates = tuple(sorted(set(available_dates)))
    custom_start = custom_end = None
    if window == 'CUSTOM' and dates:
        c1, c2 = st.columns(2)
        with c1:
            custom_start = st.date_input('Validation From', value=dates[0], min_value=dates[0], max_value=dates[-1], key='generic_validation_start')
        with c2:
            custom_end = st.date_input('Validation To', value=dates[-1], min_value=dates[0], max_value=dates[-1], key='generic_validation_end')
    selected_dates = select_validation_dates(dates, window=window, custom_start=custom_start, custom_end=custom_end) if dates else ()
    compare_labels = st.multiselect('Compare strategies', list(labels), default=[selected_label], key='generic_historical_compare')
    st.info(f'Selected {len(selected_dates)} cached trading day(s). Strategy identity: {selected.identity}')
    return {
        'strategy_id': selected.strategy_id,
        'version': selected.version,
        'adapter_id': selected.adapter_id,
        'dates': selected_dates,
        'compare': tuple((labels[label].strategy_id, labels[label].version) for label in compare_labels),
        'research_scope': selected.research_scope,
    }


def render_strategy_comparison(reports: Iterable[StrategyValidationReport]) -> None:
    rows = []
    for report in reports:
        m = report.metrics
        rows.append({
            'Strategy': report.strategy.display_name,
            'Version': report.strategy.version,
            'Ready Days': m.ready_days,
            'Blocked Days': m.blocked_days,
            'Readiness %': m.readiness_pct,
            'Trades': m.trade_count,
            'Win Rate %': m.win_rate_pct,
            'Net Return %': m.net_return_pct,
            'Expectancy %': m.expectancy_pct,
            'Profit Factor': m.profit_factor,
            'Max Drawdown %': m.maximum_drawdown_pct,
            'Promotion': 'ELIGIBLE' if m.promotion_eligible else 'HOLD',
            'Promotion Reasons': ' | '.join(m.promotion_reasons),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)



def render_strategy_validation_results(
    reports: Iterable[StrategyValidationReport],
) -> None:
    reports = tuple(reports)
    if not reports:
        return

    st.markdown('##### Strategy Comparison')
    render_strategy_comparison(reports)

    for report in reports:
        with st.expander(
            f'{report.strategy.display_name} '
            f'({report.strategy.version}) — daily readiness',
            expanded=len(reports) == 1,
        ):
            metrics = report.metrics
            r1, r2, r3, r4, r5 = st.columns(5)
            r1.metric('Ready Days', metrics.ready_days)
            r2.metric('Blocked Days', metrics.blocked_days)
            r3.metric('Readiness', f'{metrics.readiness_pct:.1f}%')
            r4.metric('Trades', metrics.trade_count)
            r5.metric(
                'Promotion',
                'ELIGIBLE' if metrics.promotion_eligible else 'HOLD',
            )

            daily_rows = [
                {
                    'Trading Date': day.trading_date,
                    'Ready': 'YES' if day.ready else 'NO',
                    'Fidelity': day.fidelity,
                    'Coverage Basis': day.coverage_basis,
                    'Contract Coverage %': day.contract_coverage_pct,
                    'Candle Coverage %': day.candle_coverage_pct,
                    'OI Coverage %': day.oi_coverage_pct,
                    'Global Gate': (
                        'PASS' if day.global_replay_ready else 'BLOCK'
                    ),
                    'Relevant Audit': day.strategy_relevant_status,
                    'Relevant Contracts': day.relevant_contracts,
                    'Relevant CE': day.relevant_ce_contracts,
                    'Relevant PE': day.relevant_pe_contracts,
                    'Relevant Complete': day.relevant_complete_contracts,
                    'Relevant Candle %': day.relevant_candle_coverage_pct,
                    'Relevant OI %': day.relevant_oi_coverage_pct,
                    'Missing Relevant': day.missing_relevant_contracts,
                    'Replay Rows': len(day.rows),
                    'Readiness Reason': day.readiness_reason,
                    'Relevant Audit Reason': day.strategy_relevant_reason,
                }
                for day in report.days
            ]
            st.dataframe(
                pd.DataFrame(daily_rows),
                width='stretch',
                hide_index=True,
            )

            blocked = [day for day in report.days if not day.ready]
            if blocked:
                st.warning(
                    f'{len(blocked)} selected day(s) were blocked. '
                    'They remain included in readiness and promotion metrics.'
                )
            st.caption(
                'Promotion reasons: '
                + ' | '.join(metrics.promotion_reasons)
            )
