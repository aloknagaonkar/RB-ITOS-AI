"""Offline VM parity gate. Reads frozen research/candles; no services or orders."""
import argparse
import hashlib
import inspect
from copy import deepcopy
from datetime import datetime,date,time,timedelta
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

def signature(trades):
    return [(t['direction'],t['signal_time'],t['entry_time'],t['exit_time'],round(t['entry_price'],5),round(t['exit_price'],5),round(t['points'],5),t['exit_reason']) for t in trades]

def live_signature(day,raw,warm):
    from market_lab import hilega_v2_alignment_replay_v1 as old
    from market_lab.hilega_combined_policy_v1 import PriceFrames,make_gate
    from market_lab.hilega_alignment_dual_exit_live_v1 import HilegaAlignmentDualExitLiveCoordinator as Live
    from market_lab.hilega_opening_reference_v1 import capture_opening_reference
    c=old.ExitFirstCanonical();tracker=PriceFrames()
    for d,rows in sorted(warm):
        for bar in old.aggregate_exact_5m(old.candles(rows),date.fromisoformat(d)):
            c.on_bar(bar);tracker.seed(bar)
    opening=capture_opening_reference(c,date.fromisoformat(day))
    c.bullish.session=old.SessionState(session_date=date.fromisoformat(day))
    c.bearish.session=old.BearishSessionState(session_date=date.fromisoformat(day))
    for eng in (c.bullish,c.bearish):eng.previous_indicators=None;eng.previous_bar=None
    c.trade_owner='NONE';c.session_date=date.fromisoformat(day)
    live=Live.__new__(Live)
    live.canonical=c;live.price_frames=tracker;live.gate=make_gate(tracker.frames)
    live._opening_reference=opening;live.episode={'BULLISH':False,'BEARISH':False}
    live.warning_time=None;live._manual_exit_seen=set();live._last_bar_ts=None;live._last_minute=None;live._cutoff_done_date=None
    records=[]
    live._audit=lambda at,stage,status,payload,**kw:records.append(dict(stage=stage,payload=payload))
    live._directional_decision_payload=lambda bar,decision:{}
    def decision(at,before,events,note):live._sync_view();return events
    live._decision=decision
    shadow_entries=[];shadow_exits=[]
    live._start_option=lambda **kw:shadow_entries.append((kw['direction'],kw['event'].entry_time.isoformat(),round(kw['event'].entry_price,5)))
    live._close_option=lambda **kw:shadow_exits.append((kw['direction'],kw['exit_boundary'].isoformat(),kw['exit_reason']))
    rows=old.candles(raw);selected=[r for r in rows if r.timestamp.date().isoformat()==day and '09:15'<=r.timestamp.strftime('%H:%M')<'14:55']
    bars={b.ts:b for b in old.aggregate_exact_5m(selected,date.fromisoformat(day),require_full_session=False)}
    with tempfile.TemporaryDirectory() as temp:
        live.manual_exit_root=Path(temp)
        (Path(temp)/'manual-exit.json').write_text('{"requests":[]}')
        for minute in selected:live._advance(minute,bars,recovered=False)
        live.process_cutoff(datetime.fromisoformat(day+'T14:55:00+05:30'),intraday=rows)
    entries=[];exits=[]
    for r in records:
        for e in r['payload'].get('event_details',[]):
            if e.get('exit_reason'):exits.append(e)
            elif e.get('entry_time'):entries.append(e)
    expected_shadow_entries=sorted(('BEARISH' if 'BEARISH' in e['event_type'] else 'BULLISH',e['entry_time'],round(e['entry_price'],5)) for e in entries)
    if sorted(shadow_entries)!=expected_shadow_entries:raise ValueError('SHADOW_ENTRY_DISPATCH_MISMATCH:'+day)
    expected_shadow_exits=sorted(('BEARISH' if 'BEARISH' in e['event_type'] else 'BULLISH',e['event_time'],e['exit_reason']) for e in exits)
    if sorted(shadow_exits)!=expected_shadow_exits:raise ValueError('SHADOW_EXIT_DISPATCH_MISMATCH:'+day)
    return sorted((e['entry_time'],round(e['entry_price'],5),round(e['price'],5),round(e['points'],5),e['exit_reason']) for e in exits),sorted((e['entry_time'],round(e['entry_price'],5)) for e in entries)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference-root',type=Path,default=Path('data/research/hilega-bearish-ema30-oct-through16'))
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--date',action='append')
    ap.add_argument('--apply-recorded-overrides',action='store_true',help='Merge original recorded minute OHLC and cutoff, for the Oct16 mixed-input control')
    ap.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    ap.add_argument('--session-input',type=Path,help='For one explicit recorded session, e.g. Oct16. Warmup uses all local prior caches.')
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-combined-promotion-parity'))
    args=ap.parse_args();os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    from market_lab import hilega_v2_alignment_replay_v1 as legacy
    from market_lab import hilega_combined_replay_v1 as promoted
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    reference=json.loads((args.reference_root/'report.json').read_text())
    if reference.get('status')!='COMPLETE':raise ValueError('COMPLETE_FROZEN_REFERENCE_REQUIRED')
    if args.session_input and (not args.date or len(args.date)!=1):raise ValueError('SESSION_INPUT_REQUIRES_ONE_DATE')
    days=args.date or [d for d in reference['session_dates'] if d<'2026-10-16']
    parent=json.loads((args.research_root/'3-month/report.json').read_text())
    calendar,grouped=source_data(args.research_root,parent,support)
    args.output.mkdir(parents=True,exist_ok=True);proof=[]
    for day in days:
        frozen=json.loads((args.reference_root/'sessions'/(day+'.json')).read_text())
        if args.session_input:
            raw=json.loads(args.session_input.read_text())['candles'];warm=[]
            for d,path in sorted(legacy.cache_index().items()):
                if d<day:warm.append((d,json.loads(path.read_text())['candles']))
        else:
            raw=grouped[day];warm=[(d,grouped[d]) for d in calendar if d<day and grouped.get(d)][-30:]
        if args.apply_recorded_overrides:
            from hilega_pending_previous10_research import recorded_overrides
            raw,_=recorded_overrides(raw,args.audit,day,datetime.fromisoformat)
        if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
        baseline=legacy.replay(day,raw,warm)
        if signature(baseline['trades'])!=signature(frozen['EXISTING']['trades']):raise ValueError('FROZEN_INPUT_BASELINE_MISMATCH:'+day)
        result=promoted.replay(day,raw,warm)
        if signature(result['trades'])!=signature(frozen['BULLISH_GAP2_FULL_WMA2']['trades']):raise ValueError('PROMOTED_RESEARCH_TRADE_MISMATCH:'+day)
        actual_exits,actual_entries=live_signature(day,raw,warm)
        expected_exits=sorted((t['entry_time'],round(t['entry_price'],5),round(t['exit_price'],5),round(t['points'],5),t['exit_reason']) for t in result['trades'])
        expected_entries=sorted((t['entry_time'],round(t['entry_price'],5)) for t in result['trades'])
        if actual_exits!=expected_exits or actual_entries!=expected_entries:raise ValueError('LIVE_REPLAY_EVENT_PARITY_MISMATCH:'+day)
        row=dict(session_date=day,status='PASS',trades=len(result['trades']),points=round(sum(t['points'] for t in result['trades']),5),research_trade_parity='PASS',live_replay_event_parity='PASS',shadow_event_dispatch_parity='PASS',warmup_sessions=len(warm))
        proof.append(row);print(json.dumps(row),flush=True)
        (args.output/(day+'.json')).write_text(json.dumps(result,indent=2))
        (args.output/'validation.json').write_text(json.dumps(dict(status='PASS',policy_id=promoted.POLICY_ID,strategy_version=promoted.VERSION,sessions=proof,implementation_sha256={
            'backend/market_lab/hilega_combined_policy_v1.py':hashlib.sha256(Path(inspect.getfile(__import__('market_lab.hilega_combined_policy_v1',fromlist=['VERSION']))).read_bytes()).hexdigest(),
            'backend/market_lab/hilega_combined_replay_v1.py':hashlib.sha256(Path(inspect.getfile(promoted)).read_bytes()).hexdigest(),
            'backend/market_lab/hilega_alignment_dual_exit_live_v1.py':hashlib.sha256(Path(inspect.getfile(__import__('market_lab.hilega_alignment_dual_exit_live_v1',fromlist=['VERSION']))).read_bytes()).hexdigest()},orders_sent=False),indent=2))
    print('PARITY REPORT:',args.output/'validation.json')

if __name__=='__main__':main()
