"""Research replay: opposite arms/setups cannot cancel pending direction.

No installation, broker operations, service control, or live state writes.
--fetch-today performs one analytics GET; otherwise all input is local.
An intraday run marks an open trade at the last completed minute, never invents
an early cutoff exit. Existing entry checks, ten-minute window and exits stay.
"""
import argparse
import copy
import csv
import hashlib
import inspect
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

IST=ZoneInfo('Asia/Kolkata')
VERSION='five-minute-setup-1.2.0-pending-switch'

RULE_CHANGES=[
 ('Opposite arm','May cancel prior pending direction and start a direction watch','Informational only; no pending cancellation or watch'),
 ('Opposite accepted setup','Replaces prior pending before entry confirmation','Keeps its own confirmation context alongside prior pending'),
 ('Direction replacement','Can happen before full entry confirmation','Only fully confirmed entry wins; remaining pending contexts cleared'),
 ('Alternative setup direction restriction','Direction watch can suppress opposite setup','No arm/setup direction watch; other setup conditions retained'),
 ('Same-direction setup repeats','Existing caller eligibility behavior','Existing caller eligibility behavior; no new repeated-setup route'),
 ('Setup boundaries','Completed five-minute boundaries','Unchanged'),
 ('Confirmation checks','Every minute; strength >=0.75, persistence, positive expanding gap','Unchanged'),
 ('Pending lifetime','Original ten-minute confirmation window','Unchanged; expired contexts are not resurrected'),
 ('Canonical exit/reset cancellation','Existing behavior','Unchanged'),
 ('Active position exits','Existing dual-exit rules; 14:55 cutoff','Unchanged'),
 ('Setup audit','Does not record every alternative setup rejection','Research logs each prerequisite and observed values'),
]

def dt(value):
    at=datetime.fromisoformat(value)
    if at.utcoffset() is None:raise ValueError('TIMEZONE_REQUIRED')
    return at.astimezone(IST)

def changed_gate(Base):
    class ConfirmedOnly(Base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.policy_events=[]
        def observe_arms(self,events,available):
            # Preserve parent calls and the canonical engine; change no position.
            arms={'PATH1_ARMED_RSI_CROSS_EMA3_UP':'BULLISH','BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN':'BEARISH'}
            for event in events:
                if event.event_type in arms:
                    self.policy_events.append(dict(time=available.isoformat(),event='ARM_INFORMATION_ONLY',direction=arms[event.event_type],pending_directions=list(self.pending)))
        def can_signal(self,side,available):
            return True
        def signal(self,event,available):
            if self.owner!='NONE' or self.locked:return
            # Base signal() is retained, but its eager _switch is insulated.
            super().signal(event,available)
        def _switch(self,side,available,reason):
            self.policy_events.append(dict(time=available.isoformat(),event='SETUP_INFORMATION_ONLY',direction=side,original_reason=reason,pending_directions=list(self.pending)))
        def evaluate(self,**kwargs):
            before=list(self.pending)
            entries,checks=super().evaluate(**kwargs)
            if entries:
                # Base has already committed a fully confirmed entry. This is
                # the first point at which other pending directions are removed.
                winner=self.owner
                self.policy_events.append(dict(time=(kwargs['minute']+timedelta(minutes=1)).isoformat(),event='ENTRY_CONFIRMED_OTHER_PENDING_CANCELLED',direction=winner,prior_pending=before,cancelled_pending=list(self.pending)))
                self.pending.clear();self.watch_side=None;self.watch_at=None
            return entries,checks
    return ConfirmedOnly

def setup_probe(sink,policy,side,at,bar,latest,current,previous,reference,gate,episode):
    if not bar:return
    sign=1 if side=='BULLISH' else -1
    ready=bool(latest and latest.ready and current.ready)
    gap=sign*(current.ema3_rsi-current.wma21_rsi) if current.ready else None
    pg=sign*(previous['snapshot'].ema3_rsi-previous['snapshot'].wma21_rsi) if previous and previous['snapshot'].ready else None
    consecutive=bool(previous and previous['minute']==at-timedelta(minutes=2))
    watch_live=bool(gate.opposite_switch and gate.watch_at is not None and at-gate.watch_at<timedelta(minutes=10))
    direction_pass=not watch_live or gate.watch_side in (None,side)
    flags=dict(indicators_ready=ready,
       completed_5m_alignment=bool(ready and sign*(latest.rsi9-latest.ema3_rsi)>0 and sign*(latest.ema3_rsi-latest.wma21_rsi)>0),
       direction_watch_pass=direction_pass,
       gap_positive=gap is not None and gap>0,
       previous_minute_available=consecutive,
       gap_expanding=bool(consecutive and gap is not None and pg is not None and gap>pg),
       unused_alignment_episode=not episode[side],actual_position_flat=gate.owner=='NONE',
       no_same_direction_pending=side not in gate.pending,before_cutoff=at.strftime('%H:%M')<'14:55')
    sink.append(dict(policy=policy,time=at.isoformat(),direction=side,flags=flags,failed=[k for k,v in flags.items() if not v],
       gap=gap,previous_gap=pg,gap_delta=gap-pg if gap is not None and pg is not None else None,
       completed_rsi=latest.rsi9 if latest else None,completed_ema=latest.ema3_rsi if latest else None,completed_wma=latest.wma21_rsi if latest else None,
       current_rsi=current.rsi9,current_ema=current.ema3_rsi,current_wma=current.wma21_rsi,
       directional_strength=sign*(current.wma21_rsi-reference.wma21_rsi) if current.ready and reference and reference.ready else None,
       pending_directions=list(gate.pending),watch_side=gate.watch_side,watch_at=gate.watch_at.isoformat() if gate.watch_at else None))

def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError('REPLAY_SOURCE_DIFFERS:'+old[:100])
    return text.replace(old,new,1)

def simulate(engine,day,raw,warm,asof,policy):
    source=inspect.getsource(engine.replay)
    needle='   if bar and g.can_signal(side,at)'
    source=replace_once(source,needle,"   _research_probe(_setup_audit,_policy,side,at,bar,latest,current,prev,ref,g,episode)\n"+needle)
    partial=asof.strftime('%H:%M')<'14:55'
    if partial:
        needle=" selected=[x for x in rows if x.timestamp.date()==day and '09:15'<=x.timestamp.strftime('%H:%M')<'14:55']"
        source=replace_once(source,needle,needle+"\n selected=[x for x in selected if x.timestamp+timedelta(minutes=1)<=_asof]")
        source=replace_once(source,'for i in range(340)]','for i in range(_minute_count)]')
        source=replace_once(source," if not any(x.timestamp==cutoff for x in rows):raise ValueError('EXACT_1455_OPEN_REQUIRED')",' # Partial replay does not require a future 14:55 open.')
        cut=" if active:\n  at=datetime.fromisoformat(TARGET+'T14:55:00+05:30')"
        if source.count(cut)!=1:raise ValueError('PARTIAL_REPLAY_END_ANCHOR_MISMATCH')
        source=source[:source.index(cut)]+"\n return dict(session_date=TARGET,trades=trades,audit=audit,open_trade=copy.deepcopy(active),rules=RULES,strategy_version=RULES['version'])\n"
    registry=[];Base=engine.WmaGapGate;Parent=Base if policy=='CURRENT' else changed_gate(Base)
    class Recording(Parent):
        def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);registry.append(self)
    audit=[];namespace=dict(engine.replay.__globals__,WmaGapGate=Recording,_research_probe=setup_probe,_setup_audit=audit,_policy=policy,_asof=asof,
                            _minute_count=int((asof-dt(day+'T09:15:00+05:30')).total_seconds()/60))
    exec(compile(source,'<isolated-research-replay>','exec'),namespace)
    result=namespace['replay'](day,raw,warm,dict(research_policy=policy))
    if len(registry)!=1:raise ValueError('ONE_GATE_REQUIRED')
    result.update(policy=policy,setup_diagnostics=audit,policy_events=getattr(registry[0],'policy_events',[]),observation_only=True,execution_enabled=False)
    active=result.get('open_trade')
    if active:
        last=next(r for r in raw if dt(r['timestamp'])==asof-timedelta(minutes=1))
        active.update(mark_time=asof.isoformat(),mark_price=float(last['close']),unrealized_nifty_points=(float(last['close'])-active['entry_price'])*(1 if active['direction']=='BULLISH' else -1))
    return result

def audit_parity(path,day,asof,result):
    frames={r['checkpoint']:r for r in result['audit']};issues=[];compared=0;seen={}
    if not path.exists():return dict(status='UNVERIFIED',compared=0,issues=['LIVE_AUDIT_MISSING'])
    with path.open() as stream:
        for line in stream:
            if not line.strip():continue
            if not line.endswith('\n'):continue
            r=json.loads(line);p=r.get('payload') or {};at=p.get('decision_timestamp')
            if r.get('stage')=='DIRECTIONAL_MANUAL_EXIT_RESET' and str(p.get('completed_at','')).startswith(day):
                if dt(p['completed_at'])<=asof:issues.append('MANUAL_RESET_REQUIRES_SEPARATE_REPLAY')
            if r.get('stage')!='DIRECTIONAL_DECISION' or r.get('status')!='PROCESSED' or not at or not at.startswith(day) or dt(at)>asof:continue
            if p.get('strategy_version')!=VERSION:issues.append('LIVE_VERSION_MISMATCH:'+at);continue
            if at in seen:
                if seen[at]!=p:issues.append('CONFLICTING_PROCESSED_AUDIT:'+at)
                continue
            seen[at]=p;f=frames.get(at)
            if not f:issues.append('REPLAY_CHECKPOINT_MISSING:'+at);continue
            compared+=1
            if f['owner_after']!=p['trade_owner_after']:issues.append('OWNER_MISMATCH:'+at)
            if abs(float(f['nifty_close'])-float(p['nifty_close']))>1e-5:issues.append('PRICE_MISMATCH:'+at)
            for key in ('rsi9','ema3','wma21'):
                if abs(float(f['completed_5m_indicators'][key])-float(p['completed_5m_indicators'][key]))>1e-5:issues.append('INDICATOR_MISMATCH:'+at+':'+key)
            recorded=sorted(e['event_type'] for e in p.get('event_details',[]))
            expected=sorted(c['event'] for c in f['transitions'])
            # Transition names differ between schemas; compare counts of entry
            # and exit transitions, with entry identity covered by owner/price.
            nentry=sum(e.get('entry_time')==at and e.get('exit_reason') is None for e in p.get('event_details',[]))
            if nentry!=expected.count('ENTRY_ACTIVE'):issues.append('ENTRY_TRANSITION_MISMATCH:'+at)
            if len(recorded)!=len(expected):issues.append('TRANSITION_COUNT_MISMATCH:'+at)
    return dict(status='PASS' if compared and not issues else 'MISMATCH' if issues else 'UNVERIFIED',compared=compared,issues=sorted(set(issues)))

def inputs(engine,day,path,fetch,output):
    index=engine.cache_index();warm=[];hashes={}
    for d,p in sorted(index.items()):
        if d>=day:continue
        body=json.loads(p.read_text());rows=body.get('candles') or []
        if body.get('session_date') not in (None,d) or body.get('underlying') not in (None,'NSE_INDEX|Nifty 50'):raise ValueError('CACHE_IDENTITY_MISMATCH:'+str(p))
        if rows:warm.append((d,rows));hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    if len(warm)<20:raise ValueError('TWENTY_PRIOR_WARMUP_SESSIONS_REQUIRED')
    # Warm every local prior session, matching the deployed live bootstrap.
    if fetch:
        if datetime.now(IST).date().isoformat()!=day:raise ValueError('FETCH_TODAY_ONLY')
        import httpx
        from dotenv import dotenv_values
        token=os.getenv('UPSTOX_ACCESS_TOKEN') or dotenv_values('.env').get('UPSTOX_ACCESS_TOKEN')
        if not token:raise ValueError('ANALYTICS_TOKEN_MISSING')
        url='https://api.upstox.com/v3/historical-candle/intraday/NSE_INDEX%7CNifty%2050/minutes/1'
        with httpx.Client(timeout=30) as client:
            r=client.get(url,headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
        if r.status_code!=200:raise ValueError('ANALYTICS_GET_FAILED_HTTP_'+str(r.status_code))
        body=r.json()
        if body.get('status')!='success':raise ValueError('ANALYTICS_GET_FAILED')
        raw=[]
        for row in body['data']['candles']:
            if dt(row[0]).date().isoformat()!=day:continue
            raw.append(dict(timestamp=dt(row[0]).isoformat(),open=float(row[1]),high=float(row[2]),low=float(row[3]),close=float(row[4]),volume=row[5]))
        path=output/'captured-nifty-1m.json';path.write_text(json.dumps(dict(session_date=day,underlying='NSE_INDEX|Nifty 50',candles=raw),indent=2)+'\n')
    else:
        path=path or index.get(day)
        if not path:raise ValueError('TODAY_INPUT_MISSING: use --fetch-today or --input PATH')
        body=json.loads(Path(path).read_text())
        if body.get('session_date') not in (None,day) or body.get('underlying') not in (None,'NSE_INDEX|Nifty 50'):raise ValueError('INPUT_IDENTITY_MISMATCH')
        raw=body['candles']
    hashes[str(path)]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return sorted(raw,key=lambda r:dt(r['timestamp'])),warm,hashes

class Checks(unittest.TestCase):
    @staticmethod
    def gate():
        from market_lab import hilega_v2_alignment_replay_v1 as e
        return e,changed_gate(e.WmaGapGate)(opposite_switch=True)
    @staticmethod
    def event(e,side):
        return e.StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21' if side=='BULLISH' else 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL',dt('2026-10-16T13:45:00+05:30'),None,'IDLE','ARMED',details={})
    def test_opposite_arm_keeps_original(self):
        e,g=self.gate();at=dt('2026-10-16T13:50:00+05:30');g.signal(self.event(e,'BEARISH'),at)
        g.observe_arms([SimpleNamespace(event_type='PATH1_ARMED_RSI_CROSS_EMA3_UP')],at+timedelta(minutes=5))
        self.assertIn('BEARISH',g.pending);self.assertIsNone(g.watch_side)
    def test_opposite_setup_does_not_cancel(self):
        e,g=self.gate();at=dt('2026-10-16T13:50:00+05:30');g.signal(self.event(e,'BEARISH'),at);g.pending['BEARISH']['armed_at']=at
        g.signal(self.event(e,'BULLISH'),at+timedelta(minutes=5))
        self.assertEqual(set(g.pending),{'BULLISH','BEARISH'});self.assertEqual(g.pending['BEARISH']['armed_at'],at)
    def test_both_directions_remain_eligible(self):
        _,g=self.gate();at=dt('2026-10-16T14:00:00+05:30')
        self.assertTrue(g.can_signal('BULLISH',at));self.assertTrue(g.can_signal('BEARISH',at))
    def test_confirmed_entry_clears_other_pending(self):
        e,g=self.gate();at=dt('2026-10-16T13:50:00+05:30')
        for s in ('BEARISH','BULLISH'):g.signal(self.event(e,s),at);g.pending[s]['armed_at']=at
        snapshot=lambda w,ema:SimpleNamespace(ready=True,rsi9=45,ema3_rsi=ema,wma21_rsi=w)
        g.previous=dict(minute=at+timedelta(minutes=1),snapshot=snapshot(49,48),wma_change=-1)
        entries,checks=g.evaluate(minute=at+timedelta(minutes=2),current=snapshot(48.8,47.5),reference=snapshot(50,49),price=100)
        self.assertEqual(len(entries),1);self.assertEqual(g.owner,'BEARISH');self.assertEqual(g.pending,{})
    def test_pending_window_still_expires(self):
        e,g=self.gate();at=dt('2026-10-16T13:50:00+05:30');g.signal(self.event(e,'BEARISH'),at)
        snap=SimpleNamespace(ready=True,rsi9=45,ema3_rsi=48,wma21_rsi=49)
        entries,checks=g.evaluate(minute=at+timedelta(minutes=10),current=snap,reference=snap,price=100)
        self.assertFalse(entries);self.assertFalse(g.pending);self.assertIn('WINDOW_EXPIRED',checks[0]['reasons'])
    def test_existing_position_not_replaced_by_setup(self):
        e,g=self.gate();g.owner='BEARISH';g.active={'time':dt('2026-10-16T14:00:00+05:30'),'price':100}
        g.signal(self.event(e,'BULLISH'),dt('2026-10-16T14:05:00+05:30'));self.assertFalse(g.pending);self.assertEqual(g.owner,'BEARISH')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--date',default='2026-10-16');p.add_argument('--as-of',default='14:25')
    p.add_argument('--input',type=Path);p.add_argument('--fetch-today',action='store_true');p.add_argument('--test',action='store_true')
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-pending-confirmation-20261016'))
    p.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'));a=p.parse_args()
    if a.test:
        r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks));raise SystemExit(0 if r.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=VERSION:raise ValueError('STRATEGY_VERSION_MISMATCH')
    at=dt(a.date+'T'+a.as_of+':00+05:30')
    if not '09:20'<=a.as_of<='14:55':raise ValueError('AS_OF_MUST_BE_0920_TO_1455')
    if at>datetime.now(IST):raise ValueError('AS_OF_NOT_YET_AVAILABLE')
    a.output.mkdir(parents=True,exist_ok=True);raw,warm,hashes=inputs(engine,a.date,a.input,a.fetch_today,a.output)
    # Discard all future candles even if the API returned a longer session.
    raw=[r for r in raw if dt(r['timestamp'])<=at]
    results={policy:simulate(engine,a.date,raw,warm,at,policy) for policy in ('CURRENT','CONFIRMED_OPPOSITE_ONLY')}
    parity=audit_parity(a.audit,a.date,at,results['CURRENT'])
    payload=dict(status='COMPARABLE' if parity['status']=='PASS' else 'BASELINE_NOT_VERIFIED',session_date=a.date,as_of=at.isoformat(),
       baseline_live_parity=parity,source_sha256=hashes,replay_engine_sha256=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
       runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),warmup_sessions=len(warm),rule_changes=RULE_CHANGES,results=results,
       observation_only=True,orders_sent=False,warning='Research-only reconstruction. Partial sessions retain open positions with unrealized NIFTY marks, not invented exits. No option fills/costs. Do not compare policy performance unless baseline parity passes. No live strategy changes.')
    (a.output/'report.json').write_text(json.dumps(payload,indent=2,default=str)+'\n')
    with (a.output/'setup-diagnostics.csv').open('w',newline='') as h:
        fields=['policy','time','direction','failed','gap','previous_gap','gap_delta','directional_strength','pending_directions','watch_side','watch_at']
        writer=csv.DictWriter(h,fields,extrasaction='ignore');writer.writeheader()
        for result in results.values():
            for row in result['setup_diagnostics']:writer.writerow({**row,'failed':';'.join(row['failed']),'pending_directions':';'.join(row['pending_directions'])})
    lines=['# Pending direction: confirmed-opposite research','',payload['warning'],'','Baseline parity: '+parity['status'],'',
           '| Rule | Existing | Research change |','|---|---|---|']
    lines += ['| '+' | '.join(row)+' |' for row in RULE_CHANGES]
    lines+=['','| Policy | Closed trades | Closed points | Open direction | Open entry | Open mark points |','|---|---:|---:|---|---|---:|']
    for policy,result in results.items():
        active=result.get('open_trade') or {};trades=result['trades']
        lines.append(f"| {policy} | {len(trades)} | {sum(t['points'] for t in trades):.2f} | {active.get('direction','NONE')} | {active.get('entry_time','—')} | {active.get('unrealized_nifty_points',0):.2f} |")
    lines+=['','## Alternative setup checks, 14:00–14:25','','| Policy | Time | Direction | Failed conditions | Gap change |','|---|---|---|---|---:|']
    for policy,result in results.items():
        for row in result['setup_diagnostics']:
            if '14:00'<=row['time'][11:16]<='14:25':lines.append(f"| {policy} | {row['time'][11:16]} | {row['direction']} | {', '.join(row['failed']) or 'ALL PASSED'} | {row['gap_delta']} |")
    for policy,result in results.items():
        lines+=['','## '+policy+' entry timeline','']
        for t in result['trades']+([result['open_trade']] if result.get('open_trade') else []):
            lines.append(f"- {t['direction']}: setup {t.get('signal_time')}; entry {t['entry_time']} at {t['entry_price']}; exit {t.get('exit_time','OPEN')}")
    lines+=['','Parity issues: '+json.dumps(parity['issues'])]
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text);print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if parity['status']=='PASS' else 2)

if __name__=='__main__':main()
