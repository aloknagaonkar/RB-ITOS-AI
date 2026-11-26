#!/usr/bin/env python3
"""Fresh intraday research replay; never changes strategy services, controls or orders."""
import csv,hashlib,html,importlib,importlib.util,json,os,sys,types
from datetime import datetime,timedelta
from pathlib import Path

def load_engine(repo):
    package=repo/'hilega-rsi-zones-moderate-v3'
    if not package.is_dir():raise ValueError('EXTRACT_HILEGA_RSI_ZONES_MODERATE_V3_FIRST')
    manifest=json.loads((package/'manifest.json').read_text())
    installed=repo/'backend/market_lab/hilega_rsi_two_route_v1'
    prefix='backend/market_lab/hilega_rsi_two_route_v1/'
    for name in ('__init__.py','engine.py','policy.py'):
        path=package/'files'/prefix/name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['package_files']['files/'+prefix+name]:raise ValueError('RESEARCH_PACKAGE_CHANGED:'+name)
    expected=manifest['guard_files'][prefix+'reference.py']
    if hashlib.sha256((installed/'reference.py').read_bytes()).hexdigest()!=expected:raise ValueError('REFERENCE_ENGINE_CHANGED')
    name='market_lab.hilega_rsi_today_isolated';module=types.ModuleType(name)
    module.__path__=[str(package/'files'/prefix),str(installed)];module.__package__=name
    sys.modules[name]=module
    exec(compile((package/'files'/prefix/'__init__.py').read_text(),'<research-identity>','exec'),module.__dict__)
    return importlib.import_module(name+'.engine').Engine

def print_result(result):
    print('\nSide | Route | Setup | Entry | Exit | Entry NIFTY | Exit NIFTY | Net | Peak + | Giveback | Exit reason')
    for t in result['trades']:
        print(f"{t['side']} | {t['route_name']} | {t['entry_candle_start'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['entry_price']:.2f} | {t['exit_price']:.2f} | {t['points']:+.2f} | {t['peak_positive_points']:.2f} | {t['giveback_points']:.2f} | {'; '.join(t['exit_reasons'])}")
    if not result['trades']:print('No closed trades yet.')
    print('\nCLOSED TRADE SUMMARY:',json.dumps(result['summary'],indent=2))
    t=result['active_trade'];print('\nOPEN TRADE:',json.dumps({k:t.get(k) for k in ('side','route_name','entry_time','entry_price')} if t else None,indent=2))
    print('OPEN POINTS / PEAK / GIVEBACK:',json.dumps(result['open_metrics'],indent=2))

def write_report(out,payload):
    result=payload['result'];rows=[]
    for a in result['audit']:
        for side,e in a['entry_evaluation'].items():
            events=[v for v in a['events'] if v['side']==side]
            status='ENTRY ACCEPTED' if any(v['event']=='ENTRY' for v in events) else 'EXIT ACCEPTED' if any(v['event']=='EXIT' for v in events) else 'ACTIVE / NO NEW ENTRY' if side in (a['owner_before'],a['owner_after']) else 'BLOCKED / WAIT'
            rows.append(dict(decision=a['decision_time'],side=side,status=status,route=e['selected_route'],rsi_votes=e['rsi_pass_count'],blockers='; '.join(e['blockers']),frame=a['frame'],entry_checks=e['checks'],route_checks=e['route_checks'],strength=e.get('moderate_entry_strength'),zone=e.get('confirmation_audit'),exit_checks=a['exit_evaluation'],events=events))
    out.mkdir(parents=True)
    (out/'audit.json').write_text(json.dumps(payload,indent=2,allow_nan=False,default=str))
    with (out/'signals.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)
    esc=lambda x:html.escape(str(x))
    def table(headers,data):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(k)+'</th>' for k in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in data)+'</tbody></table></div>'
    trades=[[t['side'],t['route_name'],t['entry_candle_start'][11:16],t['entry_time'][11:16],t['exit_time'][11:16],f"{t['entry_price']:.2f}",f"{t['exit_price']:.2f}",f"{t['points']:+.2f}",'WIN' if t['points']>0 else 'LOSS' if t['points']<0 else 'BREAKEVEN',f"{t['peak_positive_points']:.2f}",f"{t['giveback_points']:.2f}",'; '.join(t['exit_reasons'])] for t in result['trades']]
    body='<h1>RSI exit + EMA zones · MODERATE_EVERY_ENTRY</h1><p>'+esc(payload['as_of'])+' IST snapshot. Research replay; not executed trade history. Fees/slippage excluded. Open positions are not forced closed.</p><h2>Accepted trades · entry / exit / points</h2>'+table(['Side','Route','Setup','Entry','Exit','Entry NIFTY','Exit NIFTY','Net','Result','Peak +','Giveback','Exit reason'],trades)+'<h2>Open trade and closed summary</h2><pre>'+esc(json.dumps({k:result[k] for k in ('active_trade','open_metrics','summary')},indent=2))+'</pre><h2>Every completed 3-minute decision · both directions</h2><p>Use browser Find to search a time or blocker. Open Details for exact values, both route gates, strength, zones and exit conditions. A failed alternative route does not necessarily prevent entry through the other route.</p>'
    for r in rows:
        body+='<details><summary>'+esc(r['decision'][11:16]+' · '+r['side']+' · '+r['status']+' · '+(r['route'] or 'No route')+' · '+r['blockers'])+'</summary><pre>'+esc(json.dumps(r,indent=2))+'</pre></details>'
    css='body{font:15px system-ui;background:#10212b;color:#e1eef4;padding:24px}h1,h2{color:#8ee5cf}.scroll{overflow:auto}table{border-collapse:collapse;white-space:nowrap}td,th{border:1px solid #385766;padding:10px;text-align:left}summary{cursor:pointer;padding:12px;border-bottom:1px solid #385766}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:16px;background:#192f3b}p{line-height:1.5}'
    (out/'audit.html').write_text('<!doctype html><html><meta charset="utf-8"><title>Today Hilega signal audit</title><style>'+css+'</style><body>'+body+'</body></html>')

def main():
    repo=Path.cwd();sys.path.insert(0,str(repo/'backend'))
    from dotenv import load_dotenv
    load_dotenv(repo/'.env')
    from market_lab.domain import IST
    from market_lab.hilega_rsi_two_route_v1.data import seed,aggregate
    from market_lab.hilega_rsi_two_route_v1.live import normalize_prefix
    from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
    now=datetime.now(IST);day=now.date();Engine=load_engine(repo)
    print('DATE:',day,'| RSI_EXIT_EMA_ZONES__MODERATE_EVERY_ENTRY',flush=True)
    source=UpstoxLiveShadowSourcesV1(os.getenv('UPSTOX_ACCESS_TOKEN',''))
    print('Fetching fresh intraday NIFTY candles...',flush=True)
    items=source.nifty_intraday_1m(now=now)
    raw=[dict(timestamp=c.timestamp.astimezone(IST).isoformat(),open=float(c.open),high=float(c.high),low=float(c.low),close=float(c.close),volume=getattr(c,'volume',None)) for c in items]
    complete,forming=normalize_prefix(raw,day,now)
    if not complete:raise ValueError('NO_COMPLETED_MINUTES_YET')
    grid=complete[1:] if str(day)=='2026-11-08' else complete
    ready=aggregate(grid[:len(grid)//3*3]);references=complete+forming;available={r['timestamp'] for r in references}
    print('Completed minute candles:',len(complete),'| completed 3m candles:',len(ready),flush=True)
    print('Loading 20 verified prior sessions from existing caches...',flush=True)
    warm,evidence=seed(repo,day);engine=Engine(str(day),warm)
    for bar in ready:
        boundary=datetime.fromisoformat(bar['start'])+timedelta(minutes=3)
        if boundary.strftime('%H:%M')!='15:30' and boundary.isoformat() not in available:
            print('Waiting for next-minute OPEN:',boundary.isoformat());break
        engine.advance(bar,references)
    result=engine.result()
    if not result['audit']:raise ValueError('NO_DECISION_WITH_FILL_REFERENCE_YET')
    print('LAST DECISION:',result['audit'][-1]['decision_time']);print_result(result)
    out=repo/'data/research'/('rsi-zones-moderate-fresh-'+now.strftime('%Y%m%dT%H%M%S%f'))
    write_report(out,dict(configuration='RSI_EXIT_EMA_ZONES__MODERATE_EVERY_ENTRY',as_of=now.isoformat(),warmup=evidence,result=result))
    print('\nHTML:',out/'audit.html');print('JSON:',out/'audit.json');print('SIGNALS CSV:',out/'signals.csv')
    print('Research only. No live rules, services, execution controls or orders changed.')
if __name__=='__main__':main()
