"""Classify unresolved historical observations without inventing an exit or P&L."""
from copy import deepcopy


def current_view(dashboard, session_date, version):
    result = deepcopy(dashboard)
    unresolved = 0
    for trade in result.get('trades', []):
        if trade.get('status') not in {'ACTIVE', 'PENDING_EXACT_EXIT'}:
            continue
        if (str(trade.get('signal_bar', ''))[:10] == session_date
                and trade.get('strategy_version') == version):
            continue
        trade['recorded_status'] = trade['status']
        trade['status'] = 'UNRESOLVED_HISTORICAL'
        trade['requires_reconciliation'] = True
        trade['display_issue'] = 'PRIOR_SESSION_OR_POLICY_OPEN_RECORD; PRICES_ARE_HISTORICAL'
        unresolved += 1
    trades = result.get('trades', [])
    def counts(subset):
        return dict(trade_count=len(subset),
            active_count=sum(t.get('status') == 'ACTIVE' for t in subset),
            closed_count=sum(t.get('status') == 'CLOSED' for t in subset),
            incomplete_count=sum(t.get('status') not in {'ACTIVE', 'CLOSED'} for t in subset))
    result.update(active_count=sum(t.get('status') == 'ACTIVE' for t in trades),
        pending_exit_count=sum(t.get('status') == 'PENDING_EXACT_EXIT' for t in trades),
        incomplete_count=sum(t.get('status') not in {'ACTIVE', 'CLOSED', 'PENDING_EXACT_EXIT'} for t in trades),
        unresolved_historical_count=unresolved, display_session_date=session_date,
        display_strategy_version=version,
        by_direction={side: counts([t for t in trades if t.get('direction') == side])
                      for side in ('BULLISH', 'BEARISH')})
    return result
