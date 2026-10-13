"""Read existing EMA10 research exports. No replay, services or orders."""
import argparse,csv,json,math
from datetime import date
from pathlib import Path
TARGETS=[('BULLISH','S0.5_P2_FLATNone'),('BULLISH','S2_P1_FLAT0.5'),('BEARISH','S0_P1_FLATNone')]

def read(p):
    with p.open(newline='') as f:return list(csv.DictReader(f))
def write(p,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r)) or ['trade_id']
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def number(v):return None if v in ('',None,'None') else float(v)
def decision(policy,t,candles):
    slope=number(t.get('slope'));mean3=number(t.get('mean3'))
    if slope is None:return None,'Missing recorded slope'
    if policy=='S0_P1_FLATNone':return slope<0,f'Latest slope {slope:+.4f}; required <0'
    if policy=='S2_P1_FLAT0.5':
        if mean3 is None:return None,'Missing three-bar mean'
        return slope>=2 and abs(mean3)>.5,f'Latest {slope:+.4f} >=2; |mean3| {abs(mean3):.4f} >0.5'
    rows=sorted([r for rr in candles.values() for r in rr],key=lambda r:r['available_at'])
    eligible=[r for r in rows if r['available_at']<=t['available_at']]
    # Latest recorded feature belongs to this date; only adjacent five-minute rows qualify.
    if len(eligible)<2:return None,'Previous slope not included in exported window'
    previous=number(eligible[-2]['slope']);current=number(eligible[-1]['slope'])
    if previous is None or current is None:return None,'Missing adjacent slope'
    return previous>=.5 and current>=.5,f'Previous {previous:+.4f}; current {current:+.4f}; both >=0.5'

def category(accepted,points):
    if accepted is None:return 'UNAVAILABLE'
    return ('KEPT_WINNER' if points>0 else 'KEPT_LOSER' if points<0 else 'KEPT_BREAKEVEN') if accepted else ('BLOCKED_WINNER' if points>0 else 'AVOIDED_LOSER' if points<0 else 'BLOCKED_BREAKEVEN')

def analyze(a):
    root=a.input_root;trades=read(root/'trades.csv');summary=read(root/'summary.csv');raw=read(root/'candles.csv');candles={}
    for r in raw:candles.setdefault(r['session_date'],[]).append(r)
    for rows in candles.values():rows.sort(key=lambda r:r['available_at'])
    details=[];totals=[];errors=[]
    for side,policy in TARGETS:
        for t in trades:
            if t['direction']!=side:continue
            accepted,reason=decision(policy,t,candles);pts=number(t['points'])
            details.append(dict(t,policy=policy,selection='UNAVAILABLE' if accepted is None else 'KEEP' if accepted else 'BLOCK',category=category(accepted,pts),gate_evidence=reason))
        for period in ('ONE_MONTH','THREE_MONTHS','EARLIER_TWO_MONTHS'):
            expected=next((r for r in summary if r['period']==period and r['direction']==side and r['policy']==policy),None)
            if not expected:errors.append('Missing summary:'+period+':'+policy);continue
            chosen=[d for d in details if d['policy']==policy and expected['start']<=d['session_date']<=expected['end']]
            missing=[d for d in chosen if d['selection']=='UNAVAILABLE'];kept=[d for d in chosen if d['selection']=='KEEP'];blocked=[d for d in chosen if d['selection']=='BLOCK']
            net=sum(number(d['points']) for d in kept);blocked_win=sum(max(0,number(d['points'])) for d in blocked);avoided_loss=sum(max(0,-number(d['points'])) for d in blocked)
            passed=not missing and len(kept)==int(expected['trades']) and math.isclose(net,float(expected['net']),abs_tol=.011) and math.isclose(blocked_win,float(expected['blocked_winner_points']),abs_tol=.011) and math.isclose(avoided_loss,float(expected['avoided_loss_points']),abs_tol=.011)
            row=dict(period=period,start=expected['start'],end=expected['end'],direction=side,policy=policy,kept_trades=len(kept),kept_net=round(net,2),blocked_winners=sum(number(d['points'])>0 for d in blocked),blocked_winner_points=round(blocked_win,2),avoided_losers=sum(number(d['points'])<0 for d in blocked),avoided_loss_points=round(avoided_loss,2),unavailable=len(missing),reconciled='PASS' if passed else 'FAIL')
            totals.append(row)
            if not passed:errors.append('RECONCILIATION_FAILED:'+period+':'+policy)
    out=a.output_root;out.mkdir(parents=True,exist_ok=True);write(out/'trade-details.csv',details);write(out/'reconciliation.csv',totals)
    for cat in ('AVOIDED_LOSER','BLOCKED_WINNER','KEPT_LOSER'):
        write(out/(cat.lower()+'.csv'),[d for d in details if d['category']==cat])
    print('Period | Direction | Policy | Kept net | Winners blocked | Winner points blocked | Losses avoided | Loss points avoided | Reconciled')
    for r in totals:print(f"{r['period']} | {r['direction']} | {r['policy']} | {r['kept_net']:+.2f} | {r['blocked_winners']} | {r['blocked_winner_points']:.2f} | {r['avoided_losers']} | {r['avoided_loss_points']:.2f} | {r['reconciled']}")
    for side,policy in TARGETS:
        last=next(r for r in totals if r['period']=='ONE_MONTH' and r['policy']==policy)
        subset=[d for d in details if d['policy']==policy and last['start']<=d['session_date']<=last['end'] and d['category'] in ('BLOCKED_WINNER','AVOIDED_LOSER')]
        print('\n'+side+' '+policy+' — last month, blocked trades (largest absolute points first)')
        print('Date | Category | Signal | Entry / price | Exit / price | Points | EMA evidence')
        for d in sorted(subset,key=lambda d:-abs(number(d['points']))):
            print(f"{d['session_date']} | {d['category']} | {d.get('signal_time','')[11:16]} | {d['entry_time'][11:16]} / {number(d['entry_price']):.2f} | {d['exit_time'][11:16]} / {number(d['exit_price']):.2f} | {number(d['points']):+.2f} | {d['gate_evidence']}")
    daily=[]
    for side,policy in TARGETS:
        for day in sorted({d['session_date'] for d in details if d['policy']==policy}):
            dd=[d for d in details if d['policy']==policy and d['session_date']==day]
            base=sum(number(d['points']) for d in dd);kept=sum(number(d['points']) for d in dd if d['selection']=='KEEP')
            daily.append(dict(session_date=day,direction=side,policy=policy,baseline_net=round(base,2),kept_net=round(kept,2),net_delta=round(kept-base,2)))
    write(out/'daily.csv',daily)
    (out/'report.json').write_text(json.dumps(dict(reconciliation=totals,errors=errors,scope='Fixed baseline entry/exit selection diagnostics; not full filtered strategy replay',execution_enabled=False),indent=2))
    print('Output:',out,'; research exports only; no replay or live changes')
    if errors:raise SystemExit('STOP: '+ '; '.join(errors))
    print('PASS: all three candidate trade memberships reconcile with original summary')

def self_test():
    t={'slope':'2.5','mean3':'0.4','session_date':'2026-10-12','available_at':'2026-10-12T09:30:00+05:30'}
    assert decision('S2_P1_FLAT0.5',t,{})[0] is False
    t['mean3']='1';assert decision('S2_P1_FLAT0.5',t,{})[0] is True
    t['slope']='-1';assert decision('S0_P1_FLATNone',t,{})[0] is True
    assert category(False,10)=='BLOCKED_WINNER' and category(False,-10)=='AVOIDED_LOSER'
    assert category(None,10)=='UNAVAILABLE'
    cc={t['session_date']:[{'available_at':'2026-10-12T09:25:00+05:30','slope':'.5'},{'available_at':t['available_at'],'slope':'.6'},{'available_at':'2026-10-12T09:35:00+05:30','slope':'-20'}]}
    assert decision('S0.5_P2_FLATNone',t,cc)[0] is True
    print('PASS: policy equality boundaries, flat exclusion, categories and no future-candle leakage')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input-root',type=Path,default=Path('data/historical-evidence/hilega-ema10-trend-research-v1'));p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-ema10-filter-trade-diagnostics-v1'));p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:self_test()
    else:analyze(a)
