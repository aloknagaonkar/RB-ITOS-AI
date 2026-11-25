"""Present the shared RSI engine through the existing Hilega replay contract."""
from copy import deepcopy
from datetime import date,datetime,timedelta
from .engine import Engine
from .data import bars
from .calendar import validate_rows,required_sessions
from ..hilega_three_minute_v1.hilega_combined_policy_v1 import RULES,VERSION,POLICY_ID,check_payload,SIDE

MODEL='HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT_REPLAY_V1'
SOURCE='RSI_TWO_ROUTE_CONFIRMED_MIDPOINT_REPLAY'

def build_session(session_date,raw_rows,warmup,metadata=None):
    day=date.fromisoformat(session_date);needed=[str(d) for d in required_sessions(day)]
    supplied={d:rows for d,rows in warmup}
    if sorted(supplied)!=needed:raise ValueError('EXACT_RECENT_20_WARMUP_REQUIRED')
    seed=[b for d in needed for b in bars(supplied[d],date.fromisoformat(d))]
    rows=validate_rows(raw_rows,day);engine=Engine(str(day),seed)
    for b in bars(rows,day):engine.advance(b,rows)
    trades=[];audit=[];checks=[];events=[];setups=[]
    for t in engine.trades:
        trades.append(dict(t,direction=SIDE[t['side']],signal_time=t['entry_signal_time'],
            setup_available=t['entry_signal_time'],qualified_signal_time=t['entry_signal_time'],
            setup_source=t['route_name'],exit_reason='; '.join(t['exit_reasons']),
            mfe_points=t['peak_positive_points'],entry_checks=dict(t['entry_evaluation'],signal_available_at=t['entry_signal_time'])))
    for a in engine.audits:
        f=a['frame'];cp=a['decision_time'];cc=[check_payload(a,s) for s in ('CE','PE')];checks+=cc
        transitions=[]
        for e in a['events']:
            if e['event']=='ENTRY':
                transitions.append(dict(event='ENTRY_ACTIVE',direction=SIDE[e['side']],price=e['fill'],route_name=e['route_name']))
                setups.append(dict(time=cp,direction=SIDE[e['side']],source=e['route_name']))
            else:
                t=next(t for t in engine.trades if t['trade_id']==e['trade_id'])
                transitions.append(dict(event='EXIT_CLOSED',direction=SIDE[e['side']],price=e['fill'],points=t['points'],reason='; '.join(e['reasons'])))
        exitv=deepcopy(a['exit_evaluation'])
        if exitv is not None:exitv.update(direction=SIDE[a['owner_before']],policy_id=POLICY_ID,decision_interval_minutes=3,session_end_IST='15:30',rsi5=f['rsi5'],rsi9=f['rsi9'],wma21=f['wma21_rsi9'],action='EXIT' if any(e['event']=='EXIT' for e in a['events']) else 'HOLD')
        policy=[dict(event='RSI_TWO_ROUTE_CHECK',time=cp,direction=c['direction'],passed=c['passed'],route_name=c['route_name'],reasons=c['reasons'],policy_id=POLICY_ID,strategy_version=VERSION) for c in cc];events+=policy
        audit.append(dict(checkpoint=cp,minute_timestamp=(datetime.fromisoformat(cp)-timedelta(minutes=1)).isoformat(),
            decision_interval_minutes=3,indicator_timeframe='3m',policy_id=POLICY_ID,strategy_version=VERSION,
            owner_before=SIDE.get(a['owner_before'],'NONE'),owner_after=SIDE.get(a['owner_after'],'NONE'),
            price_ema_frame=f,nifty_close=f['close'],indicators=dict(rsi9=f['rsi9'],ema3=None,wma21=f['wma21_rsi9']),
            completed_5m_indicators=dict(rsi9=f['rsi9'],ema3=None,wma21=f['wma21_rsi9']),
            checks=cc,policy_events=policy,transitions=transitions,exit_validation=exitv,pending_switches=[],canonical_events=[],
            native_audit=a,active_trade=None))
    summary=engine.result()['summary'];gains=sum(max(t['points'],0) for t in trades);losses=sum(max(-t['points'],0) for t in trades)
    metric=dict(strategy_id=MODEL,available=True,signals=sum(bool(c['selected_route']) for c in checks),
        entries=len(trades),denied=sum(bool(c['selected_route']) for c in checks)-len(trades),completed=len(trades),
        winning_trades=summary['winners'],losing_trades=summary['losers'],breakeven_trades=sum(t['points']==0 for t in trades),
        gross_points_gained=gains,gross_points_lost=losses,net_points=summary['net_points'],gain_loss_ratio=gains/losses if losses else None,
        win_rate_pct=100*summary['winners']/len(trades) if trades else None)
    return dict(model=MODEL,source=SOURCE,source_id=SOURCE+':'+str(day),session_date=str(day),strategy_id=MODEL,
        strategy_version=VERSION,rules=RULES,policy_id=POLICY_ID,trades=trades,audit=audit,checks=checks,
        alternative_signals=[],setup_attempts=setups,policy_events=events,performance_summary=[metric],reports=[],report_count=len(audit),
        evidence_level='STRATEGY',ce_available=False,audit_chain_ok=None,audit_chain_issue=None,manifest=metadata or {},
        observation_only=True,execution_enabled=False,forward_confirmation_eligible=False,
        warning='Historical reconstruction of the active native RSI strategy. NIFTY reference points; actual option fills and costs use the existing live execution pipeline.')
