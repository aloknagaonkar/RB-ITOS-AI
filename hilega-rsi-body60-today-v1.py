#!/usr/bin/env python3
"""Fresh intraday research replay; never changes strategy services, controls or orders."""
import csv,hashlib,html,importlib,importlib.util,json,os,sys,types
from datetime import datetime,timedelta
from pathlib import Path

def load_engine(repo,body_min=50):
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
    if body_min not in (50,60):raise ValueError('UNSUPPORTED_BODY_THRESHOLD')
    name='market_lab.hilega_rsi_today_body'+str(body_min);module=types.ModuleType(name)
    module.__path__=[str(package/'files'/prefix),str(installed)];module.__package__=name
    sys.modules[name]=module
    exec(compile((package/'files'/prefix/'__init__.py').read_text(),'<research-identity>','exec'),module.__dict__)
    policy_source=(package/'files'/prefix/'policy.py').read_text()
    if body_min==60:
        needle='body_at_least_50pct=valid and body+eps>=.5*span'
        if policy_source.count(needle)!=1:raise ValueError('BODY_RULE_SOURCE_CHANGED')
        policy_source=policy_source.replace(needle,'body_at_least_60pct=valid and body+eps>=.6*span')
        module.VERSION+='-research-body60'
    policy=types.ModuleType(name+'.policy');policy.__package__=name;sys.modules[policy.__name__]=policy
    exec(compile(policy_source,'<isolated-body-rule>','exec'),policy.__dict__)
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
    body='<h1>'+esc(payload.get('configuration','RSI exit + EMA zones'))+'</h1><p>'+esc(payload['as_of'])+' IST snapshot. Research replay; not executed trade history. Fees/slippage excluded. Open positions are not forced closed.</p><h2>Accepted trades · entry / exit / points</h2>'+table(['Side','Route','Setup','Entry','Exit','Entry NIFTY','Exit NIFTY','Net','Result','Peak +','Giveback','Exit reason'],trades)+'<h2>Open trade and closed summary</h2><pre>'+esc(json.dumps({k:result[k] for k in ('active_trade','open_metrics','summary')},indent=2))+'</pre><h2>Every completed 3-minute decision · both directions</h2><p>Use browser Find to search a time or blocker. Open Details for exact values, both route gates, strength, zones and exit conditions. A failed alternative route does not necessarily prevent entry through the other route.</p>'
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
    now=datetime.now(IST);day=now.date()
    engines={n:load_engine(repo,n) for n in (50,60)}
    print('DATE:',day,'| SAME fresh candles and same verified warmup for BODY50 vs BODY60',flush=True)
    source=UpstoxLiveShadowSourcesV1(os.getenv('UPSTOX_ACCESS_TOKEN',''))
    print('Fetching fresh intraday NIFTY candles...',flush=True)
    items=source.nifty_intraday_1m(now=now)
    now=datetime.now(IST)
    if now.date()!=day:raise ValueError('SESSION_DATE_CHANGED_DURING_FETCH')
    raw=[dict(timestamp=c.timestamp.astimezone(IST).isoformat(),open=float(c.open),high=float(c.high),low=float(c.low),close=float(c.close),volume=getattr(c,'volume',None)) for c in items]
    complete,forming=normalize_prefix(raw,day,now)
    if not complete:raise ValueError('NO_COMPLETED_MINUTES_YET')
    grid=complete[1:] if str(day)=='2026-11-08' else complete
    ready=aggregate(grid[:len(grid)//3*3]);references=complete+forming;available={r['timestamp'] for r in references}
    eligible=[]
    for bar in ready:
        boundary=datetime.fromisoformat(bar['start'])+timedelta(minutes=3)
        if boundary.strftime('%H:%M')!='15:30' and boundary.isoformat() not in available:break
        eligible.append(bar)
    if not eligible:raise ValueError('NO_DECISION_WITH_FILL_REFERENCE_YET')
    print('Completed minutes:',len(complete),'| processed 3m candles:',len(eligible),flush=True)
    print('Loading 20 verified prior sessions...',flush=True)
    warm,evidence=seed(repo,day);results={}
    out=repo/'data/research'/('rsi-zones-body50-vs60-'+now.strftime('%Y%m%dT%H%M%S%f'))
    for minimum,Engine in engines.items():
        engine=Engine(str(day),warm)
        for bar in eligible:engine.advance(bar,references)
        result=engine.result();results[str(minimum)]=result
        print('\n'+'='*70+'\nBODY MINIMUM: '+str(minimum)+'%')
        print('LAST DECISION:',result['audit'][-1]['decision_time']);print_result(result)
        write_report(out/('body'+str(minimum)),dict(configuration='RSI EXIT + EMA ZONES | EVERY ENTRY BODY >= '+str(minimum)+'%',as_of=now.isoformat(),body_minimum_pct=minimum,warmup=evidence,result=result))
    baseline,candidate=results['50'],results['60'];comparison=[]
    print('\nORIGINAL BODY50 ENTRIES: BODY60 DECISION AT THE SAME TIME')
    print('Side | Entry | Original net | Body % | BODY60 status | Blockers')
    for t in baseline['trades']+([baseline['active_trade']] if baseline['active_trade'] else []):
        a=next(a for a in candidate['audit'] if a['decision_time']==t['entry_time']);ev=a['entry_evaluation'][t['side']]
        accepted=any(e['event']=='ENTRY' and e['side']==t['side'] for e in a['events'])
        row=dict(side=t['side'],entry=t['entry_time'],original_net=t.get('points'),body_pct=ev['moderate_entry_strength']['body_pct'],body60_status='ENTRY ACCEPTED' if accepted else ev['status'],body60_blockers=ev['blockers'])
        comparison.append(row);points=f"{t['points']:+.2f}" if 'points' in t else 'OPEN'
        print(t['side'],'|',t['entry_time'][11:16],'|',points,'|',f"{row['body_pct']:.2f}",'|',row['body60_status'],'|','; '.join(ev['blockers']) or 'NONE')
    print('\nCLOSED NET CHANGE:',f"{candidate['summary']['net_points']-baseline['summary']['net_points']:+.2f}")
    losses=lambda r:-sum(min(0,t['points']) for t in r['trades'])
    print('GROSS CLOSED LOSS REDUCTION:',f"{losses(baseline)-losses(candidate):+.2f}")
    print('CLOSED GIVEBACK REDUCTION:',f"{baseline['summary']['giveback_points']-candidate['summary']['giveback_points']:+.2f}")
    (out/'comparison.json').write_text(json.dumps(dict(as_of=now.isoformat(),warmup=evidence,results=results,original_entry_comparison=comparison),indent=2,allow_nan=False))
    esc=lambda x:html.escape(str(x))
    table='<table><tr><th>Body minimum</th><th>Closed trades</th><th>Wins</th><th>Losses</th><th>Closed net</th><th>Peak sum</th><th>Giveback</th><th>Open side</th><th>Open points</th><th>Full audit</th></tr>'
    for n,r in results.items():
        sm=r['summary'];om=r.get('open_metrics') or {}
        vals=[n+'%',sm['trades'],sm['winners'],sm['losers'],round(sm['net_points'],2),round(sm['peak_positive_points'],2),round(sm['giveback_points'],2),r['owner'] or 'NONE',round(om['unrealized_points'],2) if om else '—']
        table+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in vals)+'<td><a href="body'+n+'/audit.html">Entries, exits and all checks</a></td></tr>'
    table+='</table>'
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Body50 vs Body60</title><style>body{font:16px system-ui;padding:24px}table{border-collapse:collapse}td,th{border:1px solid #999;padding:10px}a{color:#08726e}</style><h1>RSI exit + EMA zones: entry body50 vs60</h1><p>'+esc(now.isoformat())+' · Same fresh data and 20-session warmup. Only minimum body changes; exits/RSI/routes/zones/wicks are identical. Research NIFTY points; fees/slippage excluded. Open trades are shown separately.</p>'+table+'<p>Original entry outcomes are reference context, not guaranteed savings. Later entries and ownership can change.</p>')
    import zipfile
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in out.rglob('*'):
            if f.is_file():z.write(f,str(Path(out.name)/f.relative_to(out)))
    print('\nHTML:',out/'index.html');print('UPLOAD ZIP:',archive)
    print('Research only. Live body threshold remains unchanged at50%; no services, controls or orders changed.')
if __name__=='__main__':main()
