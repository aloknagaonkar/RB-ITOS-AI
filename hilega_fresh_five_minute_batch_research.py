"""Offline fresh 5m decisions versus verified retained-candidate research.

No pending candidate, expiry, persistence, direction watch or alignment-episode
entry restriction. Every completed 5m boundary evaluates current RSI/EMA/WMA
ordering, >=.75 directional WMA change, positive expanding completed-5m gap,
flat-position and cutoff requirements. Entries use that boundary as setup time.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timedelta
import unittest

FRESH=('FRESH_5M','FRESH_5M_EMA10','FRESH_5M_EMA10_WMA_LOCK','FRESH_5M_EMA10_WMA_EXCEPTION')

def fresh_gate(engine):
    class Fresh(engine.WmaGapGate):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.policy_events=[];self.opposite_switch=False
        def observe_arms(self,events,available):pass
        def can_signal(self,side,available):return False
        def signal(self,event,available):pass
        def evaluate(self,*,minute,current,reference,price,exit_boundary=False):
            at=minute+timedelta(minutes=1);self.pending.clear()
            self.previous=dict(minute=minute,snapshot=current,wma_change=None)
            if at.minute%5:return [],[]
            ready=bool(current.ready and reference and reference.ready)
            if ready:
                values=[current.rsi9,current.ema3_rsi,current.wma21_rsi,reference.rsi9,reference.ema3_rsi,reference.wma21_rsi]
                if any(not math.isfinite(float(v)) for v in values):raise ValueError('NONFINITE_FRESH_INDICATORS')
            checks=[];accepted=[]
            for side in ('BULLISH','BEARISH'):
                sign=1 if side=='BULLISH' else -1
                strength=sign*(current.wma21_rsi-reference.wma21_rsi) if ready else None
                gap=sign*(current.ema3_rsi-current.wma21_rsi) if ready else None
                previous_gap=sign*(reference.ema3_rsi-reference.wma21_rsi) if ready else None
                ordering=bool(ready and sign*(current.rsi9-current.ema3_rsi)>0 and sign*(current.ema3_rsi-current.wma21_rsi)>0)
                flags=dict(indicators_ready=ready,completed_5m_alignment=ordering,
                    wma_threshold_pass=bool(ready and strength>=.75),gap_positive_pass=bool(ready and gap>0),
                    gap_expanding_pass=bool(ready and gap>previous_gap),actual_position_flat=self.owner=='NONE',
                    before_cutoff=not self.locked and at.strftime('%H:%M')<'14:55')
                reasons=[name for name,value in flags.items() if not value]
                check=dict(direction=side,signal_timestamp=at.isoformat(),signal_available_at=at.isoformat(),
                    minute_timestamp=minute.isoformat(),decision_timestamp=at.isoformat(),
                    current_rsi9=current.rsi9,current_ema3=current.ema3_rsi,current_wma21=current.wma21_rsi,
                    previous_rsi9=reference.rsi9 if ready else None,previous_ema3=reference.ema3_rsi if ready else None,
                    previous_wma21=reference.wma21_rsi if ready else None,directional_wma_strength=strength,
                    current_gap=gap,previous_gap=previous_gap,gap_delta=gap-previous_gap if ready else None,
                    **flags,persistence_required=False,confirmation_window_pass=True,
                    setup_basis='FRESH_COMPLETED_5M_CURRENT_ALIGNMENT',status='ENTRY' if not reasons else 'NO_ENTRY',reasons=reasons)
                checks.append(check)
                if reasons:continue
                event_type='ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21' if side=='BULLISH' else 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL'
                event=engine.StrategyEvent(event_type,at,'FRESH_5M_RESEARCH','FLAT',side+'_ACTIVE',price=float(price),
                    entry_time=at,entry_price=float(price),details=dict(wma_gap=check))
                accepted.append(event);self.owner=side;self.active=dict(time=at,price=float(price))
            if len(accepted)>1:raise ValueError('MULTIPLE_FRESH_ENTRIES')
            return accepted,checks
    return Fresh

class Checks(unittest.TestCase):
    def harness(self):
        class Base:
            def __init__(self):self.pending={};self.owner='NONE';self.active=None;self.locked=False
        def event(kind,at,source,before,after,**kw):return SimpleNamespace(event_type=kind,event_time=at,**kw)
        return fresh_gate(SimpleNamespace(WmaGapGate=Base,StrategyEvent=event))()
    def tick(self,g,clock='10:05',rsi=60,ema=57,wma=55,prsi=57,pema=55,pwma=54):
        at=datetime.fromisoformat('2026-10-06T'+clock+':00+05:30')
        return g.evaluate(minute=at-timedelta(minutes=1),current=SimpleNamespace(ready=True,rsi9=rsi,ema3_rsi=ema,wma21_rsi=wma),
            reference=SimpleNamespace(ready=True,rsi9=prsi,ema3_rsi=pema,wma21_rsi=pwma),price=100)
    def test_first_qualifying_boundary_enters_immediately(self):
        g=self.harness();entries,checks=self.tick(g);self.assertEqual(len(entries),1)
        self.assertEqual(entries[0].event_time.isoformat(),'2026-10-06T10:05:00+05:30');self.assertFalse(g.pending)
    def test_no_entry_between_boundaries(self):
        g=self.harness();self.assertEqual(self.tick(g,'10:03'),([],[]));self.assertEqual(g.owner,'NONE')
    def test_failed_attempt_not_carried_forward(self):
        g=self.harness();self.assertFalse(self.tick(g,wma=54.1)[0]);self.assertFalse(g.pending)
        entries,_=self.tick(g,'10:10');self.assertEqual(entries[0].details['wma_gap']['signal_available_at'][11:16],'10:10')
    def test_ordering_mandatory(self):
        g=self.harness();entries,checks=self.tick(g,rsi=56);self.assertFalse(entries);self.assertFalse(checks[0]['completed_5m_alignment'])
    def test_strength_mandatory(self):
        g=self.harness();entries,checks=self.tick(g,pwma=54.5);self.assertFalse(entries);self.assertFalse(checks[0]['wma_threshold_pass'])
    def test_expansion_compares_completed_reference(self):
        g=self.harness();entries,checks=self.tick(g,pema=57);self.assertFalse(entries);self.assertFalse(checks[0]['gap_expanding_pass'])
    def test_active_position_prevents_entry(self):
        g=self.harness();g.owner='BEARISH';self.assertFalse(self.tick(g)[0])
    def test_cutoff_prevents_entry(self):self.assertFalse(self.tick(self.harness(),'14:55')[0])
    def test_bearish_symmetric(self):
        g=self.harness();entries,_=self.tick(g,rsi=40,ema=43,wma=45,prsi=43,pema=45,pwma=46)
        self.assertEqual(g.owner,'BEARISH');self.assertEqual(len(entries),1)
    def test_canonical_signal_does_not_create_pending(self):
        g=self.harness();g.signal(None,None);self.assertFalse(g.pending)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--previous-root',type=Path,default=Path('data/research/hilega-retained-policy-last10-20261016'))
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--today-input',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016-v3/today-recorded-overrides.json'))
    ap.add_argument('--stack-module',default='hilega_retained_ema10_wma_lock_research2')
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-fresh-five-minute-last10-20261016'))
    ap.add_argument('--test',action='store_true');a=ap.parse_args()
    if a.test:
        r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks));raise SystemExit(0 if r.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_retained_policy_batch_research as previous
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as batch
    import hilega_ema10_exit_day_research as exits
    import hilega_post_entry_wma_lock_today_research as lock
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    stack=previous.load_stack(a.stack_module)
    if engine.RULES['version']!=p.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    old=json.loads((a.previous_root/'report.json').read_text())
    if old['status']!='COMPLETE' or old['strategy_version']!=p.VERSION:raise ValueError('COMPLETE_VERIFIED_PREVIOUS_BATCH_REQUIRED')
    if old['exception_policy_version']!='RSI_EMA_LOCK_EXCEPTION_V2_BULL_GT45_BEAR_LT55':raise ValueError('PREVIOUS_EXCEPTION_VERSION_MISMATCH')
    parent=json.loads((a.research_root/'3-month/report.json').read_text())
    if parent['strategy_version']!=p.VERSION:raise ValueError('SOURCE_VERSION_MISMATCH')
    sessions,grouped=source_data(a.research_root,parent,support)
    extra=json.loads(a.today_input.read_text());extra_day=extra['session_date'];days=old['session_dates']
    coverage=[];evaluated={};a.output.mkdir(parents=True,exist_ok=True)
    for day in days:
        row=dict(session_date=day,status='INCOMPLETE',issues=[])
        try:
            asof=p.dt(day+'T14:55:00+05:30')
            if asof>p.datetime.now(p.IST):raise ValueError('SESSION_NOT_COMPLETE')
            if day==extra_day:raw,warm,_=p.inputs(engine,day,a.today_input,False,a.output)
            else:
                raw=grouped[day];warm=[(d,grouped[d]) for d in sessions if d<day and grouped.get(d)][-30:]
                if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
            raw=[r for r in raw if p.dt(r['timestamp'])<=asof]
            source_hash=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest()
            if source_hash!=old['provenance'][day]['raw_and_warm_sha256']:raise ValueError('INPUT_DIFFERS_FROM_PREVIOUS_BATCH')
            baseline=p.simulate(engine,day,raw,warm,asof,'CURRENT')
            stored={k:json.loads((a.previous_root/'sessions'/day/(k+'.json')).read_text()) for k in previous.POLICIES}
            parity=batch.frozen_parity(stored['ORIGINAL_CURRENT_1M'],baseline);row['parity']=parity
            if parity['status']!='PASS':raise ValueError('BASELINE_PARITY_NOT_PASS')
            Base=fresh_gate(engine);em=exits.ema_frames(engine,day,raw,warm,p.dt);wm=lock.completed_frames(baseline,p.dt)
            indicators={p.dt(r['checkpoint']):r['completed_5m_indicators'] for r in baseline['audit']
                if r.get('nifty_close') is not None and r.get('completed_5m_indicators') and p.dt(r['checkpoint']).minute%5==0}
            Ema=exits.exit_gate(Base,em)
            specs=[(FRESH[0],Base),(FRESH[1],Ema),(FRESH[2],lock.lock_gate(Ema,engine.direction,wm)),
                (FRESH[3],stack.exception_lock_gate(Ema,engine.direction,wm,indicators,lock))]
            result=dict(stored)
            for name,Gate in specs:
                value=p.simulate(SimpleNamespace(WmaGapGate=Gate,replay=engine.replay),day,raw,warm,asof,'CURRENT')
                for t in value['trades']:
                    if t['signal_time']!=t['entry_time'] or p.dt(t['entry_time']).minute%5:raise ValueError('STALE_OR_OFF_BOUNDARY_FRESH_ENTRY')
                batch.signature(value['trades']);value['research_variant']=name;result[name]=value
                dest=a.output/'sessions'/day/(name+'.json');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(value,indent=2,default=str)+'\n')
            row.update(status='COMPLETE',warmup_sessions=len(warm),input_sha256=source_hash);evaluated[day]=result
        except Exception as exc:row['issues'].append(type(exc).__name__+': '+str(exc))
        coverage.append(row);print(json.dumps(row,default=str),flush=True)
        (a.output/'progress.json').write_text(json.dumps(coverage,indent=2,default=str)+'\n')
    policies=tuple(previous.POLICIES)+FRESH
    summary={k:batch.stats([t for d in sorted(evaluated) for t in evaluated[d][k]['trades']]) for k in policies}
    rules='Fresh variants evaluate RSI9>EMA3>WMA21 bullish or RSI9<EMA3<WMA21 bearish at EVERY completed 5m boundary while flat, with directional WMA change>=.75 and positive expanding gap versus previous completed 5m reference. Reference at opening may be the existing validated prior-session opening reference. No pending setup, persistence, watch or episode restriction. Failed or WMA-vetoed attempts are discarded, with independent fresh eligibility next boundary. Canonical signals do not authorize entry. Existing active dual exits and 14:55 cutoff retained; same-boundary exit then entry allowed. EMA variants add close>price EMA10 to dual exit for both directions. Standard post-entry WMA lock retained; exception variant uses RSI9/EMA3>45 for bullish, <55 for bearish. No 40/60 exception.'
    report=dict(status='COMPLETE' if len(evaluated)==len(days) else 'INCOMPLETE',session_dates=days,coverage=coverage,comparisons=summary,rules=rules,
        observation_only=True,orders_sent=False,warning='Gross NIFTY points, not option P&L; costs/fills excluded. Same input hashes and matched baseline as prior batch. Historical frozen reconstruction; latest recorded/API inputs mixed. Repeated alignment entries are a deliberate research change and may increase re-entry frequency. No live changes.',
        source_sha256={str(Path(m.__file__)):hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (stack,exits,lock,engine)},
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (a.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# Fresh five-minute versus retained decisions','',rules,'',report['warning'],'','Status: '+report['status'],f'Coverage: {len(evaluated)}/{len(days)}','',
        '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for k,s in summary.items():lines.append(f"| {k} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','## Daily comparison','','| Date | Existing 1m | Retained + EMA10 + lock | Fresh 5m | Fresh + EMA10 | Fresh + EMA10 + lock | Fresh + exceptions |','|---|---:|---:|---:|---:|---:|---:|']
    selected=('ORIGINAL_CURRENT_1M','RETAINED_5M_EMA10_WMA_LOCK')+FRESH
    for day in sorted(evaluated):lines.append('| '+day+' | '+' | '.join(f"{batch.stats(evaluated[day][k]['trades'])['points']:+.2f}" for k in selected)+' |')
    lines+=['','Incomplete sessions: '+json.dumps([r for r in coverage if r['status']!='COMPLETE'],default=str)]
    detail=['# All trades and fresh-boundary pass/fail audit','',report['warning'],'']
    for day in sorted(evaluated):
        detail+=['','## '+day,'','| Policy | Direction | Setup | Entry | Exit | Points |','|---|---|---|---|---|---:|']
        for k in policies:
            for t in evaluated[day][k]['trades']:detail.append(f"| {k} | {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:+.2f} |")
        detail+=['','### Fresh + EMA10 + WMA lock: boundary checks','','| Decision | Direction | Status | RSI9 | EMA3 | WMA21 | Strength | Gap | Prior gap | Reasons |','|---|---|---|---:|---:|---:|---:|---:|---:|---|']
        for r in evaluated[day][FRESH[2]]['audit']:
            for c in r.get('checks') or []:
                detail.append(f"| {c['decision_timestamp'][11:16]} | {c['direction']} | {c['status']} | {c['current_rsi9']} | {c['current_ema3']} | {c['current_wma21']} | {c['directional_wma_strength']} | {c['current_gap']} | {c['previous_gap']} | {', '.join(c['reasons']) or 'ALL PASSED'} |")
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);(a.output/'trade-and-check-details.md').write_text('\n'.join(detail)+'\n')
    print(text);print('DETAILS:',a.output/'trade-and-check-details.md');print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if report['status']=='COMPLETE' else 2)

if __name__=='__main__':main()
