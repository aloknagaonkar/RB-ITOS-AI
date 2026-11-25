#!/usr/bin/env python3
"""Research: retain EMA zones, permit zone entries after strong confirmation.
Requires the unchanged hilega-zone-strength-research-20261125.py beside this file.
"""
import argparse, copy, hashlib, html, importlib.util, json, os, sys, zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

HELPER='hilega-zone-strength-research-20261125.py'

def load_helper(path):
    spec=importlib.util.spec_from_file_location('zone_strength_helper',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

class InsideGate:
    helper=None
    def __init__(self,evaluator,config):
        self.evaluator=evaluator;self.config=config;self.pending={};self.owner=None

    def evaluate(self,f,side):
        h=self.helper;ev=self.evaluator(f,side);route=ev['selected_route']
        spans=[('EMA10_HIGH_EMA30_LOW',f['ema10_high'],f['ema30_low']),
               ('EMA10_LOW_EMA30_HIGH',f['ema10_low'],f['ema30_high'])]
        touched=[n for n,a,b in spans if f['low']<=max(a,b) and f['high']>=min(a,b)]
        zones=h.zone_blocks(f);old=self.pending.pop(side,None)
        info=dict(zones=zones,touched_zones=touched,candle=h.shape(f),
                  original_route=route,phase='DIRECT_OUTSIDE_ZONE',setup_time=None)
        ev['confirmation_audit']=info;reasons=[]
        if self.owner==side:
            reasons=['ACTIVE_SAME_SIDE_NO_FRESH_SETUP'];info['phase']='ACTIVE'
        elif self.config is None:
            raise ValueError('INSIDE_GATE_REQUIRES_STRENGTH_CONFIG')
        else:
            setup_min,follow_min,wick,both=self.config
            if old is not None:
                info.update(phase='FOLLOWUP',setup_time=old['start'],setup_frame=old)
                checks=dict(
                    next_candle=datetime.fromisoformat(f['start'])==datetime.fromisoformat(old['start'])+timedelta(minutes=3),
                    strong=h.strong(f,side,follow_min,wick,both),
                    setup_breakout=f['close']>old['high'] if side=='CE' else f['close']<old['low'],
                    existing_rsi_route_ema30_passed=route is not None)
                # Deliberately NO outside-zone or beyond-zone condition here.
                info['followup_checks']=checks
                reasons=['FOLLOWUP_'+k.upper()+'_FAILED' for k,v in checks.items() if not v]
                if not reasons:
                    ev['original_setup_frame']=copy.deepcopy(old)
                    info['phase']='FOLLOWUP_CONFIRMED_INSIDE_ZONE' if zones else 'FOLLOWUP_CONFIRMED_OUTSIDE_ZONE'
                else:info['phase']='FOLLOWUP_FAILED_CANCELLED'
            elif h.touches(f,side):
                info['phase']='SETUP_CHECK'
                price='close_vs_ema30_high' if side=='CE' else 'close_vs_ema30_low'
                setup_route=next((name for name,gates in ev['route_checks'].items()
                                  if all(v is True for k,v in gates.items() if k!=price)),None)
                checks=dict(strong=h.strong(f,side,setup_min,wick,both),setup_rsi_route_passed=setup_route is not None)
                info.update(setup_checks=checks,setup_route=setup_route)
                if all(checks.values()):
                    self.pending[side]=copy.deepcopy(f)
                    info.update(phase='WAIT_NEXT_CANDLE',setup_time=f['start'])
                    reasons=['WAIT_STRONG_FOLLOWUP']
                else:reasons=['SETUP_'+k.upper()+'_FAILED' for k,v in checks.items() if not v]
            else:
                aa,bb=((f['ema10_low'],f['ema30_high']) if side=='CE'
                       else (f['ema10_high'],f['ema30_low']))
                beyond=f['low']>max(aa,bb) if side=='CE' else f['high']<min(aa,bb)
                if not beyond:reasons.append('NOT_BEYOND_RELEVANT_ZONE')
                if zones:reasons.append('NO_NEW_ENTRY_ZONE')
            # Direct path matches the prior runner; only confirmed follow-ups may enter zones.
        info['gate_blockers']=reasons
        if reasons:
            ev['selected_route']=None;ev['blockers']=list(ev['blockers'])+reasons
            for name,gates in ev['route_checks'].items():
                gates['zone_strength_confirmation']=False
                ev['eligible_routes'][name]=False
                ev['route_blockers'][name].append('zone_strength_confirmation')
        return ev

def self_test(h):
    def evaluate(f,side):
        key='close_vs_ema30_high' if side=='CE' else 'close_vs_ema30_low'
        price=f['close']>f['ema30_high'] if side=='CE' else f['close']<f['ema30_low']
        colour=f['close']>f['open'] if side=='CE' else f['close']<f['open']
        checks={key:price,'colour':colour,'rsi':True,'ready':True}
        return dict(selected_route='Normal Route' if all(checks.values()) else None,
                    route_checks={'Normal Route':checks},eligible_routes={'Normal Route':all(checks.values())},
                    route_blockers={'Normal Route':[]},blockers=[])
    def frame(o,high,low,c,minute):
        return dict(open=o,high=high,low=low,close=c,start=f'2026-11-25T09:{minute:02d}:00+05:30',
                    ema10_high=120,ema10_low=100,ema30_high=102,ema30_low=98)
    a=frame(100.5,105,100,104.5,15);b=frame(104.5,110,104.5,109.5,18)
    def mirror(f):
        out=dict(f,open=220-f['open'],high=220-f['low'],low=220-f['high'],close=220-f['close'])
        out.update(ema10_high=220-f['ema10_low'],ema10_low=220-f['ema10_high'],
                   ema30_high=220-f['ema30_low'],ema30_low=220-f['ema30_high'])
        return out
    for side,s,f in [('CE',a,b),('PE',mirror(a),mirror(b))]:
        for config in [h.MODES['STRICT_SETUP70_FOLLOWUP70'],h.MODES['MODERATE_SETUP50_FOLLOWUP60']]:
            gate=InsideGate(evaluate,config)
            assert gate.evaluate(s,side)['selected_route'] is None
            ev=gate.evaluate(f,side)
            assert h.zone_blocks(f) and ev['selected_route']=='Normal Route'
            assert ev['original_setup_frame']==s
            assert ev['confirmation_audit']['phase']=='FOLLOWUP_CONFIRMED_INSIDE_ZONE'
            # A price-rule failure must still reject a strong follow-up.
            bad=dict(f,ema30_high=200) if side=='CE' else dict(f,ema30_low=1)
            gate=InsideGate(evaluate,config);gate.evaluate(s,side)
            assert gate.evaluate(bad,side)['selected_route'] is None
    # Regression: touching only the other zone must not start a new waiting state.
    other=frame(105,110,105,109,15)
    for side,f in [('CE',other),('PE',mirror(other))]:
        config=h.MODES['STRICT_SETUP70_FOLLOWUP70']
        prior=h.Gate(evaluate,config);new=InsideGate(evaluate,config)
        x=prior.evaluate(f,side);y=new.evaluate(f,side)
        assert x['selected_route']==y['selected_route']
        assert prior.pending==new.pending=={}
        assert y['confirmation_audit']['phase']=='DIRECT_OUTSIDE_ZONE'
    h.self_test()
    print('PASS: strict/moderate CE/PE can confirm INSIDE a zone; original EMA30 price gate still enforced.')

def make_html(out,results,metadata):
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Strong entries inside EMA zones</title><style>body{background:#122530;color:#e3edf2;font:15px/1.5 system-ui;margin:24px}h1,h2{color:#8de4c0}table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:10px;border-bottom:1px solid #49606c;text-align:left}th{background:#213b49}.scroll{overflow:auto}summary{cursor:pointer}details{margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#afc1cc}@media print{body{background:white;color:black}h1,h2{color:black}}</style><h1>Strong setup + follow-up: entries inside EMA zones</h1>',
      '<p>'+str(metadata['day'])+' · Completed 3m · Full-day NIFTY research · No live changes</p>',
      '<p>All variants retain the RSI5/RSI9 exit. Prior variants block entries inside either EMA zone. New variants retain and monitor both zones: when the setup range touches its directional zone (CE EMA10 Low / EMA30 High; PE EMA10 High / EMA30 Low), require a strong setup and next-candle strong follow-up, but permit the follow-up close inside a zone. Original EMA30 close, RSI and route requirements still apply at entry; follow-up must close beyond the original setup high for CE / low for PE. Only confirmed follow-ups waive the requirement to clear EMA10 and both zones; direct-entry gates remain identical to the prior runner.</p>',
      '<p>Strict: both bodies ≥70%, each wick ≤15%. Moderate: setup body ≥50%, follow-up ≥60%, adverse wick ≤20% (upper for CE, lower for PE). Candles entirely beyond their directional zone retain direct entry, subject to both existing no-entry zones for the prior variants; the new variants waive that zone blocking only through confirmation. Setup RSI/route and colour must pass; its EMA30 price check is postponed until follow-up. Failed follow-up cancels; cannot re-arm on that same candle. Existing open trades retain their exits, with the original setup midpoint fixed.</p>',
      '<p>Input: 375 verified target minutes and the same 20 prior sessions. Entries/exits modeled at next 1m open; session exit at exact 15:29 close. Fees/slippage excluded. NIFTY points are not option profit or executed-trade P&amp;L.</p><h2>Comparison</h2><div class="scroll"><table><tr><th>Variant</th><th>Trades</th><th>Winners</th><th>Losers</th><th>Net</th><th>Peak sum</th><th>Giveback</th><th>Confirmed zone entries</th></tr>']
    for name,r in results.items():
        s=r['summary'];vals=[name,s['trades'],s['winners'],s['losers'],f"{s['net_points']:+.2f}",f"{s['peak_positive_points']:.2f}",f"{s['giveback_points']:.2f}",s['confirmed_entries_inside_zones']]
        parts.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in vals)+'</tr>')
    parts.append('</table></div>')
    for name,r in results.items():
        parts.append('<h2>'+name+'</h2><div class="scroll"><table><tr><th>Side / route</th><th>Setup</th><th>Entry</th><th>Exit</th><th>Entry NIFTY</th><th>Exit NIFTY</th><th>Net</th><th>Peak +</th><th>Giveback</th><th>Entry path</th><th>Exit reason</th></tr>')
        for t in r['trades']:
            phase=(t['entry_evaluation'].get('confirmation_audit') or {}).get('phase','BASELINE')
            vals=[t['side']+' / '+t['route_name'],t['entry_candle_start'][11:16],t['entry_time'][11:16],t['exit_time'][11:16],f"{t['entry_price']:.2f}",f"{t['exit_price']:.2f}",f"{t['points']:+.2f}",f"{t['peak_positive_points']:.2f}",f"{t['giveback_points']:.2f}",phase,'; '.join(t['exit_reasons'])]
            parts.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in vals)+'</tr>')
        parts.append('</table></div><details><summary>Every 3-minute audit · both directions</summary>')
        for a in r['audit']:
            parts.append('<details><summary>'+html.escape(a['decision_time'][11:16]+' · '+str(a['owner_before'])+' → '+str(a['owner_after']))+'</summary><pre>'+html.escape(json.dumps(a,indent=2))+'</pre></details>')
        parts.append('</details>')
    parts.append('<h2>Evidence</h2><pre>'+html.escape(json.dumps(metadata,indent=2))+'</pre><small>Summed individual peaks are not a simultaneous portfolio peak. Research only.</small></html>')
    (out/'audit.html').write_text(''.join(parts))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--day',type=date.fromisoformat,default=date(2026,11,25))
    p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--self-test',action='store_true');a=p.parse_args()
    helper_path=Path(__file__).resolve().parent/HELPER
    if not helper_path.is_file():raise SystemExit('MISSING_HELPER:'+str(helper_path))
    h=load_helper(helper_path);InsideGate.helper=h;self_test(h)
    if a.self_test:return
    repo=a.repo.resolve();os.chdir(repo);sys.path.insert(0,str(repo/'backend'))
    from dotenv import load_dotenv
    from market_lab.domain import IST
    from market_lab.hilega_rsi_two_route_v1 import engine as original
    from market_lab.hilega_rsi_two_route_v1.calendar import validate_rows
    from market_lab.hilega_rsi_two_route_v1.data import seed,bars,digest
    from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
    print('MATCHED TEST V2: same directional touch trigger and direct gates; only confirmed-followup zone clearance is relaxed.',flush=True)
    text=h.load_engine(original);load_dotenv(repo/'.env')
    src=UpstoxLiveShadowSourcesV1(os.environ.get('UPSTOX_ACCESS_TOKEN',''))
    try:items=src.nifty_intraday_1m() if datetime.now(IST).date()==a.day else src.historical_candles('NSE_INDEX|Nifty 50',a.day)
    finally:src.close()
    rows=[dict(timestamp=c.timestamp.astimezone(IST).isoformat(),open=float(c.open),high=float(c.high),low=float(c.low),close=float(c.close),volume=getattr(c,'volume',None)) for c in sorted(items,key=lambda c:c.timestamp)]
    print('Fetched candles:',len(rows),flush=True);rows=validate_rows(rows,a.day)
    print('Loading 20 verified prior sessions...',flush=True);warm,evidence=seed(repo,a.day)
    results={};old_gate=h.Gate
    modes=[(name,cfg,False) for name,cfg in h.MODES.items()]+[
        ('STRICT_ALLOW_ZONE_ENTRIES',h.MODES['STRICT_SETUP70_FOLLOWUP70'],True),
        ('MODERATE_ALLOW_ZONE_ENTRIES',h.MODES['MODERATE_SETUP50_FOLLOWUP60'],True)]
    for name,config,inside in modes:
        h.Gate=InsideGate if inside else old_gate
        engine,gate=h.make_engine(original,text,a.day,warm,config)
        for bar in bars(rows,a.day):h.advance(engine,gate,bar,rows)
        if engine.active:raise ValueError('SESSION_EXIT_MISSING')
        r=engine.result();s=r['summary']
        s['confirmed_entries_inside_zones']=sum((t['entry_evaluation'].get('confirmation_audit') or {}).get('phase')=='FOLLOWUP_CONFIRMED_INSIDE_ZONE' for t in r['trades'])
        results[name]=r;print('\n'+name,flush=True)
        print('Side | Route | Setup | Entry | Exit | Entry NIFTY | Exit NIFTY | Net | Peak + | Giveback | Entry path | Exit reason')
        for t in r['trades']:
            phase=(t['entry_evaluation'].get('confirmation_audit') or {}).get('phase','BASELINE')
            print(f"{t['side']} | {t['route_name']} | {t['entry_candle_start'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['entry_price']:.2f} | {t['exit_price']:.2f} | {t['points']:+.2f} | {t['peak_positive_points']:.2f} | {t['giveback_points']:.2f} | {phase} | {'; '.join(t['exit_reasons'])}")
        print('SUMMARY:',json.dumps(s),flush=True)
    h.Gate=old_gate
    meta=dict(day=str(a.day),minute_count=len(rows),minute_sha256=digest(rows),warmup=evidence,
              engine_sha256=hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest(),
              helper_sha256=hashlib.sha256(helper_path.read_bytes()).hexdigest(),runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),live_changes=False)
    out=repo/'data/research'/('zone-entry-confirmation-'+datetime.now(IST).strftime('%Y%m%dT%H%M%S%f'));out.mkdir(parents=True,exist_ok=False)
    (out/'comparison.json').write_text(json.dumps(dict(metadata=meta,results=results),indent=2,allow_nan=False))
    (out/'inputs.json').write_text(json.dumps(dict(minutes=rows,warmup_bars=warm,warmup_evidence=evidence),allow_nan=False))
    make_html(out,results,meta)
    zpath=out.with_suffix('.zip')
    with zipfile.ZipFile(zpath,'w',zipfile.ZIP_DEFLATED) as z:
        for f in out.iterdir():z.write(f,f.name)
    print('\nHTML:',out/'audit.html');print('UPLOAD ZIP:',zpath)
    print('No live rules, services, execution controls or orders changed.')

if __name__=='__main__':main()
