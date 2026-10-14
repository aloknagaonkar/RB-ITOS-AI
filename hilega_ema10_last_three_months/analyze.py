"""Offline attribution of EMA10 exit changes. No strategy or broker writes."""
import argparse, calendar, csv, json
from datetime import date, timedelta
from pathlib import Path
POLICIES=('WAITING_ENTRY','EARLIER_ADJACENT_GAP','BULLISH_EXPANSION_HYBRID')

def start_date(end):
    index=end.year*12+end.month-1-3
    year,month=divmod(index,12);month+=1
    return date(year,month,min(end.day,calendar.monthrange(year,month)[1]))+timedelta(days=1)

def classify(r):
    old=float(r['current_points']);new=float(r['ema10_points'])
    delta=new-old
    if old>0 and new<0:return 'WINNER_TO_LOSER'
    if old<0 and new>0:return 'LOSER_TO_WINNER'
    return 'EMA10_HELPED' if delta>1e-8 else 'EMA10_HURT' if delta < -1e-8 else 'UNCHANGED'

def summary(rows):
    old=[float(r['current_points']) for r in rows];new=[float(r['ema10_points']) for r in rows]
    result={'trades':len(rows)}
    for name,values in (('current',old),('ema10',new)):
        gains=sum(v for v in values if v>0);loss=-sum(v for v in values if v<0)
        result.update({name+'_gains':round(gains,2),name+'_losses':round(loss,2),name+'_net':round(gains-loss,2),name+'_gain_loss_ratio':gains/loss if loss else None})
    ds=[n-o for o,n in zip(old,new)]
    result.update(extra_points_earned=round(sum(v for v in ds if v>0),2),points_lost_by_delaying=round(-sum(v for v in ds if v<0),2),net_exit_effect=round(sum(ds),2),helped=sum(v>1e-8 for v in ds),hurt=sum(v < -1e-8 for v in ds),winner_to_loser=sum(o>0 and n<0 for o,n in zip(old,new)),loser_to_winner=sum(o<0 and n>0 for o,n in zip(old,new)))
    return result

def analyze(report,end=None):
    trades=report['trades']
    if not trades:raise ValueError('No eligible trade rows in report')
    end=end or max(date.fromisoformat(r['session_date']) for r in trades)
    start=start_date(end)
    chosen=[dict(r,outcome=classify(r),month=r['session_date'][:7]) for r in trades if start<=date.fromisoformat(r['session_date'])<=end]
    excluded=[r for r in report.get('excluded_entries',[]) if start<=date.fromisoformat(r['session_date'])<=end]
    sums=[]
    for period in ['WINDOW']+sorted({r['month'] for r in chosen}):
        for policy in POLICIES:
            for direction in ('ALL','BULLISH','BEARISH'):
                rows=[r for r in chosen if r['entry_policy']==policy and (direction=='ALL' or r['direction']==direction) and (period=='WINDOW' or r['month']==period)]
                invalid=[r for r in excluded if r['entry_policy']==policy and (direction=='ALL' or r['direction']==direction) and (period=='WINDOW' or r['session_date'][:7]==period)]
                sums.append(dict(period=period,entry_policy=policy,direction=direction,excluded_timing_entries=len(invalid),excluded_source_points=round(sum(float(r['source_points']) for r in invalid),2),**summary(rows)))
    return dict(start=start.isoformat(),end=end.isoformat(),summary=sums,trades=chosen,excluded_entries=excluded,warning='Rolling three calendar months ending at latest eligible evidence date, unless --end-date supplied. Dates refer to signal session. Policies are alternatives: never add their totals. Paired attribution only; extended trades may overlap. Timing exclusions are outside both P&Ls. Price points exclude fees and option fills. Missing gap values remain unavailable.')

def write_csv(path,rows,default):
    keys=list(dict.fromkeys(k for r in rows for k in r if k!='audit')) or default
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader();w.writerows(rows)

def self_test():
    assert start_date(date(2026,10,1))==date(2026,7,2)
    assert start_date(date(2026,5,31))==date(2026,3,1)
    rows=[dict(current_points=50,ema10_points=20),dict(current_points=-10,ema10_points=15),dict(current_points=5,ema10_points=-15)]
    s=summary(rows)
    assert s['extra_points_earned']==25 and s['points_lost_by_delaying']==50 and s['net_exit_effect']==-25
    assert s['current_net']==45 and s['ema10_net']==20 and s['winner_to_loser']==1 and s['loser_to_winner']==1
    assert classify(rows[2])=='WINNER_TO_LOSER'
    assert summary([])['trades']==0
    print('PASS: rolling dates, attribution reconciliation, winner/loser changes and empty groups')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--report',type=Path,default=Path('data/historical-evidence/hilega-warning-ema10-exit-v1/report.json'));p.add_argument('--end-date',type=date.fromisoformat);p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-ema10-last-three-months-v1'));a=p.parse_args()
    if a.self_test:self_test();raise SystemExit(0)
    if a.output_root.exists():raise SystemExit('STOP: output exists; select a new --output-root')
    result=analyze(json.loads(a.report.read_text()),a.end_date)
    a.output_root.mkdir(parents=True)
    (a.output_root/'report.json').write_text(json.dumps(result,indent=2))
    write_csv(a.output_root/'summary.csv',result['summary'],['period'])
    rows=sorted(result['trades'],key=lambda r:float(r['delta_points']))
    write_csv(a.output_root/'trade-details.csv',rows,['trade_id'])
    write_csv(a.output_root/'ema10-hurt.csv',[r for r in rows if float(r['delta_points']) < -1e-8],['trade_id'])
    write_csv(a.output_root/'ema10-helped.csv',list(reversed([r for r in rows if float(r['delta_points'])>1e-8])),['trade_id'])
    write_csv(a.output_root/'excluded-entries.csv',result['excluded_entries'],['trade_id'])
    print('WINDOW:',result['start'],'through',result['end'])
    for row in result['summary']:
        if row['period']=='WINDOW' and row['direction']!='ALL':print(json.dumps(row))
    print('Output:',a.output_root)
