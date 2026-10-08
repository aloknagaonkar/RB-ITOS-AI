"""Offline development research. Entry-time gates; canonical exits unchanged."""
import argparse,csv,hashlib,json,math
from pathlib import Path
POLICIES=('WAITING_CONTROL','EARLIER_UNFILTERED','HYBRID_GAP_5_10','HYBRID_EXPANSION_025_050','HYBRID_ALIGNMENT','HYBRID_COMBINED')

def qualifies(row,policy):
    c=row.get('entry_check') or {};cur=c.get('current') or {}
    values=[c.get(k) for k in ('directional_wma_strength','current_gap','previous_gap','gap_delta')]
    if any(v is None or not math.isfinite(float(v)) for v in values):return False
    strength,gap,previous,delta=map(float,values)
    if strength<.75 or gap<=0 or delta<=0 or not math.isclose(delta,gap-previous,abs_tol=1e-7):return False
    r,e,w=[cur.get(k) for k in ('rsi9','ema3','wma21')]
    aligned=False if None in (r,e,w) else (r>e>w if row['direction']=='BULLISH' else r<e<w)
    checks={'HYBRID_GAP_5_10':5<=gap<10,'HYBRID_EXPANSION_025_050':.25<=delta<.5,'HYBRID_ALIGNMENT':aligned}
    return all(checks.values()) if policy=='HYBRID_COMBINED' else checks.get(policy,policy=='EARLIER_UNFILTERED')

def select(row,policy):
    if policy=='WAITING_CONTROL':return 'WAITING'
    if policy=='EARLIER_UNFILTERED':return 'EARLIER' if row.get('candidate_points') is not None else 'DENIED'
    # No future acceptance or P&L is used to decide whether the early gate passes.
    if row.get('candidate_points') is not None and qualifies(row,policy):
        # If control already entered, preserve its earlier execution.
        if row.get('control_points') is not None and row['control_entry_timestamp']<row['candidate_entry_timestamp']:return 'WAITING'
        return 'EARLIER'
    return 'WAITING'

def detail(row,policy):
    choice=select(row,policy);prefix='candidate' if choice=='EARLIER' else 'control'
    points=None if choice=='DENIED' else row.get(prefix+'_points')
    return dict(trade_id=row['trade_id'],session_date=row['session_date'],direction=row['direction'],policy=policy,
        path=choice if points is not None else 'DENIED',signal_timestamp=row.get('signal_timestamp'),
        entry_timestamp=row.get(prefix+'_entry_timestamp') if points is not None else None,
        entry_price=row.get(prefix+'_entry_price') if points is not None else None,
        exit_timestamp=row.get('exit_timestamp') if points is not None else None,exit_price=row.get('exit_price') if points is not None else None,
        points=points,control_points=row.get('control_points'),delta_vs_waiting=(points or 0)-(row.get('control_points') or 0),
        canonical_points=row['canonical_points'],canonical_mfe=row['canonical_mfe'],
        current_gap=(row.get('entry_check') or {}).get('current_gap'),gap_delta=(row.get('entry_check') or {}).get('gap_delta'))

def metrics(rows):
    accepted=[r for r in rows if r['points'] is not None];denied=[r for r in rows if r['points'] is None]
    gains=sum(r['points'] for r in accepted if r['points']>0);losses=-sum(r['points'] for r in accepted if r['points']<0)
    equity=peak=drawdown=0
    for r in sorted(accepted,key=lambda x:(x['exit_timestamp'],x['trade_id'])):
        equity+=r['points'];peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    return dict(signals=len(rows),entries=len(accepted),denied=len(denied),winners=sum(r['points']>0 for r in accepted),losers=sum(r['points']<0 for r in accepted),
        gains=round(gains,2),losses=round(losses,2),net=round(gains-losses,2),gain_loss_ratio=gains/losses if losses else None,
        max_drawdown=round(drawdown,2),delta_vs_waiting=round(sum(r['delta_vs_waiting'] for r in rows),2),
        denied_canonical_winners=sum(r['canonical_points']>0 for r in denied),denied_plus20_setups=sum(r['canonical_mfe']>=20 for r in denied))

def analyze(report):
    rows=report['trades'];dates=sorted({r['session_date'] for r in rows})
    cohorts=[('ALL_AVAILABLE_DEVELOPMENT',set(dates))]
    if len(dates)==490:
        cohorts += [(f'DEVELOPMENT_BLOCK_{i+1}',set(dates[i*160:(i+1)*160])) for i in range(3)]
        cohorts += [('PREVIOUSLY_OBSERVED_10',set(dates[480:]))]
    details=[detail(r,p) for r in rows for p in POLICIES];summary=[]
    for name,days in cohorts:
        for direction in ('ALL','BULLISH','BEARISH'):
            for policy in POLICIES:
                subset=[r for r in details if r['session_date'] in days and r['policy']==policy and (direction=='ALL' or r['direction']==direction)]
                summary.append(dict(cohort=name,direction=direction,policy=policy,**metrics(subset)))
    daily=[dict(session_date=day,direction=d,policy=p,**metrics([r for r in details if r['session_date']==day and r['policy']==p and (d=='ALL' or r['direction']==d)])) for day in dates for d in ('ALL','BULLISH','BEARISH') for p in POLICIES]
    return dict(model='HILEGA_GAP_HYBRID_DEVELOPMENT_V1',sessions=len(dates),summary=summary,daily=daily,trades=details,execution_enabled=False,
        warning='Exploratory development policies; thresholds informed by prior analysis. No independent validation or deployment recommendation. Evaluate first previously selected adjacent-gap entry; if gate fails, fall back to waiting control, without retrying the early gate. This is not entry on every first WMA threshold touch. Canonical exits and recorded close assumptions retained. Fees, option fills and position interaction excluded. Drawdown uses completed trade order. Reconciled frozen warmup reproduces historical evidence, not current live indicators.')

def self_test():
    r=dict(trade_id='t',session_date='2026-01-01',direction='BULLISH',canonical_points=10,canonical_mfe=30,control_points=None,candidate_points=-3,control_entry_timestamp=None,candidate_entry_timestamp='2026-01-01T10:01',exit_timestamp='2026-01-01T10:20',entry_check=dict(directional_wma_strength=.75,current_gap=6,previous_gap=5.7,gap_delta=.3,current=dict(rsi9=60,ema3=56,wma21=50)))
    assert qualifies(r,'HYBRID_COMBINED')
    assert select(r,'HYBRID_COMBINED')=='EARLIER' # No hindsight winner selection.
    r['entry_check']['gap_delta']=0
    assert select(r,'HYBRID_COMBINED')=='WAITING'
    assert detail(r,'HYBRID_COMBINED')['points'] is None
    r['direction']='BEARISH';r['entry_check'].update(gap_delta=.3,current=dict(rsi9=40,ema3=44,wma21=50))
    assert qualifies(r,'HYBRID_COMBINED')
    r['entry_check']['current_gap']=10
    assert not qualifies(r,'HYBRID_GAP_5_10')
    result=analyze({'trades':[r]})
    assert all(x['entries']+x['denied']==x['signals'] for x in result['summary'])
    print('PASS: directional gates, boundaries, missing/denied exclusion and no hindsight membership gate')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--report',type=Path,default=Path('data/historical-evidence/hilega-adjacent-gap-reconciled-490-v1/report.json'));p.add_argument('--expected-sessions',type=int,default=490);p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-gap-hybrid-development-v1'));a=p.parse_args()
    if a.self_test:self_test();raise SystemExit(0)
    if a.output_root.exists():raise SystemExit('STOP: output exists; choose a new output root')
    result=analyze(json.loads(a.report.read_text()))
    if result['sessions']!=a.expected_sessions:raise SystemExit(f"STOP: expected {a.expected_sessions} sessions, found {result['sessions']}")
    result['source_sha256']=hashlib.sha256(a.report.read_bytes()).hexdigest();a.output_root.mkdir(parents=True)
    (a.output_root/'report.json').write_text(json.dumps(result,indent=2))
    for name in ('summary','daily','trades'):
        with (a.output_root/(name+'.csv')).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(result[name][0]));w.writeheader();w.writerows(result[name])
    for r in result['summary']:
        if r['direction']!='ALL':print(json.dumps(r))
    print('Output:',a.output_root/'report.json');print('Research only; strategy, exits, source evidence and orders unchanged.')
