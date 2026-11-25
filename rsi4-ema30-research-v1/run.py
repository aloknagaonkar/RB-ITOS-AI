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
from engine import VERSION,PERIODS,replay


def export_csv(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def page(results):
    esc=lambda x:html.escape(str(x))
    val=lambda x:'—' if x is None else f'{x:.4f}' if isinstance(x,float) else str(x)
    sections=[]
    for result in results:
        sections.append('<h2>'+esc(result['session_date']+' · '+result.get('exit_variant',''))+'</h2>')
        if result.get('status'):
            sections.append('<p>'+esc(result['status'])+'</p>');continue
        sections.append('<pre>'+esc(json.dumps(result['summary'],indent=2))+'</pre>')
        headers=['Side','Signal IST','Entry IST','Exit IST','Entry NIFTY','Exit NIFTY','Points','Peak +','Giveback','Exit reason']
        body=[]
        for t in result['trades']:
            cells=[t['side'],t['entry_signal_time'][11:16],t['entry_time'][11:16],t['exit_time'][11:16],
                f"{t['entry_price']:.2f}",f"{t['exit_price']:.2f}",f"{t['points']:+.2f}",f"{t['peak_positive_points']:.2f}",f"{t['giveback_points']:.2f}",'; '.join(t['exit_reasons'])]
            body.append('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in cells)+'</tr>')
        sections.append('<div class="scroll"><table><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr>'+''.join(body)+'</table></div>')
        for a in result['audit']:
            f=a['frame'];parts=[]
            for side,info in a['entry_evaluation'].items():
                bull=side=='CE';rows=[]
                for key,passed in info['checks'].items():
                    if key.startswith('close_vs_'):
                        value='close '+val(f['close'])+'; EMA '+val(f['ema30_high' if bull else 'ema30_low']);require='Close > EMA30 High' if bull else 'Close < EMA30 Low'
                    elif key.startswith('wma'):
                        value=val(f['wma21_rsi9']);require='> 50' if bull else '< 50'
                    else:value=val(f[key.replace('_threshold','')]);require='> 55' if bull else '< 45'
                    label='PASS' if passed is True else 'FAIL' if passed is False else 'NOT READY'
                    rows.append('<tr><td>'+esc(key)+'</td><td class="'+label.lower().replace(' ','')+'">'+label+'</td><td>'+esc(value)+'</td><td>'+esc(require)+'</td></tr>')
                parts.append('<h4>'+side+' · '+esc(info['status'])+'</h4><p>Blockers: '+esc('; '.join(info['blockers']) or 'NONE')+'</p><table><tr><th>Entry condition</th><th>Result</th><th>Actual value</th><th>Requirement</th></tr>'+''.join(rows)+'</table>')
            parts.append('<h4>Active-position exit checks</h4><pre>'+esc(json.dumps(a['exit_evaluation'],indent=2))+'</pre>')
            parts.append('<h4>Accepted events and fills</h4><pre>'+esc(json.dumps(a['events'],indent=2))+'</pre>')
            sections.append('<details><summary>'+esc(a['decision_time'][11:16]+' IST | '+str(a['owner_before'])+' → '+str(a['owner_after']))+'</summary><p>Candle '+esc(f['start'][11:16])+'; O/H/L/C '+esc(' / '.join(val(f[k]) for k in ['open','high','low','close']))+'</p>'+''.join(parts)+'</details>')
    return '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RSI4 EMA30 research</title><style>body{font:14px/1.5 system-ui;background:#11252e;color:#d7e6ee;margin:24px}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #40545e;text-align:left}th{background:#233b48}.scroll{overflow:auto}details{background:#1a323e;border:1px solid #40545e;margin:14px 0;padding:12px}summary{cursor:pointer;font-weight:bold}pre{white-space:pre-wrap;overflow-wrap:anywhere}.pass{color:#38da98}.fail{color:#ff8795}.notready{color:#dfc881}button{padding:10px;margin:6px;cursor:pointer}h2{margin-top:36px}</style></head><body><h1>RSI(5/9/14/21) + EMA30 channel</h1><p>Fresh independent research. Completed 3-minute signals, next-minute-open simulated NIFTY fills. No option premium fills, fees or slippage. Exit conditions are proposed test variants, not validated trading recommendations. Same-bar exit then opposite entry is allowed; one position at a time. No extra Hilega filters or follow-up wait.</p><button onclick="document.querySelectorAll('details').forEach(x=>x.open=true)">Expand all candles</button><button onclick="document.querySelectorAll('details').forEach(x=>x.open=false)">Collapse all</button>'''+''.join(sections)+'</body></html>'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--days',nargs='+',default=['2026-11-20','2026-11-23'])
    p.add_argument('--variants',nargs='+',choices=['BALANCED','FAST','WMA'],default=['BALANCED'])
    args=p.parse_args();repo=args.repo.resolve();os.chdir(repo);sys.path.insert(0,str(repo/'backend'))
    from market_lab.hilega_three_minute_v1 import warmup as w
    from market_lab.hilega_three_minute_v1 import hilega_combined_replay_v1 as old
    out=repo/'data/research'/('rsi4-ema30-'+datetime.now(w.IST).strftime('%Y%m%dT%H%M%S%f'))
    out.mkdir(parents=True,exist_ok=False)
    index=old.cache_index();results=[];trade_rows=[];audit_rows=[]
    engine_sha=hashlib.sha256(Path(__file__).with_name('engine.py').read_bytes()).hexdigest()
    print('New strategy:',VERSION,'| completed 3m | exits:',','.join(args.variants),flush=True)
    def convert(b):return dict(start=b.ts.isoformat(),open=float(b.open),high=float(b.high),low=float(b.low),close=float(b.close))
    for key in dict.fromkeys(args.days):
        day=date.fromisoformat(key)
        try:
            if not w.session_day(day):
                results.append(dict(session_date=key,status='NON_TRADING_DAY'));print(key,'NON_TRADING_DAY',flush=True);continue
            if day==w.SPECIAL:
                results.append(dict(session_date=key,status='SHORT_SESSION_NOT_SUPPORTED_BY_THIS_RUNNER'));continue
            if key not in index:raise ValueError('VERIFIED_TARGET_CANDLES_MISSING')
            raw=w.read_session(index[key],day)
            warm,coverage=w.load_warmup(index,day,source=None)
            seed=[convert(b) for d,rows in warm for b in w.warmup_bars(rows,date.fromisoformat(d))]
            bars=[convert(b) for b in w.warmup_bars(raw,day)]
            for variant in dict.fromkeys(args.variants):
                print('Running fresh replay:',key,variant,'| warmup sessions',len(warm),flush=True)
                result=replay(key,bars,raw,seed,variant)
                result['input_evidence']=dict(target_path=str(index[key]),target_sha256=hashlib.sha256(Path(index[key]).read_bytes()).hexdigest(),warmup=coverage,engine_sha256=engine_sha)
                results.append(result)
                print('Side | Signal | Entry | Exit | Entry NIFTY | Exit NIFTY | Net | Peak + | Giveback | Exit reason',flush=True)
                for t in result['trades']:
                    print(f"{t['side']} | {t['entry_signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['entry_price']:.2f} | {t['exit_price']:.2f} | {t['points']:+.2f} | {t['peak_positive_points']:.2f} | {t['giveback_points']:.2f} | {'; '.join(t['exit_reasons'])}",flush=True)
                    print('  Entry indicators:',json.dumps({k:t['entry_frame'][k] for k in ['close','ema30_high','ema30_low','rsi5','rsi9','rsi14','rsi21','wma21_rsi9']}),flush=True)
                    print('  Exit indicators:',json.dumps({k:t['exit_frame'][k] for k in ['close','ema30_high','ema30_low','rsi5','rsi9','rsi14','rsi21','wma21_rsi9']}),flush=True)
                    flat={k:v for k,v in t.items() if not isinstance(v,(dict,list))};flat.update(session_date=key,exit_variant=variant,exit_reasons='; '.join(t['exit_reasons']))
                    for phase in ['entry','exit']:
                        flat.update({phase+'_'+k:v for k,v in t[phase+'_frame'].items() if k!='start'})
                    trade_rows.append(flat)
                for a in result['audit']:
                    for side,v in a['entry_evaluation'].items():
                        audit_rows.append(dict(session_date=key,exit_variant=variant,decision_time=a['decision_time'],side=side,
                            **a['frame'],**v['checks'],status=v['status'],blockers='; '.join(v['blockers']),owner_before=a['owner_before'],owner_after=a['owner_after'],
                            exit_evaluation=json.dumps(a['exit_evaluation']),events=json.dumps(a['events'])))
                print('SUMMARY',json.dumps(result['summary']),flush=True)
        except Exception as exc:
            results.append(dict(session_date=key,status='REPLAY_FAILED',error_type=type(exc).__name__,error=str(exc)))
            print(key,'REPLAY_FAILED',type(exc).__name__,str(exc),flush=True)
    report=dict(strategy_version=VERSION,results=results,application_source_modified=False,services_restarted=False,
                broker_requests_sent=False,original_caches_modified=False)
    (out/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    (out/'audit.html').write_text(page(results))
    export_csv(out/'trades.csv',trade_rows);export_csv(out/'candle-audit.csv',audit_rows)
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):z.write(f,f.name)
    print('HTML:',out/'audit.html',flush=True);print('UPLOAD ZIP:',archive,flush=True)


if __name__=='__main__':main()
