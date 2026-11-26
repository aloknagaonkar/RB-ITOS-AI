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

class ZoneFollowupGate:
    def __init__(self,evaluator):
        self.evaluator=evaluator;self.pending={};self.owner=None
    def evaluate(self,frame,side):
        from copy import deepcopy
        ev=self.evaluator(frame,side)
        intervals=[dict(name=name,lower=min(frame[a],frame[b]),upper=max(frame[a],frame[b])) for name,a,b in (
            ('EMA10_HIGH_EMA30_LOW','ema10_high','ema30_low'),('EMA10_LOW_EMA30_HIGH','ema10_low','ema30_high'))]
        touched=[z['name'] for z in intervals if frame['low']<=z['upper'] and frame['high']>=z['lower']]
        old=self.pending.pop(side,None)
        info=dict(ev.get('confirmation_audit') or {},phase='ENTRY_RULES_WAIT',touched_zones=touched,zone_boundaries=intervals)
        ev['confirmation_audit']=info
        if self.owner==side:
            info['phase']='ACTIVE_POSITION';return ev
        reason=None
        if old:
            setup=old['frame'];bull=side=='CE'
            gates=dict(next_completed_candle=datetime.fromisoformat(frame['start'])==datetime.fromisoformat(setup['start'])+timedelta(minutes=3),
                directional_setup_breakout=frame['close']>setup['high'] if bull else frame['close']<setup['low'],
                current_entry_rules_passed=ev['selected_route'] is not None,
                outside_both_zones=not bool(info.get('zones')))
            info.update(phase='FOLLOWUP_CONFIRMED' if all(gates.values()) else 'FOLLOWUP_FAILED_CANCELLED',setup_time=setup['start'],setup_frame=deepcopy(setup),setup_zone_boundaries=old['zones'],followup_checks=gates)
            if all(gates.values()):
                ev['original_setup_frame']=deepcopy(setup)
                for route in ev['route_checks']:ev['route_checks'][route]['zone_followup_confirmation_passed']=True
                return ev
            reason='FOLLOWUP_FAILED_CANCELLED'
        elif ev['selected_route'] is not None and touched:
            self.pending[side]=dict(frame=deepcopy(frame),zones=intervals)
            info.update(phase='WAIT_NEXT_COMPLETED_3M',setup_time=frame['start'])
            reason='WAIT_NEXT_COMPLETED_3M_ZONE_FOLLOWUP'
        elif ev['selected_route'] is not None:
            info['phase']='DIRECT_OUTSIDE_ZONES';return ev
        else:return ev
        ev['route_before_followup']=ev['selected_route'];ev['selected_route']=None;ev['blockers'].append(reason)
        for name,gates in ev['route_checks'].items():
            gates['zone_followup_confirmation_passed']=False;ev['eligible_routes'][name]=False;ev['route_blockers'][name].append(reason)
        return ev

def confirmation_engine(Base,day,warm):
    original=sys.modules[Base.__module__]
    gate=ZoneFollowupGate(original.evaluate_entry)
    # A separate globals dictionary keeps the baseline engine unchanged.
    ns=dict(__name__=Base.__module__+'_followup',__package__=original.__package__)
    exec(compile(Path(original.__file__).read_text(),'<zone-followup-engine>','exec'),ns)
    ns['evaluate_entry']=gate.evaluate;ns['VERSION']=original.VERSION+'-zone-touch-followup'
    return ns['Engine'](str(day),warm),gate

def advance_confirmed(engine,gate,bar,references):
    from copy import deepcopy
    gate.owner=engine.active['side'] if engine.active else None
    audit=engine.advance(bar,references)
    for event in audit['events']:
        if event['event']!='ENTRY':continue
        ev=audit['entry_evaluation'][event['side']];setup=ev.get('original_setup_frame')
        if setup:
            active=engine.active;active['confirmation_frame']=deepcopy(active['entry_frame']);active['entry_frame']=deepcopy(setup)
            active['entry_candle_start']=setup['start'];active['original_setup_time']=setup['start']
            span=setup['high']-setup['low'];o,h,l,c=(setup[k] for k in ('open','high','low','close'))
            active['entry_candle_strength']=dict(valid=span>0,body_pct=100*abs(c-o)/span,upper_wick_pct=100*(h-max(o,c))/span,lower_wick_pct=100*(min(o,c)-l)/span)
            event['original_setup_time']=setup['start']
        gate.pending.clear()
    return audit

def main():
    repo=Path.cwd();sys.path.insert(0,str(repo/'backend'))
    from dotenv import load_dotenv
    load_dotenv(repo/'.env')
    from market_lab.domain import IST
    from market_lab.hilega_rsi_two_route_v1.data import seed,aggregate
    from market_lab.hilega_rsi_two_route_v1.live import normalize_prefix
    from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
    now=datetime.now(IST);day=now.date()
    Base=load_engine(repo,60)
    print('DATE:',day,'| BODY60 baseline vs BODY60 + ANY-ZONE TOUCH FOLLOW-UP',flush=True)
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
    out=repo/'data/research'/('rsi-body60-zone-followup-'+now.strftime('%Y%m%dT%H%M%S%f'))
    labels={'BASE60':'BODY60 — current entry handling','FOLLOWUP60':'BODY60 + zone-touch next-candle confirmation'}
    for variant in ('BASE60','FOLLOWUP60'):
        engine,gate=(Base(str(day),warm),None) if variant=='BASE60' else confirmation_engine(Base,day,warm)
        for bar in eligible:
            if gate is None:engine.advance(bar,references)
            else:advance_confirmed(engine,gate,bar,references)
        result=engine.result();results[variant]=result
        print('\n'+'='*70+'\nCONFIGURATION: '+labels[variant])
        print('LAST DECISION:',result['audit'][-1]['decision_time']);print_result(result)
        write_report(out/variant,dict(configuration=labels[variant],as_of=now.isoformat(),body_minimum_pct=60,warmup=evidence,result=result))
    baseline,candidate=results['BASE60'],results['FOLLOWUP60'];comparison=[]
    print('\nBASELINE BODY60 ENTRIES: FOLLOW-UP VARIANT AT THE SAME TIME')
    print('Side | Entry | Original net | Body % | Follow-up status | Blockers')
    for t in baseline['trades']+([baseline['active_trade']] if baseline['active_trade'] else []):
        a=next(a for a in candidate['audit'] if a['decision_time']==t['entry_time']);ev=a['entry_evaluation'][t['side']]
        accepted=any(e['event']=='ENTRY' and e['side']==t['side'] for e in a['events'])
        row=dict(side=t['side'],entry=t['entry_time'],original_net=t.get('points'),body_pct=ev['moderate_entry_strength']['body_pct'],followup_status='ENTRY ACCEPTED' if accepted else ev['status'],followup_blockers=ev['blockers'])
        comparison.append(row);points=f"{t['points']:+.2f}" if 'points' in t else 'OPEN'
        print(t['side'],'|',t['entry_time'][11:16],'|',points,'|',f"{row['body_pct']:.2f}",'|',row['followup_status'],'|','; '.join(ev['blockers']) or 'NONE')
    print('\nCLOSED NET CHANGE:',f"{candidate['summary']['net_points']-baseline['summary']['net_points']:+.2f}")
    losses=lambda r:-sum(min(0,t['points']) for t in r['trades'])
    print('GROSS CLOSED LOSS REDUCTION:',f"{losses(baseline)-losses(candidate):+.2f}")
    print('CLOSED GIVEBACK REDUCTION:',f"{baseline['summary']['giveback_points']-candidate['summary']['giveback_points']:+.2f}")
    (out/'comparison.json').write_text(json.dumps(dict(as_of=now.isoformat(),warmup=evidence,results=results,original_entry_comparison=comparison),indent=2,allow_nan=False))
    esc=lambda x:html.escape(str(x))
    table='<table><tr><th>Configuration</th><th>Closed trades</th><th>Wins</th><th>Losses</th><th>Closed net</th><th>Peak sum</th><th>Giveback</th><th>Open side</th><th>Open points</th><th>Full audit</th></tr>'
    for n,r in results.items():
        sm=r['summary'];om=r.get('open_metrics') or {}
        vals=[labels[n],sm['trades'],sm['winners'],sm['losers'],round(sm['net_points'],2),round(sm['peak_positive_points'],2),round(sm['giveback_points'],2),r['owner'] or 'NONE',round(om['unrealized_points'],2) if om else '—']
        table+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in vals)+'<td><a href="'+n+'/audit.html">Entries, exits and all checks</a></td></tr>'
    table+='</table>'
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Body60 zone-touch follow-up</title><style>body{font:16px system-ui;padding:24px}table{border-collapse:collapse}td,th{border:1px solid #999;padding:10px}a{color:#08726e}</style><h1>RSI exit + EMA zones: body60 baseline vs zone-touch follow-up</h1><p>'+esc(now.isoformat())+' · Same fresh data and 20-session warmup. Both use body >=60%. Only zone-touch follow-up confirmation changes. Setup wick/body overlap with either zone triggers the next-candle wait; confirmed close must break setup high/low and pass all entry rules. Original setup midpoint retained. No 80% crossing rule is added. Research NIFTY points; fees/slippage excluded. Open trades are shown separately.</p>'+table+'<p>Original entry outcomes are reference context, not guaranteed savings. Later entries and ownership can change.</p>')
    import zipfile
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in out.rglob('*'):
            if f.is_file():z.write(f,str(Path(out.name)/f.relative_to(out)))
    print('\nHTML:',out/'index.html');print('UPLOAD ZIP:',archive)
    print('Research only. Live remains BODY50 with no follow-up; no services, controls or orders changed.')
if __name__=='__main__':main()
