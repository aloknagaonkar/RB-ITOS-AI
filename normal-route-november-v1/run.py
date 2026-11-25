#!/usr/bin/env python3
"""Fresh offline RSI strategy replay from verified VM candle caches."""
import argparse
import csv
from datetime import date,datetime
import hashlib
import html
import json
import os
from pathlib import Path
import sys
import zipfile
from engine import VERSION,PERIODS,ROUTE_NAME,ROUTE_ID,replay


def export_csv(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


from monthly_report import page, daily_rows, totals, requested_days

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--days',nargs='+')
    p.add_argument('--month',default='2026-11')
    p.add_argument('--through',default='2026-11-23')
    p.add_argument('--variants',nargs='+',choices=['ALL_THREE'],default=['ALL_THREE'])
    args=p.parse_args();repo=args.repo.resolve();os.chdir(repo);sys.path.insert(0,str(repo/'backend'))
    from market_lab.hilega_three_minute_v1 import warmup as w
    from market_lab.hilega_three_minute_v1 import hilega_combined_replay_v1 as old
    out=repo/'data/research'/('normal-route-november-'+datetime.now(w.IST).strftime('%Y%m%dT%H%M%S%f'))
    out.mkdir(parents=True,exist_ok=False)
    index=old.cache_index();results=[];trade_rows=[];audit_rows=[]
    engine_sha=hashlib.sha256(Path(__file__).with_name('engine.py').read_bytes()).hexdigest()
    print(ROUTE_NAME,'|',VERSION,'| completed 3m | exits:',','.join(args.variants),flush=True)
    def convert(b):return dict(start=b.ts.isoformat(),open=float(b.open),high=float(b.high),low=float(b.low),close=float(b.close))
    days=requested_days(args.days,args.month,args.through,datetime.now(w.IST).date())
    for key in days:
        day=date.fromisoformat(key)
        try:
            if not w.session_day(day):
                results.append(dict(session_date=key,status='NON_TRADING_DAY'));print(key,'NON_TRADING_DAY',flush=True);continue
            if key not in index:raise ValueError('VERIFIED_TARGET_CANDLES_MISSING')
            raw=w.read_session(index[key],day)
            warm,coverage=w.load_warmup(index,day,source=None)
            seed=[convert(b) for d,rows in warm for b in w.warmup_bars(rows,date.fromisoformat(d))]
            bars=[convert(b) for b in w.warmup_bars(raw,day)]
            for variant in dict.fromkeys(args.variants):
                print('Running fresh replay:',key,variant,'| warmup sessions',len(warm),flush=True)
                result=replay(key,bars,raw,seed,variant)
                result['session_kind']='SHORT_14:20_15:30_23_COMPLETE_BARS' if day==w.SPECIAL else 'REGULAR'
                result['session_open']=raw[0]['open'];result['session_close']=raw[-1]['close']
                result['market_trend']='BULLISH' if raw[-1]['close']>raw[0]['open'] else 'BEARISH' if raw[-1]['close']<raw[0]['open'] else 'FLAT'
                result['input_evidence']=dict(target_path=str(index[key]),target_sha256=hashlib.sha256(Path(index[key]).read_bytes()).hexdigest(),warmup=coverage,engine_sha256=engine_sha)
                results.append(result)
                print('Side | Signal | Entry | Exit | Entry NIFTY | Exit NIFTY | Net | Peak + | Giveback | Exit reason',flush=True)
                for t in result['trades']:
                    print(f"{t['side']} | {t['entry_signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['entry_price']:.2f} | {t['exit_price']:.2f} | {t['points']:+.2f} | {t['peak_positive_points']:.2f} | {t['giveback_points']:.2f} | {'; '.join(t['exit_reasons'])}",flush=True)
                    print('  Entry indicators:',json.dumps({k:t['entry_frame'][k] for k in ['open','close','ema30_high','ema30_low','rsi5','rsi9','rsi14','rsi21','rsi28','wma21_rsi9']}),flush=True)
                    print('  Exit indicators:',json.dumps({k:t['exit_frame'][k] for k in ['close','ema30_high','ema30_low','rsi5','rsi9','rsi14','rsi21','rsi28','wma21_rsi9']}),flush=True)
                    flat={k:v for k,v in t.items() if not isinstance(v,(dict,list))};flat.update(session_date=key,exit_variant=variant,exit_reasons='; '.join(t['exit_reasons']))
                    for phase in ['entry','exit']:
                        flat.update({phase+'_'+k:v for k,v in t[phase+'_frame'].items() if k!='start'})
                    trade_rows.append(flat)
                for a in result['audit']:
                    for side,v in a['entry_evaluation'].items():
                        audit_rows.append(dict(route_name=ROUTE_NAME,route_id=ROUTE_ID,session_date=key,exit_variant=variant,decision_time=a['decision_time'],side=side,
                            **a['frame'],**v['checks'],status=v['status'],blockers='; '.join(v['blockers']),owner_before=a['owner_before'],owner_after=a['owner_after'],
                            exit_evaluation=json.dumps(a['exit_evaluation']),events=json.dumps(a['events'])))
                print('SUMMARY',json.dumps(result['summary']),flush=True)
        except Exception as exc:
            results.append(dict(session_date=key,status='REPLAY_FAILED',error_type=type(exc).__name__,error=str(exc)))
            print(key,'REPLAY_FAILED',type(exc).__name__,str(exc),flush=True)
    aggregate=totals([t for r in results for t in r.get('trades',[])])
    failures=[r for r in results if r.get('status')=='REPLAY_FAILED']
    print('MONTH SUMMARY',json.dumps(aggregate),flush=True)
    print('COVERAGE',json.dumps(dict(replayed=sum('summary' in r for r in results),failed=len(failures),non_trading=sum(r.get('status')=='NON_TRADING_DAY' for r in results))),flush=True)
    report=dict(report_version='normal-route-november-report-1.0',generator_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},status='PARTIAL_FAILURE' if failures else 'REPLAY_COMPLETE',requested_days=days,month_summary=aggregate,route_name=ROUTE_NAME,route_id=ROUTE_ID,strategy_version=VERSION,results=results,application_source_modified=False,services_restarted=False,
                broker_requests_sent=False,original_caches_modified=False)
    (out/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    (out/'audit.html').write_text(page(results))
    export_csv(out/'daily-summary.csv',daily_rows(results));export_csv(out/'trades.csv',trade_rows);export_csv(out/'candle-audit.csv',audit_rows)
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):z.write(f,f.name)
    print('HTML:',out/'audit.html',flush=True);print('UPLOAD ZIP:',archive,flush=True)
    if failures:raise SystemExit(2)


if __name__=='__main__':main()
