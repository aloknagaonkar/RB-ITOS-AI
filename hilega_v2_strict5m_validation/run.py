"""Separate full-lifecycle loss diagnostics. No broker API, live writes or deployment."""
import argparse,calendar,csv,hashlib,json,sys,types
from datetime import date,datetime,timedelta
from pathlib import Path
from market_lab import hilega_v2_alignment_replay_v1 as base
from functools import partial
import engine
POLICIES=['BASELINE','STRICT5M_DUAL_EXIT','STRICT5M_ALL_SLOPE_EXIT','STRICT5M_ALL_SLOPE_EXIT_STRENGTH075']
def policy_module(policy):
 if policy=='BASELINE':return base
 return types.SimpleNamespace(replay=partial(engine.replay,slope_exit=policy!='STRICT5M_DUAL_EXIT',strength_min=.75 if policy.endswith('075') else 0))

def metrics(trades):
 gain=sum(max(t['points'],0) for t in trades);loss=sum(max(-t['points'],0) for t in trades);running=peak=dd=0
 for t in sorted(trades,key=lambda t:(t['exit_time'],t['entry_time'])):
  running+=t['points'];peak=max(peak,running);dd=max(dd,peak-running)
 return dict(trades=len(trades),wins=sum(t['points']>0 for t in trades),losses_count=sum(t['points']<0 for t in trades),gains=round(gain,2),losses=round(loss,2),net=round(gain-loss,2),gain_loss_ratio=gain/loss if loss else None,max_drawdown=round(dd,2))
def begin(end,months):
 y,m=divmod(end.year*12+end.month-1-months,12);m+=1
 return date(y,m,min(end.day,calendar.monthrange(y,m)[1]))+timedelta(days=1)
def dump(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,default=str))
def write(p,rows):
 keys=list(dict.fromkeys(k for r in rows for k in r)) or ['session_date']
 with p.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows([{k:json.dumps(v,default=str) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows])
def key(t):return(t['direction'],t['entry_time'],round(t['entry_price'],6))
def attribution(b,changed):
 bb={key(t):t for t in b};cc={key(t):t for t in changed};out=[]
 for k in sorted(set(bb)|set(cc)):
  old=bb.get(k);new=cc.get(k)
  status='MATCHED_ENTRY' if old and new else 'BASELINE_ONLY' if old else 'VARIANT_ONLY'
  out.append(dict(direction=k[0],entry_time=k[1],entry_price=k[2],membership=status,baseline_id=old['trade_id'] if old else None,variant_id=new['trade_id'] if new else None,baseline_exit=old['exit_time'] if old else None,variant_exit=new['exit_time'] if new else None,baseline_points=old['points'] if old else 0,variant_points=new['points'] if new else 0,net_delta=(new['points'] if new else 0)-(old['points'] if old else 0)))
 assert abs(sum(r['net_delta'] for r in out)-(sum(t['points'] for t in changed)-sum(t['points'] for t in b)))<1e-7
 return out

def run(args):
 end=date.fromisoformat(args.end_date);start=date.fromisoformat(args.start_date) if args.start_date else begin(end,3);out=args.output_root
 if out.exists():raise ValueError('Output exists; choose a fresh --output-root')
 out.mkdir(parents=True);index=base.cache_index(args.cache_root);warm=[];coverage=[];trades=[];daily=[];attr=[];hashes={};modules={p:policy_module(p) for p in POLICIES}
 for day,path in sorted(index.items()):
  if day>end.isoformat():continue
  data=json.loads(path.read_text());raw=data.get('candles') or [];hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
  if data.get('session_date') not in (None,day) or data.get('underlying') not in (None,'NSE_INDEX|Nifty 50'):raise ValueError('INVALID_NIFTY_CACHE:'+str(path))
  if day<start.isoformat():
   if raw:warm.append((day,raw))
   continue
  if not raw:coverage.append(dict(session_date=day,status='EMPTY_CACHE'));continue
  results={}
  try:
   for policy in POLICIES:results[policy]=modules[policy].replay(day,raw,warm,{'source':'SEPARATE_LOSS_RESEARCH','policy':policy})
   # All variants must succeed before this date contributes to any comparison.
   for policy,x in results.items():
    dump(out/'sessions'/day/(policy+'.json'),x);trades.extend(dict(session_date=day,policy=policy,**t) for t in x['trades'])
    dm=metrics(x['trades']);delta=round(dm['net']-metrics(results['BASELINE']['trades'])['net'],2);daily.append(dict(session_date=day,policy=policy,**dm,delta_vs_baseline=delta))
    if policy!='BASELINE':attr.extend(dict(session_date=day,policy=policy,**r) for r in attribution(results['BASELINE']['trades'],x['trades']))
   coverage.append(dict(session_date=day,status='EVALUATED'));print(json.dumps(dict(date=day,net={p:metrics(x['trades'])['net'] for p,x in results.items()})),flush=True)
  except (ValueError,KeyError,FileNotFoundError) as e:coverage.append(dict(session_date=day,status='FAILED_ALL_VARIANTS',issue=str(e)));print(day,str(e),flush=True)
  warm.append((day,raw))
 day=start
 while day<=end:
  if day.isoformat() not in index:coverage.append(dict(session_date=day.isoformat(),status='CACHE_MISSING'))
  day+=timedelta(days=1)
 summary=[]
 for months in (1,3):
  start_window=max(start,begin(end,months)).isoformat()
  for direction in ('ALL','BULLISH','BEARISH'):
   bm=metrics([t for t in trades if t['policy']=='BASELINE' and t['session_date']>=start_window and (direction=='ALL' or t['direction']==direction)])
   for policy in POLICIES:
    ts=[t for t in trades if t['policy']==policy and t['session_date']>=start_window and (direction=='ALL' or t['direction']==direction)];mm=metrics(ts)
    summary.append(dict(months=months,requested_start=begin(end,months).isoformat(),window_truncated=start>begin(end,months),start=start_window,end=end.isoformat(),direction=direction,policy=policy,evaluated_sessions=sum(c['status']=='EVALUATED' and c['session_date']>=start_window for c in coverage),**mm,delta_vs_baseline=round(mm['net']-bm['net'],2)))
 write(out/'summary.csv',summary);write(out/'daily.csv',daily);write(out/'trades.csv',trades);write(out/'losses.csv',[t for t in trades if t['points']<0]);write(out/'attribution.csv',attr);write(out/'coverage.csv',coverage)
 dump(out/'report.json',dict(model='HILEGA_V2_STRICT5M_VALIDATION_V1',baseline_rules=base.RULES,policies=POLICIES,summary=summary,coverage=coverage,input_sha256=hashes,engine_sha256=hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest(),strict_engine_sha256=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),execution_enabled=False,warning='Full causal replay, Nifty points before costs. Reconstructed inputs; no live parity claim. Empty/missing dates not assumed holidays. Candidates chosen using inspected historical evidence; no independent out-of-sample claim. Profit test uses closed-minute prices, not intrabar highs/lows.'))
 for row in summary:
  if row['direction']=='ALL':print(json.dumps(row),flush=True)
 print('Output:',out,'; live and Sandbox unchanged',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--start-date');p.add_argument('--end-date',default='2026-10-09');p.add_argument('--cache-root',action='append',type=Path);p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-v2-strict5m-validation-v1'));a=p.parse_args()
 if a.self_test:
  import unittest
  r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py'));sys.exit(not r.wasSuccessful())
 run(a)
