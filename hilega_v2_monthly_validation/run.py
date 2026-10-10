"""Read-only rolling-window evaluation of the installed tested V2 replay policy."""
import argparse,calendar,csv,hashlib,json,sys
from datetime import date,timedelta
from pathlib import Path
from market_lab import hilega_v2_alignment_replay_v1 as engine

def start_date(end,months):
 total=end.year*12+end.month-1-months;y,m=divmod(total,12);m+=1
 return date(y,m,min(end.day,calendar.monthrange(y,m)[1]))+timedelta(days=1)
def metrics(trades):
 gains=sum(max(0,t['points']) for t in trades);losses=sum(max(0,-t['points']) for t in trades)
 running=peak=drawdown=0
 for t in sorted(trades,key=lambda t:(t['exit_time'],t['entry_time'])):
  running+=t['points'];peak=max(peak,running);drawdown=max(drawdown,peak-running)
 return dict(trades=len(trades),winners=sum(t['points']>0 for t in trades),losers=sum(t['points']<0 for t in trades),breakeven=sum(t['points']==0 for t in trades),gains=round(gains,2),losses=round(losses,2),net=round(gains-losses,2),gain_loss_ratio=gains/losses if losses else None,win_rate_pct=100*sum(t['points']>0 for t in trades)/len(trades) if trades else None,max_drawdown_points=round(drawdown,2))
def write_csv(path,rows):
 keys=list(dict.fromkeys(k for row in rows for k in row)) or ['session_date']
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def run(roots,out,end=None):
 index=engine.cache_index(roots);available=[]
 for d,p in sorted(index.items()):
  if json.loads(p.read_text()).get('candles'):available.append(d)
 if not available:raise ValueError('No candle sessions available')
 end=date.fromisoformat(end or available[-1]);first=start_date(end,3);out.mkdir(parents=True,exist_ok=True)
 sessions=[];trades=[];coverage=[]
 day=first
 while day<=end:
  stamp=day.isoformat();p=index.get(stamp)
  if p is None:coverage.append(dict(session_date=stamp,status='CACHE_MISSING',issue='No local input; not assumed a holiday or zero-trade session'))
  elif not json.loads(p.read_text()).get('candles'):coverage.append(dict(session_date=stamp,status='EMPTY_CACHE',issue='No candles; holiday/non-session status not independently verified'))
  else:
   try:
    x=engine.load_session(stamp,out/'sessions',roots)
    sessions.append(dict(session_date=stamp,**metrics(x['trades'])))
    for t in x['trades']:
     c=t.get('entry_checks') or {};trades.append({k:t.get(k) for k in ('trade_id','direction','setup_source','signal_time','entry_time','entry_price','warning_time','exit_time','exit_price','exit_reason','points','mfe_points','giveback_points')}|dict(session_date=stamp,strength=c.get('directional_wma_strength'),previous_strength=c.get('previous_directional_wma_strength'),gap=c.get('current_gap'),previous_gap=c.get('previous_gap'),expansion=c.get('gap_delta')))
    coverage.append(dict(session_date=stamp,status='EVALUATED',issue=''))
   except (ValueError,FileNotFoundError,engine.ReplayBusyError) as e:coverage.append(dict(session_date=stamp,status='NOT_EVALUATED',issue=str(e)))
  day+=timedelta(days=1)
 windows=[]
 for months in (1,3):
  begin=start_date(end,months).isoformat();selected=[t for t in trades if begin<=t['session_date']<=end.isoformat()];cov=[r for r in coverage if begin<=r['session_date']<=end.isoformat()]
  for direction in ('ALL','BULLISH','BEARISH'):
   windows.append(dict(months=months,start=begin,end=end.isoformat(),direction=direction,evaluated_sessions=sum(r['status']=='EVALUATED' for r in cov),missing_calendar_dates=sum(r['status']=='CACHE_MISSING' for r in cov),empty_cache_dates=sum(r['status']=='EMPTY_CACHE' for r in cov),failed_sessions=sum(r['status']=='NOT_EVALUATED' for r in cov),**metrics(selected if direction=='ALL' else [t for t in selected if t['direction']==direction])))
 result=dict(input_sha256={d:hashlib.sha256(p.read_bytes()).hexdigest() for d,p in index.items() if d<=end.isoformat()},strategy_id=engine.MODEL,rules=engine.RULES,rule_source_sha256=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),windows=windows,coverage=coverage,warning='Reconstructed Nifty research only; chart/live indicator parity unconfirmed. Missing/empty dates are not zero trades. Calendar coverage is not an exchange-calendar completeness claim. No fees, slippage or option fills included.',execution_enabled=False)
 (out/'report.json').write_text(json.dumps(result,indent=2));write_csv(out/'summary.csv',windows);write_csv(out/'daily.csv',sessions);write_csv(out/'trades.csv',trades);write_csv(out/'losses.csv',[t for t in trades if t['points']<0]);write_csv(out/'coverage.csv',coverage)
 for row in windows:print(json.dumps(row),flush=True)
 print('Output:',out,'; no strategy or order changes',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--cache-root',action='append',type=Path);p.add_argument('--end-date');p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-v2-monthly-validation-v1'));p.add_argument('--self-test',action='store_true');a=p.parse_args()
 if a.self_test:
  assert start_date(date(2026,10,9),1)==date(2026,9,10);assert start_date(date(2026,10,9),3)==date(2026,7,10)
  assert start_date(date(2026,3,31),1)==date(2026,3,1)
  m=metrics([dict(points=10,entry_time='a',exit_time='b'),dict(points=-4,entry_time='b',exit_time='c')]);assert m['net']==6 and m['max_drawdown_points']==4 and m['gain_loss_ratio']==2.5
  assert metrics([])['gain_loss_ratio'] is None
  print('PASS: calendar windows, gain/loss reconciliation, drawdown and empty group')
 else:run(a.cache_root or list(engine.CACHE_ROOTS),a.output_root,a.end_date)
