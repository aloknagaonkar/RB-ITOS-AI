"""Research: latest combined 40/60 policy, plus independently confirmed opposite reversal.
No broker orders/live changes. Original confirmation checks and entry lock remain mandatory.
"""
import copy
import hashlib
import inspect
import json
import linecache
from pathlib import Path
from types import SimpleNamespace
from datetime import timedelta
import unittest

MODEL='EXISTING_EMA10_WMA_EXCEPTION_40_60_OPPOSITE_OVERRIDE_V1'
OLD_ROOT=Path('data/research/hilega-existing-ema10-wma-exception-40-60-last10-20261016')
NEW_ROOT=Path('data/research/hilega-opposite-confirmation-override-last10-20261016')

def reversal_gate(Parent,direction,make_exit,original_close):
    class Reversal(Parent):
        def can_monitor(self,side):return self.owner=='NONE' or side!=self.owner
        def signal(self,event,available):
            if not self.can_monitor(direction(event)):return
            owner=self.owner;self.owner='NONE'
            try:return super().signal(event,available)
            finally:self.owner=owner
        def observe_arms(self,events,available):
            if self.owner!='NONE':
                events=[e for e in events if not str(e.event_type).startswith('ENTRY_') or direction(e)!=self.owner]
            owner=self.owner;self.owner='NONE'
            try:return super().observe_arms(events,available)
            finally:self.owner=owner
        def evaluate(self,**kwargs):
            self._override_closes=[]
            owner=self.owner;active=copy.deepcopy(self.active)
            if owner=='NONE':return super().evaluate(**kwargs)
            # Only the opposite side may qualify while a real position exists.
            self.pending.pop(owner,None)
            self.owner='NONE';self.active=None
            try:entries,checks=super().evaluate(**kwargs)
            except Exception:
                self.owner=owner;self.active=active;raise
            if not entries:
                self.owner=owner;self.active=active
                return entries,checks
            if len(entries)!=1 or direction(entries[0])==owner:raise ValueError('OPPOSITE_ONLY_ONE_ENTRY_REQUIRED')
            at=kwargs['minute']+timedelta(minutes=1);price=kwargs['price']
            new_owner=self.owner;new_active=self.active
            self.owner=owner;self.active=active
            # Explicit override bypasses EMA validation, preserving original
            # exit accounting and clearing old-position state before new entry.
            closed=original_close(self,make_exit(owner,at),at,price)
            if closed is None:raise ValueError('OPPOSITE_OVERRIDE_CLOSE_FAILED')
            self.owner=new_owner;self.active=new_active
            self._override_closes=[closed]
            self.policy_events.append(dict(event='CONFIRMED_OPPOSITE_EXIT_OVERRIDE',time=at.isoformat(),
                old_direction=owner,new_direction=new_owner,price=price,closed_points=closed.points,
                original_entry_time=active['time'].isoformat(),ema_validation_bypassed=True,
                entry_lock_and_exception_required=True,entry_check=checks))
            return entries,checks
    return Reversal

def combined_gate(engine,frames,wm,lock,corrected,threshold):
    import hilega_existing_ema10_wma_exception_40_60_last10_research as current
    Parent=current.combined_gate(engine,frames,wm,lock,corrected,threshold)
    def make_exit(side,at):
        return engine.StrategyEvent('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21' if side=='BULLISH' else 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21',
            at,'CONFIRMED_OPPOSITE_OVERRIDE','ACTIVE','IDLE',exit_reason='FULL_OPPOSITE_ENTRY_CONFIRMED_EMA10_OVERRIDE')
    return reversal_gate(Parent,engine.direction,make_exit,engine.WmaGapGate.close)

def opposite_replay(engine):
    source=inspect.getsource(engine.replay)
    changes={
        "if e.event_type in ENTRY_TYPES and g.owner=='NONE' and direction(e) not in g.pending:":
            "if e.event_type in ENTRY_TYPES and g.can_monitor(direction(e)) and direction(e) not in g.pending:",
        "and not episode[side] and g.owner=='NONE' and side not in g.pending":
            "and not episode[side] and g.can_monitor(side) and side not in g.pending",
        "exit_boundary=bool(events));checks.extend(cc)":
            "exit_boundary=bool(events));events.extend(getattr(g,'_override_closes',[]));checks.extend(cc)",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('REPLAY_SOURCE_DIFFERS:'+old)
        source=source.replace(old,new,1)
    name='<opposite-confirmation-'+hashlib.sha256(source.encode()).hexdigest()[:16]+'>'
    linecache.cache[name]=(len(source),None,source.splitlines(True),name)
    namespace=dict(engine.replay.__globals__);exec(compile(source,name,'exec'),namespace)
    return namespace['replay']

class Checks(unittest.TestCase):
    def harness(self,accepted=True):
        from datetime import datetime
        at=datetime.fromisoformat('2026-10-05T10:03:00+05:30')
        class Base:
            def __init__(self):
                self.owner='BULLISH';self.active={'time':at-timedelta(minutes=35),'price':100}
                self.pending={'BEARISH':{}};self.policy_events=[]
            def evaluate(self,**kwargs):
                if not accepted:return [],[dict(status='WAIT')]
                self.owner='BEARISH';self.active={'time':at,'price':98};self.pending.clear()
                return ['BEARISH'],[dict(status='ENTRY')]
            def signal(self,event,available):self.pending[event]={}
            def observe_arms(self,events,available):pass
        def close(g,event,at,price):
            result=SimpleNamespace(points=price-g.active['price']);g.owner='NONE';g.active=None;return result
        Gate=reversal_gate(Base,lambda e:e,lambda side,at:side,close)
        return Gate(),at
    def test_full_opposite_closes_before_replacement(self):
        g,t=self.harness();entries,_=g.evaluate(minute=t-timedelta(minutes=1),price=98)
        self.assertEqual(entries,['BEARISH']);self.assertEqual(g.owner,'BEARISH')
        self.assertEqual(g._override_closes[0].points,-2)
    def test_failed_opposite_keeps_active_position(self):
        g,t=self.harness(False);entries,_=g.evaluate(minute=t-timedelta(minutes=1),price=98)
        self.assertFalse(entries);self.assertEqual(g.owner,'BULLISH');self.assertEqual(g.active['price'],100)
        self.assertFalse(g._override_closes)
    def test_same_side_setup_ignored(self):
        g,t=self.harness();g.signal('BULLISH',t);self.assertNotIn('BULLISH',g.pending)
    def test_opposite_setup_alone_does_not_exit(self):
        g,t=self.harness();g.signal('BEARISH',t);self.assertEqual(g.owner,'BULLISH');self.assertEqual(g.active['price'],100)
    def test_monitor_does_not_allow_same_side(self):
        g,_=self.harness();self.assertTrue(g.can_monitor('BEARISH'));self.assertFalse(g.can_monitor('BULLISH'))

def compare(output):
    import hilega_pending_previous10_research as stats
    import hilega_existing_ema10_wma_combined_last10_research as base
    report=json.loads((output/'report.json').read_text());prior=json.loads((OLD_ROOT/'report.json').read_text())
    if report['status']!='COMPLETE':return
    if prior['status']!='COMPLETE' or prior['model']!='EXISTING_1M_DIRECTIONAL_EMA10_THRESHOLD_WMA_RSI_EXCEPTION_40_60_V3':raise ValueError('PREVIOUS_40_60_COMPLETE_REPORT_REQUIRED')
    labels=('Existing strategy','Combined 40/60','Combined + opposite override')
    totals={label:[] for label in labels}
    lines=['# Opposite-confirmation override comparison','','Gross NIFTY points, no fills/costs. Reversals use independently replayed current checks, not baseline entry times. WMA/40-60 exception still required.','',
        '| Date | Existing points | Combined 40/60 | + opposite override | Change vs combined |','|---|---:|---:|---:|---:|']
    details=['# Signal details — opposite confirmation override','','Times IST. Dash means no executed entry from that exact setup.','']
    for day in report['session_dates']:
        old=json.loads((OLD_ROOT/'sessions'/(day+'.json')).read_text());new=json.loads((output/'sessions'/(day+'.json')).read_text())
        if prior['provenance'][day]['input_sha256']!=report['provenance'][day]['input_sha256']:raise ValueError('PRIOR_INPUT_HASH_MISMATCH')
        if stats.frozen_parity(old['EXISTING'],new['EXISTING'])['status']!='PASS':raise ValueError('EXISTING_PARITY_MISMATCH')
        variants=(new['EXISTING'],old['COMBINED'],new['COMBINED']);points=[stats.stats(r['trades'])['points'] for r in variants]
        lines.append(f'| {day} | {points[0]:+.2f} | {points[1]:+.2f} | {points[2]:+.2f} | {points[2]-points[1]:+.2f} |')
        for label,r in zip(labels,variants):totals[label].extend(r['trades'])
        details+=['','## '+day,'','| Direction | Setup available | '+' | '.join(labels)+' |','|---|---|---|---|---|']
        identities=sorted({(t['direction'],t['signal_time']) for r in variants for t in r['trades']},key=lambda x:(x[1],x[0]))
        for side,signal in identities:
            cells=[base.cell([t for t in r['trades'] if (t['direction'],t['signal_time'])==(side,signal)]) for r in variants]
            details.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' |')
        details+=['','### Confirmed opposite exits','','| Time | Old side | New side | Exit/entry NIFTY | Closed trade points |','|---|---|---|---:|---:|']
        for e in new['COMBINED']['policy_events']:
            if e['event']=='CONFIRMED_OPPOSITE_EXIT_OVERRIDE':details.append(f"| {e['time'][11:16]} | {e['old_direction']} | {e['new_direction']} | {e['price']:.2f} | {e['closed_points']:+.2f} |")
    report['comparison_with_previous']={key:stats.stats(value) for key,value in totals.items()}
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines+=['','| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for key,s in report['comparison_with_previous'].items():lines.append(f"| {key} | {s['trades']} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    (output/'override-comparison.md').write_text('\n'.join(lines+details)+'\n');print('\n'.join(lines+details))

def main():
    import hilega_existing_ema10_wma_combined_last10_research as base
    import hilega_existing_ema10_wma_exception_40_60_last10_research as exception
    source=inspect.getsource(base.main)
    changes={
        'data/research/hilega-existing-ema10-wma-combined-last10-20261016':str(NEW_ROOT),
        'Checks,corrected.Checks,threshold.Checks':'Checks,base.Checks,exception.Checks,corrected.Checks,threshold.Checks',
        'replay=engine.replay),day,raw,warm,asof,\'CURRENT\')':'replay=opposite_replay(engine)),day,raw,warm,asof,\'CURRENT\')',
        'no unlimited retention, no RSI/EMA exception.':'no unlimited retention. RSI/EMA exception: bullish both>40, bearish both<60, completed 5m inputs. Independently evaluate opposite setups while active; fully passing opposite entry including lock/exception closes old position immediately without EMA10 veto and opens opposite. No setup-only reversal; existing cutoff remains.',
        'wm=lock.completed_frames(baseline,p.dt);first=min(wm)':
            "wm=lock.completed_frames(baseline,p.dt)\n            for audit_row in baseline['audit']:\n                boundary=p.dt(audit_row['checkpoint'])\n                if boundary in wm and audit_row.get('completed_5m_indicators') and audit_row.get('nifty_close') is not None:\n                    wm[boundary].update(rsi9=audit_row['completed_5m_indicators']['rsi9'],ema3=audit_row['completed_5m_indicators']['ema3'])\n            first=min(wm)",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('BASE_RUNNER_SOURCE_DIFFERS:'+old)
        source=source.replace(old,new,1)
    namespace=dict(vars(base));namespace.update(base=base,exception=exception,MODEL=MODEL,Checks=Checks,
        combined_gate=combined_gate,opposite_replay=opposite_replay)
    exec(compile(source,'<opposite-override-batch>','exec'),namespace)
    import sys
    try:namespace['main']()
    except SystemExit as exc:
        if exc.code not in (0,None) or '--test' in sys.argv:raise
    output=NEW_ROOT
    for i,arg in enumerate(sys.argv):
        if arg=='--output':output=Path(sys.argv[i+1])
        elif arg.startswith('--output='):output=Path(arg.split('=',1)[1])
    compare(output)

if __name__=='__main__':main()
