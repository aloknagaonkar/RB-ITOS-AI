#!/usr/bin/env python3
"""Research-only monthly comparison: frozen confirmed-midpoint strategy versus two-route control."""
import argparse,csv,hashlib,json,os,sys,zipfile,html
from datetime import date,datetime
from pathlib import Path
import engine,baseline
from monthly_report import page,totals,daily_rows,requested_days

MODELS={'UPDATED':engine,'BASELINE':baseline}

def export_csv(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)

def comparison(results):
    esc=lambda s:html.escape(str(s));rows=[]
    for key in sorted({r['session_date'] for r in results}):
        values=[key]
        for model in ('BASELINE','UPDATED'):
            r=next(r for r in results if r['session_date']==key and r['model']==model)
            values.extend([r.get('status','REPLAYED'),r.get('summary',{}).get('trades','—'),round(r['summary']['net_points'],2) if 'summary' in r else '—'])
        rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
    summary={m:totals([t for r in results if r['model']==m for t in r.get('trades',[])]) for m in MODELS}
    return '<!doctype html><html><meta charset="utf-8"><title>Two-route comparison</title><style>body{font:16px system-ui;margin:24px}td,th{padding:10px;border:1px solid #aaa}table{border-collapse:collapse}pre{white-space:pre-wrap}</style><h1>Two-route control versus confirmed midpoint exit</h1><p>Same verified candles, 20 prior seed sessions, next-minute-open simulated NIFTY fills; no costs or option premiums. Both use identical Normal Route (2/5 RSI with WMA) and WMA_bypass (5/5 RSI), colour/EMA gates and opposite-entry reversals. Updated adds midpoint close plus RSI5/RSI9 confirmation; control retains the original exits. No body/wick filters or entry follow-up.</p><p><a href="audit.html">Updated filterable audit</a> · <a href="baseline-audit.html">Two-route control audit</a></p><pre>'+esc(json.dumps(summary,indent=2))+'</pre><table><tr>'+''.join('<th>'+x+'</th>' for x in ['Date','Baseline status','Baseline trades','Baseline net','Updated status','Updated trades','Updated net'])+'</tr>'+''.join(rows)+'</table></html>'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--days',nargs='+');p.add_argument('--month',default='2026-10');p.add_argument('--through',default='2026-10-31');p.add_argument('--recover-missing',action='store_true');p.add_argument('--export-inputs',action='store_true');args=p.parse_args()
    repo=args.repo.resolve();os.chdir(repo);sys.path.insert(0,str(repo/'backend'))
    from market_lab.hilega_three_minute_v1 import warmup as w
    from market_lab.hilega_three_minute_v1 import hilega_combined_replay_v1 as old
    days=requested_days(args.days,args.month,args.through,datetime.now(w.IST).date())
    out=repo/'data/research'/('rsi-confirmed-midpoint-'+datetime.now(w.IST).strftime('%Y%m%dT%H%M%S%f'));out.mkdir(parents=True,exist_ok=False)
    index=old.cache_index();results=[];trade_rows=[];audit_rows=[]
    source=None
    if args.recover_missing:
        from dotenv import load_dotenv
        from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
        load_dotenv(repo/'.env')
        token=os.getenv('UPSTOX_ACCESS_TOKEN','')
        if not token:raise ValueError('UPSTOX_ACCESS_TOKEN_MISSING_FOR_READ_ONLY_RECOVERY')
        source=UpstoxLiveShadowSourcesV1(token)
    recovery=[]
    print('UPDATED',engine.VERSION,'| BASELINE',baseline.VERSION,flush=True)
    convert=lambda b:dict(start=b.ts.isoformat(),open=float(b.open),high=float(b.high),low=float(b.low),close=float(b.close))
    for key in days:
        day=date.fromisoformat(key)
        try:
            if not w.session_day(day):
                for model in MODELS:results.append(dict(model=model,session_date=key,status='NON_TRADING_DAY'))
                print(key,'NON_TRADING_DAY',flush=True);continue
            if args.recover_missing or args.export_inputs:
                from inputs import resolve_sessions
                recovery.extend(resolve_sessions(w,index,day,source=source,cache_root=out/'verified-inputs',export_inputs=args.export_inputs))
            if key not in index:raise ValueError('VERIFIED_TARGET_CANDLES_MISSING')
            raw=w.read_session(index[key],day);warm,coverage=w.load_warmup(index,day,source=None)
            seed=[convert(b) for d,rs in warm for b in w.warmup_bars(rs,date.fromisoformat(d))];bars=[convert(b) for b in w.warmup_bars(raw,day)]
        except Exception as exc:
            for model in MODELS:results.append(dict(model=model,session_date=key,status='REPLAY_FAILED',error=str(exc),error_type=type(exc).__name__))
            print(key,'INPUT_FAILED',type(exc).__name__,str(exc),flush=True);continue
        for model,module in MODELS.items():
            try:
                print('Running fresh replay:',key,model,'| warmup sessions',len(warm),flush=True)
                r=module.replay(key,bars,raw,seed);r.update(model=model,session_kind='SHORT_23_COMPLETE_BARS' if day==w.SPECIAL else 'REGULAR',session_open=raw[0]['open'],session_close=raw[-1]['close'],market_trend='BULLISH' if raw[-1]['close']>raw[0]['open'] else 'BEARISH' if raw[-1]['close']<raw[0]['open'] else 'FLAT')
                r['input_evidence']=dict(target_path=str(index[key]),target_sha256=hashlib.sha256(Path(index[key]).read_bytes()).hexdigest(),warmup=coverage,engine_sha256=hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
                trades=[];audits=[]
                print('Side | Route | Entry | Exit | Entry NIFTY | Exit NIFTY | Net | Peak + | Giveback | Exit reason',flush=True)
                for t in r['trades']:
                    print(f"{t['side']} | {t['route_name']} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['entry_price']:.2f} | {t['exit_price']:.2f} | {t['points']:+.2f} | {t['peak_positive_points']:.2f} | {t['giveback_points']:.2f} | {'; '.join(t['exit_reasons'])}",flush=True)
                    for phase in ('entry','exit'):print(' ',phase.title(),'indicators:',json.dumps(t[phase+'_frame']),flush=True)
                    flat={k:v for k,v in t.items() if not isinstance(v,(dict,list))};flat.update(model=model,session_date=key,exit_reasons='; '.join(t['exit_reasons']))
                    for phase in ('entry','exit'):flat.update({phase+'_'+k:v for k,v in t[phase+'_frame'].items()})
                    trades.append(flat)
                for a in r['audit']:
                    for side,v in a['entry_evaluation'].items():
                        audits.append(dict(model=model,session_date=key,decision_time=a['decision_time'],side=side,selected_route=v.get('selected_route',''),rsi_pass_count=v.get('rsi_pass_count',''),**a['frame'],**v['checks'],status=v['status'],blockers='; '.join(v['blockers']),route_checks=json.dumps(v.get('route_checks')),route_blockers=json.dumps(v.get('route_blockers')),candle_strength=json.dumps(v.get('candle_strength')),owner_before=a['owner_before'],owner_after=a['owner_after'],exit_evaluation=json.dumps(a['exit_evaluation']),events=json.dumps(a['events'])))
                results.append(r);trade_rows.extend(trades);audit_rows.extend(audits);print(model,'SUMMARY',json.dumps(r['summary']),flush=True)
            except Exception as exc:
                results.append(dict(model=model,session_date=key,status='REPLAY_FAILED',error=str(exc),error_type=type(exc).__name__));print(key,model,'REPLAY_FAILED',type(exc).__name__,str(exc),flush=True)
    summaries={m:totals([t for r in results if r['model']==m for t in r.get('trades',[])]) for m in MODELS}
    coverage={m:dict(replayed=sum('summary' in r for r in results if r['model']==m),failed=sum(r.get('status')=='REPLAY_FAILED' for r in results if r['model']==m),non_trading=sum(r.get('status')=='NON_TRADING_DAY' for r in results if r['model']==m)) for m in MODELS}
    failed=any(v['failed'] for v in coverage.values());report=dict(status='PARTIAL_FAILURE' if failed else 'REPLAY_COMPLETE',strategy_version=engine.VERSION,requested_days=days,input_recovery=recovery,month_summary=summaries,coverage=coverage,results=results,generator_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},application_source_modified=False,services_restarted=False,broker_requests_sent=False,original_caches_modified=False)
    (out/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    for model,name in [('UPDATED','audit.html'),('BASELINE','baseline-audit.html')]:
        (out/name).write_text(page([r for r in results if r['model']==model],updated=model=='UPDATED'))
    (out/'comparison.html').write_text(comparison(results))
    export_csv(out/'daily-summary.csv',[dict(model=m,**row) for m in MODELS for row in daily_rows([r for r in results if r['model']==m])]);export_csv(out/'trades.csv',trade_rows);export_csv(out/'candle-audit.csv',audit_rows)
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob('*')):
            if f.is_file():z.write(f,str(f.relative_to(out)))
    print('MONTH SUMMARY',json.dumps(summaries),flush=True);print('COVERAGE',json.dumps(coverage),flush=True);print('HTML:',out/'audit.html',flush=True);print('COMPARISON HTML:',out/'comparison.html',flush=True);print('UPLOAD ZIP:',archive,flush=True)
    if failed:raise SystemExit(2)

if __name__=='__main__':main()
