"""Read-only causal PCR support join through existing local API. No strategy filter."""
import argparse,csv,hashlib,json,math,sys,time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode,urlparse
from urllib.request import urlopen
from urllib.error import HTTPError,URLError

def timestamp(value):
 t=datetime.fromisoformat(value.replace('Z','+00:00'))
 if t.tzinfo is None:raise ValueError('Timezone required')
 return t

def number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def panel(ctx,mode,at,max_age):
 empty=dict(mode=mode,status='UNAVAILABLE',reason=ctx.get('reason') or 'NO_PANEL',combined_bias='UNAVAILABLE')
 if ctx.get('status')!='AVAILABLE':return empty
 try:
  available=timestamp(ctx['available_at']);age=(at-available).total_seconds()
  if available.date()!=at.date() or age<0 or age>max_age:return {**empty,'reason':'STALE_FUTURE_OR_WRONG_SESSION'}
  expiry=datetime.fromisoformat(ctx['expiry']).date()
  if expiry<at.date():return {**empty,'reason':'EXPIRED_CONTRACT'}
 except (ValueError,KeyError,TypeError):return {**empty,'reason':'MISSING_CAUSAL_TIME_OR_EXPIRY'}
 panels=[p for p in ctx.get('panels',[]) if p.get('mode')==mode]
 if len(panels)!=1:return empty
 p=panels[0];strikes=p.get('strikes') or [];values=[s.get('strike') for s in strikes]
 if len(strikes)!=11 or len(set(values))!=11 or p.get('expected')!=22 or p.get('received')!=22:return {**empty,'reason':'INCOMPLETE_ATM_PLUS_MINUS5'}
 if any(not number(s) for s in values) or sorted(values)[5]!=p.get('atm'):return {**empty,'reason':'ATM_NOT_BASKET_CENTER'}
 diffs=[b-a for a,b in zip(sorted(values),sorted(values)[1:])]
 if not diffs or diffs[0]<=0 or any(abs(d-diffs[0])>1e-8 for d in diffs):return {**empty,'reason':'NONCONTIGUOUS_STRIKE_BASKET'}
 for s in strikes:
  for side in ('ce','pe'):
   r=s.get(side) or {}
   if r.get('status')!='AVAILABLE' or r.get('side')!=side.upper() or r.get('strike')!=s['strike'] or not r.get('instrument_key'):return {**empty,'reason':'POSITIONING_BASELINE_OR_INSTRUMENT_UNAVAILABLE'}
   if any(not number(r.get(k)) for k in ('baseline_oi','current_oi','baseline_ltp','current_ltp')) or r['baseline_oi']<=0 or r['baseline_ltp']<=0:return {**empty,'reason':'MISSING_PRICE_OR_OI_BASELINE'}
   try:
    prior=timestamp(r['baseline_received_at'])
    if prior.date()!=at.date() or prior>=available or prior>at:return {**empty,'reason':'INVALID_BASELINE_TIME'}
   except (ValueError,KeyError,TypeError):return {**empty,'reason':'MISSING_BASELINE_TIME'}
 if p.get('combined_bias') not in ('BULLISH','BEARISH','NEUTRAL','MIXED') or not number(p.get('pcr')):return {**empty,'reason':'CLASSIFICATION_OR_PCR_UNAVAILABLE'}
 return dict(mode=mode,status='AVAILABLE',reason='',atm=p['atm'],expiry=ctx['expiry'],combined_bias=p['combined_bias'],pcr=p['pcr'],ce_positioning=p.get('ce_positioning'),pe_positioning=p.get('pe_positioning'),ce_oi_change_pct=p.get('ce_oi_change_pct'),pe_oi_change_pct=p.get('pe_oi_change_pct'),available_at=ctx['available_at'],age_seconds=age,observation_id=ctx.get('observation_id'))

def category(direction,fixed,moving):
 if any(p['status']!='AVAILABLE' for p in (fixed,moving)):return 'UNAVAILABLE'
 f=fixed['combined_bias'];m=moving['combined_bias'];opposite='BEARISH' if direction=='BULLISH' else 'BULLISH'
 if {f,m}=={'BULLISH','BEARISH'}:return 'CONFLICTING_DIRECTIONS'
 if f==direction and m==direction:return 'BOTH_SUPPORT'
 if f==opposite and m==opposite:return 'BOTH_OPPOSE'
 if f==direction:return 'FIXED_SUPPORT_ONLY'
 if m==direction:return 'MOVING_SUPPORT_ONLY'
 return 'NEITHER_SUPPORT'

def query(base,at,horizon,max_age):
 endpoint=base.rstrip('/')+'/api/live-shadow/hilega-pcr/context?'+urlencode(dict(at=at,horizon=horizon,max_age=max_age))
 with urlopen(endpoint,timeout=30) as r:return json.load(r)

def metrics(rows):
 gains=sum(max(float(r['points']),0) for r in rows);losses=sum(max(-float(r['points']),0) for r in rows)
 return dict(trades=len(rows),winners=sum(float(r['points'])>0 for r in rows),losers=sum(float(r['points'])<0 for r in rows),gains=round(gains,2),losses=round(losses,2),net=round(gains-losses,2),gain_loss_ratio=gains/losses if losses else None)
def write(path,rows):
 keys=list(dict.fromkeys(k for r in rows for k in r)) or ['session_date']
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def run(a):
 url=urlparse(a.base_url)
 if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost') or url.path not in ('','/') or url.query or url.username:raise ValueError('Local read-only API URL required')
 if a.output_root.exists():raise ValueError('Output exists; choose a new --output-root')
 raw=list(csv.DictReader(a.trades.open()));trades=[r for r in raw if a.start_date<=r['session_date']<=a.end_date]
 if not trades:raise ValueError('No trades in selected dates')
 if len({r['trade_id'] for r in trades})!=len(trades):raise ValueError('Duplicate trade IDs')
 for r in trades:
  if r['direction'] not in ('BULLISH','BEARISH'):raise ValueError('Invalid direction')
  for field in ('signal_time','entry_time'):timestamp(r[field])
 a.output_root.mkdir(parents=True);cache={};rows=[];fixed_values={};errors=[]
 for r in sorted(trades,key=lambda r:r['entry_time']):
  for stage,field in [('SIGNAL','signal_time'),('ENTRY','entry_time')]:
   at=timestamp(r[field]);k=at.isoformat()
   if k not in cache:
    try:cache[k]=query(a.base_url,k,a.horizon,a.max_age)
    except (HTTPError,URLError,TimeoutError,ValueError) as e:
     cache[k]=dict(status='UNAVAILABLE',reason='API_ERROR',error=str(e));errors.append(dict(timestamp=k,error=str(e)))
    time.sleep(.05)
   ctx=cache[k];fixed=panel(ctx,'fixed',at,a.max_age);moving=panel(ctx,'moving',at,a.max_age)
   if fixed['status']=='AVAILABLE':fixed_values.setdefault((r['session_date'],fixed['expiry']),set()).add(fixed['atm'])
   row=dict(**r,stage=stage,decision_time=k,support_category=category(r['direction'],fixed,moving))
   for mode,p in [('fixed',fixed),('moving',moving)]:row.update({mode+'_'+key:value for key,value in p.items() if key!='mode'})
   rows.append(row)
 for r in rows:
  expiry=r.get('fixed_expiry')
  if expiry and len(fixed_values.get((r['session_date'],expiry),set()))>1:
   r.update(fixed_status='UNAVAILABLE',fixed_reason='FIXED_ATM_CHANGED_WITHIN_SESSION',fixed_combined_bias='UNAVAILABLE',support_category='UNAVAILABLE')
 summary=[];daily=[]
 for stage in ('SIGNAL','ENTRY'):
  for direction in ('ALL','BULLISH','BEARISH'):
   rr=[r for r in rows if r['stage']==stage and (direction=='ALL' or r['direction']==direction)]
   for cat in sorted({r['support_category'] for r in rr}):summary.append(dict(stage=stage,direction=direction,support_category=cat,**metrics([r for r in rr if r['support_category']==cat])))
 for day in sorted({r['session_date'] for r in trades}):
  for stage in ('SIGNAL','ENTRY'):
   rr=[r for r in rows if r['session_date']==day and r['stage']==stage]
   daily.append(dict(session_date=day,stage=stage,trades=len(rr),fixed_available=sum(r['fixed_status']=='AVAILABLE' for r in rr),moving_available=sum(r['moving_status']=='AVAILABLE' for r in rr),both_support=sum(r['support_category']=='BOTH_SUPPORT' for r in rr),unavailable=sum(r['support_category']=='UNAVAILABLE' for r in rr)))
 write(a.output_root/'trade-support.csv',rows);write(a.output_root/'summary.csv',summary);write(a.output_root/'coverage.csv',daily)
 (a.output_root/'contexts.json').write_text(json.dumps(cache,indent=2))
 report=dict(model='HILEGA_PCR_SIGNAL_SUPPORT_DIAGNOSTIC_V1',start=a.start_date,end=a.end_date,horizon_seconds=a.horizon,max_age_seconds=a.max_age,source_trade_sha256=hashlib.sha256(a.trades.read_bytes()).hexdigest(),coverage=daily,summary=summary,api_errors=errors,execution_enabled=False,warning='Recorded causal PCR context joined to reconstructed V2 signals/entries. Not a full strategy-filter replay. PCR alone does not set bias. Existing 60% absolute-OI-change weighted positioning method. Fixed basket center consistency checked only across queried points; anchor capture timing is not independently verified. No historical option OI downloaded or invented. Missing observations remain unavailable.')
 (a.output_root/'report.json').write_text(json.dumps(report,indent=2))
 for row in daily:print(json.dumps(row),flush=True)
 for row in summary:
  if row['stage']=='ENTRY' and row['direction']=='ALL':print(json.dumps(row),flush=True)
 print('Output:',a.output_root,'; no strategy, collector, order or service changes')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--trades',type=Path,default=Path('data/historical-evidence/hilega-v2-monthly-validation-v1/trades.csv'));p.add_argument('--start-date',default='2026-10-06');p.add_argument('--end-date',default='2026-10-09');p.add_argument('--base-url',default='http://127.0.0.1:8123');p.add_argument('--horizon',type=int,choices=[300,900,1800],default=300);p.add_argument('--max-age',type=int,default=120);p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-pcr-signal-support-oct6-9-v1'));a=p.parse_args()
 if a.self_test:
  import unittest
  result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py'));sys.exit(not result.wasSuccessful())
 if not 1<=a.max_age<=300:p.error('max-age must be 1..300 seconds')
 run(a)
