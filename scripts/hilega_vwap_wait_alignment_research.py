"""Stateful, cache-only VWAP wait vs block research. No broker or service access.
Requires hilega_vwap_confirmed36_research.py already in repository root.
"""
import argparse
import copy
import hashlib
import json
import math
import os
import types
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

IST=ZoneInfo('Asia/Kolkata')
POLICIES=('CURRENT','VWAP_BLOCK','VWAP_WAIT_5M')
VERSION='five-minute-setup-1.2.0-pending-switch'


def dt(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    return stamp.astimezone(IST)


def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


def read_cache(root,path):
    request=dict(path=path,params={});p=root/'raw-provider-get'/(fingerprint(request)+'.json')
    record=json.loads(p.read_text())
    if record['request']!=request or fingerprint(record['body'])!=record['body_sha256']:
        raise ValueError('RAW_CACHE_IDENTITY_OR_HASH_MISMATCH')
    return record['body']['data']['candles']


def source_data(root,report,support):
    start=datetime.fromisoformat(report['start_date']).date()-timedelta(days=70)
    end=datetime.fromisoformat(report['end_date']).date()
    if (root/'session-calendar.json').exists():
        calendar=json.loads((root/'session-calendar.json').read_text())
        start=datetime.fromisoformat(calendar['warmup_start']).date()
        end=datetime.fromisoformat(max(calendar['session_dates'])).date()
    key=quote('NSE_INDEX|Nifty 50',safe='')
    days=sorted({dt(r[0]).date().isoformat() for r in read_cache(root,f'/v3/historical-candle/{key}/days/1/{end}/{start}') if start<=dt(r[0]).date()<=end})
    raw=[];cursor=start
    while cursor<=end:
        last=min(end,cursor+timedelta(days=27))
        raw.extend(read_cache(root,f'/v3/historical-candle/{key}/minutes/1/{last}/{cursor}'))
        cursor=last+timedelta(days=1)
    return days,support.group_minutes(raw)


class Waiting:
    def __init__(self):self.value=None;self.events=[]
    def log(self,event,at,**values):self.events.append(dict(event=event,time=at.isoformat(),**values))
    def confirm(self,event,side,at):
        old=self.value
        if old and old['direction']==side:
            self.log('SAME_DIRECTION_RECONFIRMED_WAIT_RETAINED',at,direction=side)
            return
        if old:self.finish('CANCELLED_OPPOSITE_CONFIRMED',at,replacement_direction=side)
        self.value=dict(event=event,direction=side,confirmed_at=at,
                        setup_available_at=event.details['wma_gap']['signal_available_at'])
        self.log('WAIT_STARTED',at,direction=side,setup_available_at=self.value['setup_available_at'])
    def finish(self,reason,at,**values):
        if self.value:
            old=self.value
            self.log(reason,at,direction=old['direction'],confirmed_at=old['confirmed_at'].isoformat(),
                     waiting_minutes=(at-old['confirmed_at']).total_seconds()/60,**values)
            self.value=None


def gate_factory(Base,direction,vwap,policy,registry):
    class ResearchGate(Base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.wait=Waiting();self.telemetry=[];registry.append(self)
        def evaluate(self,*,minute,current,reference,price,exit_boundary=False):
            at=minute+timedelta(minutes=1)
            previous=copy.deepcopy(self.previous)
            entries,checks=super().evaluate(minute=minute,current=current,reference=reference,price=price,exit_boundary=exit_boundary)
            if policy=='CURRENT':return entries,checks
            if at.strftime('%H:%M')>='14:55':
                self.wait.finish('CANCELLED_SESSION_CUTOFF',at)
                return entries,checks
            if entries:
                if len(entries)!=1:raise ValueError('ONE_POSITION_ENTRY_REQUIRED')
                event=entries[0];side=direction(event);frame=vwap(at,side)
                self.telemetry.append(dict(event='CONFIRMED_SIGNAL_VWAP_CHECK',time=at.isoformat(),direction=side,**frame))
                same_wait=self.wait.value is not None and self.wait.value['direction']==side
                # Once waiting, a repeated same-direction confirmation cannot
                # bypass the five-minute recheck schedule.
                if frame['agrees'] and not same_wait:
                    if self.wait.value:
                        reason='WAIT_RESOLVED_SAME_DIRECTION_CONFIRMATION' if self.wait.value['direction']==side else 'CANCELLED_OPPOSITE_CONFIRMED'
                        self.wait.finish(reason,at,replacement_direction=side)
                    return entries,checks
                # Super confirmed the strategy entry, but research VWAP vetoes it.
                # Revert only its position commit; confirmation was consumed once.
                self.owner='NONE';self.active=None
                for check in checks:
                    if check.get('status')=='ENTRY':
                        check.update(status='VWAP_BLOCKED' if policy=='VWAP_BLOCK' else 'VWAP_WAIT',vwap=frame)
                if policy=='VWAP_BLOCK':
                    self.telemetry.append(dict(event='ENTRY_BLOCKED_VWAP',time=at.isoformat(),direction=side,**frame))
                    return [],checks
                self.wait.confirm(event,side,at)
            if policy!='VWAP_WAIT_5M' or not self.wait.value or self.owner!='NONE' or at.minute%5:
                return [],checks
            pending=self.wait.value;side=pending['direction'];frame=vwap(at,side)
            # Recheck the original gate's current strength, prior-minute strength,
            # persistence, positive gap and expansion. A probe has no position or
            # effect on the actual gate. Only the original 10m setup expiry is
            # replaced by the explicitly unbounded VWAP waiting policy.
            probe=Base(opposite_switch=False);probe.previous=previous
            probe.pending={side:dict(event=pending['event'],available=minute-timedelta(minutes=1),armed_at=minute-timedelta(minutes=1))}
            accepted,fresh=probe.evaluate(minute=minute,current=current,reference=reference,price=price,exit_boundary=False)
            self.telemetry.append(dict(event='WAIT_5M_CHECK',time=at.isoformat(),direction=side,
                                       current_strategy_checks_pass=bool(accepted),strategy_checks=fresh,**frame))
            for check in fresh:
                check.update(research_vwap_wait=True,original_signal_available_at=pending['setup_available_at'],
                             first_confirmed_at=pending['confirmed_at'].isoformat(),original_10m_window_overridden=True)
                if check.get('status')=='ENTRY' and not frame['agrees']:check['status']='VWAP_WAIT'
            checks.extend(fresh)
            if not frame['agrees'] or not accepted:return [],checks
            event=accepted[0];gap=dict(event.details['wma_gap'])
            gap.update(signal_available_at=pending['setup_available_at'],first_confirmed_at=pending['confirmed_at'].isoformat(),
                       delayed_vwap_entry=True,waiting_minutes=(at-pending['confirmed_at']).total_seconds()/60,
                       original_10m_window_overridden=True,vwap=frame)
            event=replace(event,details=dict(event.details,wma_gap=gap))
            self.owner=side;self.active=dict(time=at,price=price);self.pending.clear()
            self.watch_side=None;self.watch_at=None
            self.wait.finish('DELAYED_ENTRY',at,entry_price=price)
            return [event],checks
    return ResearchGate


def trade_signature(trades):
    return [(r['direction'],dt(r['entry_time']),dt(r['exit_time']),round(float(r['entry_price']),5),
             round(float(r['exit_price']),5),round(float(r['points']),5)) for r in sorted(trades,key=lambda r:dt(r['entry_time']))]


def simulate(engine,day,raw,warm,futures,policy,support):
    # Require complete session VWAP evidence before comparing any policy.
    support.vwap_at(futures,dt(day+'T15:30:00+05:30'))
    def frame(at,side):
        value=support.vwap_at(futures,at)
        if not 0<=value['age_at_signal_seconds']<300:raise ValueError('STALE_VWAP')
        return dict(vwap=value['vwap'],futures_close=value['futures_close'],distance_points=value['distance_points'],
                    candle_available_at=value['candle_available_at'],agrees=value['price_position']==('ABOVE' if side=='BULLISH' else 'BELOW'))
    registry=[];gate=gate_factory(engine.WmaGapGate,engine.direction,frame,policy,registry)
    # Clone function globals inside this research process. No monkeypatch or
    # source-file write occurs in the installed strategy or running workers.
    namespace=dict(engine.replay.__globals__,WmaGapGate=gate)
    replay=types.FunctionType(engine.replay.__code__,namespace,engine.replay.__name__,engine.replay.__defaults__,engine.replay.__closure__)
    result=replay(day,raw,warm,dict(research_policy=policy))
    if len(registry)!=1:raise ValueError('UNEXPECTED_REPLAY_GATE_COUNT')
    gate_instance=registry[0];gate_instance.wait.finish('CANCELLED_SESSION_CUTOFF',dt(day+'T14:55:00+05:30'))
    result.update(research_policy=policy,waiting_audit=gate_instance.wait.events,vwap_audit=gate_instance.telemetry,
                  research_strategy_version=VERSION+'-vwap-wait-research-v1',observation_only=True,execution_enabled=False)
    return result


def run_root(root,reports,output,engine,support):
    parent=json.loads(reports[0].read_text());sessions,grouped=source_data(root,parent,support)
    report_sources=[json.loads(path.read_text()) for path in reports]
    if any(source.get('strategy_version')!=VERSION for source in report_sources):
        raise ValueError('SOURCE_REPORT_STRATEGY_VERSION_MISMATCH')
    # Monthly report list starts with 3-month, which supplies the full window.
    day_results={};coverage=[]
    required=sorted({d for path in reports for d in json.loads(path.read_text())['session_dates']})
    for day in required:
        check=dict(session_date=day,status='INCOMPLETE',issues=[])
        try:
            expected=json.loads((root/'replays'/(day+'.json')).read_text())
            if expected.get('strategy_version')!=VERSION:raise ValueError('SAVED_BASELINE_VERSION_MISMATCH')
            for source in report_sources:
                if day in source['session_dates'] and trade_signature([t for t in source['trades'] if t['session_date']==day])!=trade_signature(expected['trades']):
                    raise ValueError('SOURCE_REPORT_REPLAY_MISMATCH')
            raw=grouped.get(day,[]);warm=[(d,grouped[d]) for d in sessions if d<day and grouped.get(d)][-30:]
            if len(warm)<20:raise ValueError('TWENTY_PRIOR_WARMUP_SESSIONS_REQUIRED')
            saved=json.loads((root/'futures-5m'/(day+'.json')).read_text())
            contract=saved['contract']
            if contract.get('underlying_key')!='NSE_INDEX|Nifty 50' or str(contract.get('expiry',''))<day:
                raise ValueError('INVALID_FUTURES_CONTRACT')
            catalog=json.loads((root/'futures-catalog.json').read_text())['contracts']
            if support.resolve_front(catalog,day)['instrument_key']!=contract['instrument_key']:
                raise ValueError('FRONT_FUTURES_IDENTITY_MISMATCH')
            evaluated={}
            for policy in POLICIES:
                result=simulate(engine,day,raw,warm,saved['candles'],policy,support)
                if policy=='CURRENT' and trade_signature(result['trades'])!=trade_signature(expected['trades']):
                    raise ValueError('UNMODIFIED_BASELINE_PARITY_FAILED')
                evaluated[policy]=result
                destination=output/'sessions'/root.name/day/(policy+'.json')
                destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(result,indent=2,default=str)+'\n')
            day_results[day]=evaluated;check['status']='COMPLETE'
        except Exception as exc:check['issues'].append(str(exc) if isinstance(exc,(ValueError,KeyError)) else type(exc).__name__)
        coverage.append(check);print(day,check['status'],check['issues'],flush=True)
        (output/('progress-'+root.name+'.json')).write_text(json.dumps(coverage,indent=2)+'\n')
    results=[]
    for path in reports:
        source=json.loads(path.read_text());days=set(source['session_dates']);comparisons=[];all_rows=[]
        for policy in POLICIES:
            trades=[];events=[];vwapaudit=[]
            for day in sorted(days & day_results.keys()):
                result=day_results[day][policy]
                trades.extend(dict(t,session_date=day,policy=policy) for t in result['trades'])
                events.extend(result['waiting_audit']);vwapaudit.extend(result['vwap_audit'])
            trades.sort(key=lambda t:dt(t['entry_time']));summary=support.stats(trades)
            summary.update(policy=policy,waits_started=sum(e['event']=='WAIT_STARTED' for e in events),
                           delayed_entries=sum(e['event']=='DELAYED_ENTRY' for e in events),
                           cancelled_opposite=sum(e['event']=='CANCELLED_OPPOSITE_CONFIRMED' for e in events),
                           cancelled_cutoff=sum(e['event']=='CANCELLED_SESSION_CUTOFF' for e in events),
                           blocked_confirmations=sum(e['event']=='ENTRY_BLOCKED_VWAP' for e in vwapaudit))
            comparisons.append(summary);all_rows.extend(trades)
        checks=[c for c in coverage if c['session_date'] in days]
        results.append(dict(period=source['period'],source_report=str(path),source_report_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            status='COMPLETE' if len(checks)==len(days) and all(c['status']=='COMPLETE' for c in checks) else 'INCOMPLETE',
                            requested_sessions=len(days),complete_sessions=sum(c['status']=='COMPLETE' for c in checks),
                            comparisons=comparisons,coverage=checks,trades=all_rows))
    return results


class Checks(unittest.TestCase):
    def event(self):
        from types import SimpleNamespace
        return SimpleNamespace(details={'wma_gap':{'signal_available_at':'2026-07-17T09:20:00+05:30'}})
    def test_opposite_confirmation_replaces_wait(self):
        w=Waiting();at=dt('2026-07-17T09:22:00+05:30');w.confirm(self.event(),'BULLISH',at)
        w.confirm(self.event(),'BEARISH',at+timedelta(minutes=20))
        self.assertEqual(w.value['direction'],'BEARISH');self.assertEqual(w.events[1]['event'],'CANCELLED_OPPOSITE_CONFIRMED')
    def test_same_direction_does_not_reset_clock(self):
        w=Waiting();at=dt('2026-07-17T09:22:00+05:30');w.confirm(self.event(),'BULLISH',at)
        w.confirm(self.event(),'BULLISH',at+timedelta(minutes=20));self.assertEqual(w.value['confirmed_at'],at)
    def test_cutoff_clears_wait(self):
        w=Waiting();at=dt('2026-07-17T09:22:00+05:30');w.confirm(self.event(),'BULLISH',at)
        w.finish('CANCELLED_SESSION_CUTOFF',dt('2026-07-17T14:55:00+05:30'));self.assertIsNone(w.value)
    def test_partial_signature_not_equal(self):self.assertNotEqual(trade_signature([]),[('BULLISH',)])

    def harness(self,agreement=False):
        from types import SimpleNamespace
        from dataclasses import dataclass
        @dataclass
        class Event:
            details:dict
            side:str='BULLISH'
        class Base:
            def __init__(self,opposite_switch=None):
                self.owner='NONE';self.active=None;self.pending={};self.previous=None
                self.watch_side=None;self.watch_at=None;self.queued=[]
            def evaluate(self,*,minute,current,reference,price,exit_boundary=False):
                entries=self.queued;self.queued=[]
                if not entries and self.pending and current.pass_checks:
                    entries=[next(iter(self.pending.values()))['event']]
                self.previous={'minute':minute}
                if entries:self.owner=entries[0].side;self.active={'time':minute+timedelta(minutes=1),'price':price}
                return entries,[dict(status='ENTRY' if entries else 'WAIT')]
        state={'agrees':agreement};registry=[]
        def vwap(at,side):return dict(agrees=state['agrees'],vwap=100.,futures_close=101.,candle_available_at=at.isoformat())
        Gate=gate_factory(Base,lambda e:e.side,vwap,'VWAP_WAIT_5M',registry)
        gate=Gate();event=Event(details={'wma_gap':{'signal_available_at':'2026-07-17T09:20:00+05:30'}})
        def tick(at,checks=True):
            return gate.evaluate(minute=dt(at)-timedelta(minutes=1),current=SimpleNamespace(pass_checks=checks),reference=None,price=101.)[0]
        return gate,event,state,tick
    def test_opposed_confirmation_waits_without_position(self):
        gate,event,state,tick=self.harness();gate.queued=[event]
        self.assertFalse(tick('2026-07-17T09:22:00+05:30'))
        self.assertEqual(gate.owner,'NONE');self.assertIsNotNone(gate.wait.value)
    def test_no_entry_between_five_minute_boundaries(self):
        gate,event,state,tick=self.harness();gate.queued=[event];tick('2026-07-17T09:22:00+05:30')
        state['agrees']=True
        self.assertFalse(tick('2026-07-17T09:23:00+05:30'))
        self.assertTrue(tick('2026-07-17T09:25:00+05:30'))
    def test_wait_can_continue_beyond_ten_minutes(self):
        gate,event,state,tick=self.harness();gate.queued=[event];tick('2026-07-17T09:22:00+05:30')
        state['agrees']=True
        self.assertTrue(tick('2026-07-17T10:00:00+05:30'))
        self.assertEqual(gate.wait.events[-1]['waiting_minutes'],38)
    def test_current_checks_must_pass_before_delayed_entry(self):
        gate,event,state,tick=self.harness();gate.queued=[event];tick('2026-07-17T09:22:00+05:30')
        state['agrees']=True
        self.assertFalse(tick('2026-07-17T09:25:00+05:30',False))
        self.assertIsNotNone(gate.wait.value)
    def test_reconfirmation_cannot_bypass_boundary(self):
        gate,event,state,tick=self.harness();gate.queued=[event];tick('2026-07-17T09:22:00+05:30')
        state['agrees']=True;gate.queued=[event]
        self.assertFalse(tick('2026-07-17T09:23:00+05:30'))
        self.assertEqual(gate.owner,'NONE')
    def test_opposite_confirmed_replaces_pending_direction(self):
        gate,event,state,tick=self.harness();gate.queued=[event];tick('2026-07-17T09:22:00+05:30')
        event=replace(event,side='BEARISH');gate.queued=[event]
        tick('2026-07-17T09:24:00+05:30')
        self.assertEqual(gate.wait.value['direction'],'BEARISH')
    def test_initial_alignment_allows_original_minute_entry(self):
        gate,event,state,tick=self.harness(True);gate.queued=[event]
        self.assertTrue(tick('2026-07-17T09:22:00+05:30'));self.assertIsNone(gate.wait.value)
    def test_cutoff_never_enters_waiting_trade(self):
        gate,event,state,tick=self.harness();gate.queued=[event];tick('2026-07-17T09:22:00+05:30')
        state['agrees']=True
        self.assertFalse(tick('2026-07-17T14:55:00+05:30'));self.assertIsNone(gate.wait.value)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--research-root',action='append',type=Path)
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-vwap-wait-vs-block-20261016'))
    p.add_argument('--test',action='store_true');args=p.parse_args()
    if args.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if not args.research_root:p.error('--research-root required; repeat for confirmed36 and monthly roots')
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_vwap_confirmed36_research as support
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=VERSION:raise ValueError('ENGINE_STRATEGY_VERSION_MISMATCH')
    args.output.mkdir(parents=True,exist_ok=True)
    engine_hash=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest();results=[]
    for root in args.research_root:
        paths=[root/'report.json'] if (root/'report.json').exists() else [root/n/'report.json' for n in ('3-month','1-month','prior-two-months')]
        if not all(path.exists() for path in paths):raise ValueError('SOURCE_RESEARCH_REPORTS_REQUIRED:'+str(root))
        results.extend(run_root(root,paths,args.output,engine,support))
    payload=dict(model='HILEGA_STATEFUL_VWAP_WAIT_VS_BLOCK_RESEARCH_V1',status='COMPLETE' if results and all(r['status']=='COMPLETE' for r in results) else 'INCOMPLETE',
                 strategy_version=VERSION,replay_engine_sha256=engine_hash,runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 observation_only=True,orders_sent=False,results=results,
                 warning='Research reconstruction, gross NIFTY points without option fills or costs. Stateful entry/exit replay; no changes to running strategy. Trend cohort selected retrospectively; sample periods overlap.',
                 waiting_rule='First confirmed signal starts waiting if VWAP opposes. Recheck current gate conditions and VWAP only at completed 5m boundaries. Opposite confirmed signal supersedes the wait; an arm alone does not. Original setup window expiry overridden only for the VWAP wait. Existing 14:55 cutoff retained. Newly confirmed signals already agreeing with VWAP may enter at their original minute confirmation.')
    (args.output/'report.json').write_text(json.dumps(payload,indent=2,default=str)+'\n')
    lines=['# Stateful VWAP waiting versus blocking','',payload['waiting_rule'],'',payload['warning'],'',
           '| Period | Coverage | Policy | Trades | Points | Change vs current | Closed-trade drawdown | Delayed entries | Waits cancelled opposite | Waits expired at cutoff |',
           '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for result in results:
        base=result['comparisons'][0]['net_nifty_points']
        for c in result['comparisons']:
            lines.append(f"| {result['period']} | {result['complete_sessions']}/{result['requested_sessions']} | {c['policy']} | {c['priced_trades']} | {c['net_nifty_points']:.2f} | {c['net_nifty_points']-base:.2f} | {c['max_closed_trade_drawdown_points']:.2f} | {c['delayed_entries']} | {c['cancelled_opposite']} | {c['cancelled_cutoff']} |")
    lines+=['','Status: '+payload['status']]
    text='\n'.join(lines)+'\n';(args.output/'summary.md').write_text(text);print(text);print('REPORT:',args.output/'report.json')
    raise SystemExit(0 if payload['status']=='COMPLETE' else 2)


if __name__=='__main__':main()
