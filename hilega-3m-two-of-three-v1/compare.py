"""Offline saved-candle comparison; broker/network calls are not used."""
import argparse
from datetime import datetime,date,time,timedelta
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as Obj
from unittest.mock import patch

HERE=Path(__file__).resolve().parent

def stats(result):
    trades=result['trades'];points=[float(t['points']) for t in trades]
    equity=0.;peak=0.;drawdown=0.
    for p in points:
        equity+=p;peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    return dict(trades=len(points),winners=sum(p>0 for p in points),losers=sum(p<0 for p in points),
        points=round(sum(points),4),worst_trade=round(min(points,default=0),4),closed_trade_drawdown=round(drawdown,4),
        total_giveback=round(sum(t.get('giveback_points',0) for t in trades),4),
        entries_after_1455=sum(t['entry_time'][11:16]>'14:55' for t in trades),
        last_exit=max((t['exit_time'] for t in trades),default=None))

def live_parity(day,raw,warm,replay):
    from market_lab.hilega_three_minute_v1 import hilega_alignment_dual_exit_live_v1 as module
    from market_lab.hilega_three_minute_v1.hilega_milega_strategy_v1 import SessionState
    from market_lab.hilega_three_minute_v1.hilega_milega_bearish_strategy_v1 import BearishSessionState
    from market_lab.hilega_three_minute_v1.session import aggregate_exact_3m
    from market_lab.domain import IST
    with tempfile.TemporaryDirectory(prefix='hilega-3m-parity-') as folder:
        live=module.HilegaAlignmentDualExitLiveCoordinator(market_sources=Obj(),option_expiry=None,
            step_audit_path=Path(folder)/'audit.jsonl',health_path=Path(folder)/'health.jsonl')
        captured=[];callbacks=[]
        live._audit=lambda now,stage,status,payload,**kw:captured.append((stage,payload))
        live._health=lambda *args,**kw:None
        live._start_option=lambda **kw:callbacks.append(('ENTRY',kw['direction'],kw['now'].isoformat()))
        live._close_option=lambda **kw:callbacks.append(('EXIT',kw['direction'],kw['exit_boundary'].isoformat()))
        for d,rows in warm:
            for bar in aggregate_exact_3m(module.candles(rows),date.fromisoformat(d)):
                live.canonical.on_bar(bar);live.price_frames.seed(bar)
        live._opening_reference=module.capture_opening_reference(live.canonical,date.fromisoformat(day))
        live.canonical.bullish.session=SessionState(session_date=date.fromisoformat(day))
        live.canonical.bearish.session=BearishSessionState(session_date=date.fromisoformat(day))
        for engine in (live.canonical.bullish,live.canonical.bearish):engine.previous_indicators=None;engine.previous_bar=None
        live.canonical.trade_owner='NONE';live.canonical.session_date=date.fromisoformat(day)
        live._sync_view()
        end=datetime.combine(date.fromisoformat(day),time(15,30),tzinfo=IST)
        rows=module.candles(raw)
        with patch('market_lab.hilega_manual_exit_strategy_v1.apply_manual_control',return_value=False):
            live._consume(rows,end,recovered=False)
            live.process_cutoff(end,intraday=rows)
        actual=[]
        for stage,payload in captured:
            if stage not in ('DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF'):continue
            for e in payload.get('event_details',[]):
                kind='ENTRY' if e['event_type'] in module.ENTRY_TYPES else 'EXIT'
                side='BEARISH' if 'BEARISH' in e['event_type'] else 'BULLISH'
                actual.append((kind,side,e['event_time'],e['price']))
        expected=[]
        for audit in replay['audit']:
            for transition in audit.get('transitions',[]):
                expected.append(('ENTRY' if transition['event']=='ENTRY_ACTIVE' else 'EXIT',transition['direction'],audit['checkpoint'],transition['price']))
        if actual!=expected:raise ValueError('LIVE_REPLAY_EVENT_MISMATCH:'+json.dumps(dict(expected=expected,actual=actual)))
        if callbacks!=[e[:3] for e in expected]:raise ValueError('EXIT_FIRST_CALLBACK_PARITY_FAILED')
        if live.gate.owner!='NONE' or not live.gate.locked or live.gate.pending:raise ValueError('SESSION_NOT_FLAT_OR_LOCKED')
        return dict(live_replay_event_parity='PASS',shadow_callback_parity='PASS',session_closed=True,events=len(actual))

def worker(args):
    data=json.loads(args.input.read_text());day=data['session_date'];warm=[(x[0],x[1]) for x in data['warmup']]
    if args.variant=='current_5m_3of3':
        from market_lab import hilega_combined_replay_v1 as engine
    else:
        from market_lab.hilega_three_minute_v1 import hilega_combined_replay_v1 as engine
        from market_lab.hilega_three_minute_v1 import session, hilega_combined_policy_v1 as policy
        if args.variant=='candidate_3m_3of3':
            session.MIN_PASSES=3
            policy.RULES['strength_gap_min_passes']=3
    result=engine.replay(day,data['candles'],warm)
    parity=live_parity(day,data['candles'],warm,result) if args.variant!='current_5m_3of3' else {}
    bypassed=[]
    for audit in result['audit']:
        for check in audit.get('checks',[]):
            if check.get('status')=='ENTRY':
                bypassed.append(dict(time=check['decision_timestamp'],direction=check['direction'],
                    pass_count=check.get('strength_gap_pass_count'),
                    failed_conditions=[k for k in ('gap_positive_pass','wma_threshold_pass','gap_expanding_pass') if check.get(k) is False],
                    confirmation_route=(check.get('ema10_entry') or {}).get('entry_confirmation_route')))
    out=dict(session_date=day,variant=args.variant,strategy_version=engine.VERSION,
        summary=stats(result),trades=result['trades'],entry_conditions=bypassed,**parity)
    args.output.write_text(json.dumps(out,indent=2,default=str)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--stage',type=Path)
    p.add_argument('--days',nargs='+');p.add_argument('--out',type=Path)
    p.add_argument('--variant',choices=['current_5m_3of3','candidate_3m_3of3','candidate_3m_2of3'])
    p.add_argument('--input',type=Path);p.add_argument('--output',type=Path)
    args=p.parse_args()
    if args.variant:worker(args);return
    if not args.stage or not args.days or not args.out:p.error('--stage, --days and --out required')
    repo=args.repo.resolve();stage=args.stage.resolve();out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    roots=[repo/'data/historical-evidence/hilega-milega-underlying-cache-v1',
        repo/'data/recovery/october-2026/replay-input/replay-warmup',repo/'data/recovery/october-2026/nifty-cache']
    index={}
    for root in roots:
        for path in sorted(root.glob('????-??-??.json')):index[path.stem]=path
    results=[]
    for day in args.days:
        date.fromisoformat(day)
        if day not in index:raise ValueError('TARGET_CANDLES_MISSING:'+day)
        target=json.loads(index[day].read_text())
        warm=[];hashes={day:hashlib.sha256(index[day].read_bytes()).hexdigest()}
        for d,path in sorted(index.items()):
            if d>=day:continue
            item=json.loads(path.read_text())
            if item.get('candles'):
                warm.append((d,item['candles']));hashes[d]=hashlib.sha256(path.read_bytes()).hexdigest()
        if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED:'+day)
        path=out/(day+'-input.json');path.write_text(json.dumps(dict(session_date=day,candles=target['candles'],warmup=warm)))
        for variant in ('current_5m_3of3','candidate_3m_3of3','candidate_3m_2of3'):
            dest=out/(day+'-'+variant+'.json')
            env=dict(os.environ,PYTHONPATH=str((repo if variant=='current_5m_3of3' else stage)/'backend'),PYTHONDONTWRITEBYTECODE='1')
            subprocess.run([sys.executable,str(HERE/'compare.py'),'--variant',variant,'--input',str(path),'--output',str(dest)],cwd=repo,env=env,check=True)
            result=json.loads(dest.read_text());results.append(dict(session_date=day,variant=variant,summary=result['summary'],
                live_replay_event_parity=result.get('live_replay_event_parity'),shadow_callback_parity=result.get('shadow_callback_parity')))
        (out/(day+'-input-sha256.json')).write_text(json.dumps(hashes,indent=2)+'\n')
        path.unlink()
    report=dict(status='PASS',scope='OFFLINE_SAVED_CANDLES',results=results,
        note='3m controls both use 15:30 session close; current 5m retains 14:55. Differences include timeframe and session duration.',
        broker_execution_validated=False,fees_and_slippage_included=False)
    (out/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
