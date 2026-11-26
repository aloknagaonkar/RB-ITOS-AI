#!/usr/bin/env python3
"""Research only: current combined baseline vs strict/moderate zone confirmation.
No installed-code edits, journal writes, services, execution controls or orders.
"""
import argparse
import copy
import hashlib
import html
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

MODES = {
    'BASELINE_RSI_EXIT_EMA_ZONES': None,
    'STRICT_SETUP70_FOLLOWUP70': (70, 70, 15, True),
    'MODERATE_SETUP50_FOLLOWUP60': (50, 60, 20, False),
}

def zone_blocks(f):
    return [name for name, a, b in (
        ('EMA10_HIGH_EMA30_LOW', f['ema10_high'], f['ema30_low']),
        ('EMA10_LOW_EMA30_HIGH', f['ema10_low'], f['ema30_high']))
        if min(a, b) <= f['close'] <= max(a, b)]

def touches(f, side):
    a, b = ((f['ema10_low'], f['ema30_high']) if side == 'CE'
            else (f['ema10_high'], f['ema30_low']))
    return f['low'] <= max(a, b) and f['high'] >= min(a, b)

def shape(f):
    o, h, l, c = (f[k] for k in ('open', 'high', 'low', 'close'))
    if h <= l or not l <= min(o, c) <= max(o, c) <= h:
        return dict(valid=False, body=0., upper=100., lower=100.)
    return dict(valid=True, body=100*abs(c-o)/(h-l),
                upper=100*(h-max(o,c))/(h-l), lower=100*(min(o,c)-l)/(h-l))

def strong(f, side, body_min, wick_max, both):
    s = shape(f)
    colour = f['close'] > f['open'] if side == 'CE' else f['close'] < f['open']
    adverse = s['upper'] if side == 'CE' else s['lower']
    wick = max(s['upper'],s['lower']) if both else adverse
    return bool(s['valid'] and colour and s['body']+1e-9 >= body_min and wick <= wick_max+1e-9)

class Gate:
    def __init__(self, evaluator, config):
        self.evaluator=evaluator; self.config=config; self.pending={}; self.owner=None

    def evaluate(self, f, side):
        ev=self.evaluator(f,side)
        route=ev['selected_route']; blocked=zone_blocks(f)
        old=self.pending.pop(side,None)
        info=dict(zones=blocked, touched=touches(f,side), candle=shape(f),
                  original_route=route, setup_time=None, phase='BASELINE')
        ev['confirmation_audit']=info
        reasons=[]
        if self.config is None:
            if blocked: reasons=['NO_NEW_ENTRY_ZONE']
        elif self.owner==side:
            reasons=['ACTIVE_SAME_SIDE_NO_FRESH_SETUP']; info['phase']='ACTIVE'
        else:
            setup_min,follow_min,wick,both=self.config
            if old is not None:
                info.update(phase='FOLLOWUP',setup_time=old['start'],setup_frame=old)
                sequential=datetime.fromisoformat(f['start']) == datetime.fromisoformat(old['start'])+timedelta(minutes=3)
                breakout=f['close']>old['high'] if side=='CE' else f['close']<old['low']
                a,b=((f['ema10_low'],f['ema30_high']) if side=='CE'
                     else (f['ema10_high'],f['ema30_low']))
                beyond=f['close']>max(a,b) if side=='CE' else f['close']<min(a,b)
                checks=dict(next_candle=sequential, strong=strong(f,side,follow_min,wick,both),
                            setup_breakout=breakout, beyond_relevant_zone=beyond,
                            outside_both_zones=not blocked, existing_route_passed=route is not None)
                info['followup_checks']=checks
                reasons=['FOLLOWUP_'+k.upper()+'_FAILED' for k,v in checks.items() if not v]
                if not reasons:
                    ev['original_setup_frame']=copy.deepcopy(old)
                    info['phase']='FOLLOWUP_CONFIRMED'
                else: info['phase']='FOLLOWUP_FAILED_CANCELLED'
                # A failed follow-up does not re-arm itself on the same candle.
            elif info['touched']:
                info['phase']='SETUP_CHECK'
                price_key='close_vs_ema30_high' if side=='CE' else 'close_vs_ema30_low'
                # A setup can still be in the zone; postpone only its price gate.
                # All its original RSI/route, colour and readiness checks must pass.
                setup_route=next((name for name,gates in ev['route_checks'].items()
                                  if all(v is True for k,v in gates.items() if k!=price_key)),None)
                checks=dict(strong=strong(f,side,setup_min,wick,both),
                            setup_rsi_route_passed=setup_route is not None)
                info.update(setup_checks=checks,setup_route=setup_route)
                if all(checks.values()):
                    self.pending[side]=copy.deepcopy(f)
                    info['phase']='WAIT_NEXT_CANDLE'; info['setup_time']=f['start']
                    reasons=['WAIT_STRONG_FOLLOWUP']
                else:
                    reasons=['SETUP_'+k.upper()+'_FAILED' for k,v in checks.items() if not v]
            else:
                # Entire candle must be beyond the relevant zone to enter directly.
                a,b=((f['ema10_low'],f['ema30_high']) if side=='CE'
                     else (f['ema10_high'],f['ema30_low']))
                beyond=f['low']>max(a,b) if side=='CE' else f['high']<min(a,b)
                info['phase']='DIRECT_OUTSIDE_ZONE'
                if not beyond: reasons.append('NOT_BEYOND_RELEVANT_ZONE')
                if blocked: reasons.append('NO_NEW_ENTRY_ZONE')
        info['gate_blockers']=reasons
        if reasons:
            ev['selected_route']=None
            ev['blockers']=list(ev['blockers'])+reasons
            for name,gates in ev['route_checks'].items():
                gates['zone_confirmation_gate']=False
                ev['eligible_routes'][name]=False
                ev['route_blockers'][name].append('zone_confirmation_gate')
        return ev

def load_engine(original):
    text=Path(original.__file__).read_text()
    changes=[
      ("if active and (closing or reversal or midpoint_exit or exits['all_three_exit']):",
       "if active and (closing or reversal or midpoint_exit or exits['all_three_exit'] or exits['momentum_exit']):"),
      ("else ['ALL_THREE_MOMENTUM_WMA_PRICE']",
       "else ['ALL_THREE_MOMENTUM_WMA_PRICE'] if exits['all_three_exit'] else ['RSI5_RSI9_MOMENTUM']"),
      ("if midpoint_exit:midpoint_closed_side=active['side']",
       "if midpoint_exit or exits['momentum_exit']:midpoint_closed_side=active['side']")]
    for before,after in changes:
        if text.count(before)!=1: raise ValueError('ENGINE_VERSION_MISMATCH_NO_CHANGES')
        text=text.replace(before,after,1)
    compile(text,'<research-engine>','exec')
    return text

def make_engine(original,text,day,warm,config):
    class Indicators(original.Indicators):
        def __init__(self): super().__init__();self.h10=self.l10=None
        def update(self,bar):
            f=super().update(bar);a=2/11
            self.h10=float(bar['high']) if self.h10 is None else a*bar['high']+(1-a)*self.h10
            self.l10=float(bar['low']) if self.l10 is None else a*bar['low']+(1-a)*self.l10
            return dict(f,ema10_high=self.h10,ema10_low=self.l10)
    gate=Gate(original.evaluate_entry,config)
    ns=dict(__name__=original.__package__+'.strength_research',__package__=original.__package__)
    exec(compile(text,'<research-engine>','exec'),ns)
    ns.update(Indicators=Indicators,evaluate_entry=gate.evaluate)
    return ns['Engine'](str(day),warm),gate

def advance(engine,gate,bar,minutes):
    gate.owner=engine.active['side'] if engine.active else None
    audit=engine.advance(bar,minutes)
    for event in audit['events']:
        if event['event']=='ENTRY':
            side=event['side'];ev=audit['entry_evaluation'][side]
            active=engine.active
            if ev.get('original_setup_frame'):
                setup=copy.deepcopy(ev['original_setup_frame'])
                active['confirmation_frame']=copy.deepcopy(active['entry_frame'])
                active['entry_frame']=setup
                active['entry_candle_start']=setup['start']
                active['original_setup_time']=setup['start']
                active['entry_candle_strength']=original_strength(setup)
                event['original_setup_time']=setup['start']
            gate.pending.clear()
    return audit

def original_strength(f):
    s=shape(f)
    return dict(valid=s['valid'],body_pct=s['body'],upper_wick_pct=s['upper'],lower_wick_pct=s['lower'])

def self_test():
    def evaluator(f,side):
        bull=side=='CE';price=f['close']>f['ema30_high'] if bull else f['close']<f['ema30_low']
        colour=f['close']>f['open'] if bull else f['close']<f['open']
        key='close_vs_ema30_high' if bull else 'close_vs_ema30_low'
        gates={key:price,'signal_candle_colour':colour,'indicators_ready':True,'rsi_pass':True}
        return dict(selected_route='Normal Route' if all(gates.values()) else None,
                    route_checks={'Normal Route':gates},eligible_routes={'Normal Route':all(gates.values())},
                    route_blockers={'Normal Route':[]},blockers=[])
    def frame(o,h,l,c,start='2026-11-25T09:15:00+05:30'):
        return dict(open=o,high=h,low=l,close=c,start=start,ema10_low=100,ema30_high=102,ema10_high=104,ema30_low=98)
    for side in ('CE','PE'):
        setup=frame(99,104,98,103) if side=='CE' else frame(103,104,98,99)
        follow=frame(103,110,103,109,'2026-11-25T09:18:00+05:30') if side=='CE' else frame(99,99,92,93,'2026-11-25T09:18:00+05:30')
        g=Gate(evaluator,MODES['MODERATE_SETUP50_FOLLOWUP60'])
        a=g.evaluate(setup,side);assert a['selected_route'] is None and side in g.pending
        b=g.evaluate(follow,side);assert b['selected_route']=='Normal Route' and b['original_setup_frame']==setup
        g=Gate(evaluator,MODES['MODERATE_SETUP50_FOLLOWUP60']);g.evaluate(setup,side)
        weak=frame(103,110,100,104,'2026-11-25T09:18:00+05:30') if side=='CE' else frame(99,102,92,98,'2026-11-25T09:18:00+05:30')
        assert g.evaluate(weak,side)['selected_route'] is None and side not in g.pending
    f=frame(100,110,90,110);assert strong(f,'CE',50,20,False) and not strong(f,'CE',70,15,True)
    f=frame(100,110,90,90);assert strong(f,'PE',50,20,False) and not strong(f,'CE',50,20,False)
    for p,want in [(98,True),(104,True),(105,False),(97,False)]:
        assert bool(zone_blocks(frame(p,p+1,p-1,p)))==want
    print('PASS: CE/PE setup-to-followup, failed-followup cancellation, original setup preservation, strength thresholds and inclusive zones.')

def report(output,results,metadata):
    output.mkdir(parents=True,exist_ok=False)
    payload=dict(metadata=metadata,results=results)
    (output/'comparison.json').write_text(json.dumps(payload,indent=2,allow_nan=False))
    # Static, offline HTML: all tables work even when JavaScript is disabled.
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Zone strength comparison</title><style>body{background:#10232d;color:#e3edf2;font:15px/1.5 system-ui;margin:24px}h1,h2{color:#8de4c0}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #3d5361;padding:10px;text-align:left;vertical-align:top}th{background:#203844}.scroll{overflow:auto}.positive{color:#8de4c0}.negative{color:#ff9c9c}details{margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#a8bdca}button{padding:8px;background:#203844;color:white;border:1px solid #678} @media print{body{background:white;color:black}.scroll{overflow:visible}button{display:none}}</style><h1>Zone-touch strength & follow-up comparison</h1>',
      '<p>'+html.escape(metadata['day'])+' · NIFTY points · Full day · Completed 3m · Research only</p>',
      '<p>Baseline: RSI5/RSI9 exit + both EMA no-entry zones. Strict: setup and follow-up body ≥70%, each wick ≤15%. Moderate: setup body ≥50%, follow-up body ≥60%, adverse wick ≤20% (CE upper / PE lower).</p>',
      '<p>Setup range overlaps its relevant zone; setup RSI/route, colour and readiness must pass, with the EMA30 price gate postponed until confirmation. Only the next completed candle can confirm: close beyond setup high/low and relevant zone, outside both zones, current entry rules pass. Failed follow-up is cancelled and cannot re-arm on that same candle. Candles entirely beyond the relevant zone use direct entries. Original setup midpoint retained; all existing exits plus RSI exit retained.</p>',
      '<p>Zone boundaries are calculated on each completed candle. Touch/overlap includes wicks and equality. Both zones block new entries in either direction. Existing positions continue; only qualifying opposite entries can reverse. Fees/slippage excluded. No live changes.</p>',
      '<button onclick="window.print()">Print / Save PDF</button><h2>Summary</h2><div class="scroll"><table><tr><th>Variant</th><th>Trades</th><th>Winners</th><th>Losers</th><th>Net</th><th>Peak sum</th><th>Giveback</th><th>Gross loss</th></tr>']
    for name,r in results.items():
        s=r['summary'];loss=-sum(min(0,t['points']) for t in r['trades'])
        parts.append('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in [name,s['trades'],s['winners'],s['losers'],round(s['net_points'],2),round(s['peak_positive_points'],2),round(s['giveback_points'],2),round(loss,2)])+'</tr>')
    parts.append('</table></div>')
    for name,r in results.items():
        parts.append('<h2>'+name+'</h2><div class="scroll"><table><tr><th>Side / route</th><th>Setup</th><th>Entry</th><th>Exit</th><th>Entry NIFTY</th><th>Exit NIFTY</th><th>Net</th><th>Peak +</th><th>Giveback</th><th>Reason</th></tr>')
        for t in r['trades']:
            vals=[t['side']+' / '+t['route_name'],t['entry_candle_start'][11:16],t['entry_time'][11:16],t['exit_time'][11:16],f"{t['entry_price']:.2f}",f"{t['exit_price']:.2f}",f"{t['points']:+.2f}",f"{t['peak_positive_points']:.2f}",f"{t['giveback_points']:.2f}",'; '.join(t['exit_reasons'])]
            parts.append('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in vals)+'</tr>')
        parts.append('</table></div><details><summary>Every 3-minute candle: both directions, indicators, confirmation and exit checks</summary>')
        for a in r['audit']:
            label=a['decision_time'][11:16]+' | owner '+str(a['owner_before'])+' → '+str(a['owner_after'])+' | '+', '.join(e['event']+' '+e['side'] for e in a['events'])
            parts.append('<details><summary>'+html.escape(label)+'</summary><pre>'+html.escape(json.dumps(a,indent=2))+'</pre></details>')
        parts.append('</details>')
    parts.append('<h2>Input evidence</h2><pre>'+html.escape(json.dumps(metadata,indent=2))+'</pre><small>Peak sums represent individual-trade excursions, not a simultaneous portfolio peak. Entry/exit modeled at next 1m OPEN; terminal exit at exact 15:29 CLOSE.</small></html>')
    (output/'audit.html').write_text(''.join(parts))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    parser.add_argument('--day',type=date.fromisoformat,default=date(2026,11,25))
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test: self_test();return
    repo=args.repo.resolve();os.chdir(repo);sys.path.insert(0,str(repo/'backend'))
    from dotenv import load_dotenv
    from market_lab.domain import IST
    from market_lab.hilega_rsi_two_route_v1 import engine as original
    from market_lab.hilega_rsi_two_route_v1.calendar import validate_rows
    from market_lab.hilega_rsi_two_route_v1.data import seed,bars,digest
    from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
    text=load_engine(original);self_test()
    load_dotenv(repo/'.env')
    source=UpstoxLiveShadowSourcesV1(os.environ.get('UPSTOX_ACCESS_TOKEN',''))
    try:
        items=(source.nifty_intraday_1m() if datetime.now(IST).date()==args.day
               else source.historical_candles('NSE_INDEX|Nifty 50',args.day))
    finally: source.close()
    rows=[dict(timestamp=c.timestamp.astimezone(IST).isoformat(),open=float(c.open),high=float(c.high),low=float(c.low),close=float(c.close),volume=getattr(c,'volume',None)) for c in sorted(items,key=lambda c:c.timestamp)]
    print('Fetched candles:',len(rows),flush=True)
    rows=validate_rows(rows,args.day)
    print('Loading 20 verified prior sessions...',flush=True)
    warm,evidence=seed(repo,args.day)
    results={}
    for name,config in MODES.items():
        engine,gate=make_engine(original,text,args.day,warm,config)
        for b in bars(rows,args.day):advance(engine,gate,b,rows)
        if engine.active: raise ValueError('SESSION_EXIT_MISSING')
        result=engine.result();results[name]=result
        print('\n'+name,flush=True)
        print('Side | Route | Setup | Entry | Exit | Entry NIFTY | Exit NIFTY | Net | Peak + | Giveback | Exit reason')
        for t in result['trades']:
            print(f"{t['side']} | {t['route_name']} | {t['entry_candle_start'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['entry_price']:.2f} | {t['exit_price']:.2f} | {t['points']:+.2f} | {t['peak_positive_points']:.2f} | {t['giveback_points']:.2f} | {'; '.join(t['exit_reasons'])}")
        print('SUMMARY:',json.dumps(result['summary']),flush=True)
    # Detect baseline/input drift instead of silently comparing with old evidence.
    if args.day==date(2026,11,25):
        s=results['BASELINE_RSI_EXIT_EMA_ZONES']['summary']
        if s['trades']!=5 or abs(s['net_points']-254.45)>.011:
            print('BASELINE_DIFFERS_FROM_PRIOR_254.45: compare input evidence before attributing differences to strength.')
    output=repo/'data/research'/('zone-strength-'+datetime.now(IST).strftime('%Y%m%dT%H%M%S%f'))
    metadata=dict(day=str(args.day),minute_count=len(rows),minute_sha256=digest(rows),warmup=evidence,
                  installed_engine_sha256=hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest(),
                  runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),live_changes=False)
    report(output,results,metadata)
    (output/'inputs.json').write_text(json.dumps(dict(day=str(args.day),minutes=rows,warmup_bars=warm,warmup_evidence=evidence),allow_nan=False))
    print('\nHTML:',output/'audit.html');print('JSON:',output/'comparison.json')
    print('No live rules, services, execution controls or orders changed.')

if __name__=='__main__':main()
