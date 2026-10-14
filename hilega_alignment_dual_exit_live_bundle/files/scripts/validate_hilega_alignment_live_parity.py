"""Offline validation of live adapter against historical replay; no broker access."""
import argparse, hashlib, json, tempfile
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from market_lab import hilega_v2_alignment_replay_v1 as historical
from market_lab import hilega_alignment_dual_exit_live_v1 as live
from market_lab.domain import IST

def verify(day, roots=None):
    index=historical.cache_index(roots)
    if day not in index:raise ValueError('TARGET_LOCAL_CACHE_MISSING:'+day)
    raw=json.loads(index[day].read_text()).get('candles') or []
    warm=[]
    for d,p in sorted(index.items()):
        if d>=day:continue
        rows=json.loads(p.read_text()).get('candles') or []
        if rows:warm.append((d,rows))
    baseline=historical.replay(day,raw,warm)
    minutes=historical.candles(raw);rows=[];trades=[];active=None;calls=[]
    def audit(at,stage,status,payload,**kwargs):
        if stage=='DIRECTIONAL_DECISION':rows.append(dict(stage=stage,payload=payload))
        for event in payload.get('event_details') or []:
            if event['event_type'] not in historical.ENTRY_TYPES|historical.EXIT_TYPES:continue
            nonlocal active
            if event['event_type'] in historical.EXIT_TYPES:
                if active is None:raise AssertionError('EXIT_WITHOUT_ENTRY')
                trades.append(dict(active,exit_time=payload['decision_timestamp'],
                    exit_price=event['price'],points=event['points'],exit_reason=event['exit_reason']))
                active=None
            else:
                if active is not None:raise AssertionError('ENTRY_BEFORE_EXIT')
                active=dict(direction='BEARISH' if event['event_type'] in historical.BEARISH_ENTRY_EVENTS else 'BULLISH',
                    entry_time=event['entry_time'],entry_price=event['entry_price'])
    with tempfile.TemporaryDirectory() as folder:
        source=SimpleNamespace(nifty_intraday_1m=lambda **kw:[])
        c=live.HilegaAlignmentDualExitLiveCoordinator(market_sources=source,option_expiry=None,
            step_audit_path=Path(folder)/'audit',health_path=Path(folder)/'health')
        c._audit=audit
        c._restore_audited_option_state=lambda **kw:{}
        c._start_option=lambda **kw:calls.append(('ENTRY',kw['now'].isoformat()))
        c._close_option=lambda **kw:calls.append(('EXIT',kw['exit_boundary'].isoformat()))
        with patch.object(live,'cache_index',return_value=index):
            c.bootstrap(datetime.combine(date.fromisoformat(day),time(9,15),tzinfo=IST))
        c._consume(minutes,datetime.combine(date.fromisoformat(day),time(14,55),tzinfo=IST),recovered=False)
        c.process_cutoff(datetime.combine(date.fromisoformat(day),time(14,55),tzinfo=IST),intraday=minutes)
        before=len(rows)
        c._consume(minutes,datetime.combine(date.fromisoformat(day),time(15),tzinfo=IST),recovered=False)
        assert len(rows)==before,'DUPLICATE_MINUTE_REPLAY'
    keys=('direction','entry_time','entry_price','exit_time','exit_price','points','exit_reason')
    expected=[{k:t[k] for k in keys} for t in baseline['trades']]
    assert trades==expected,('TRADE_PARITY_MISMATCH',expected,trades)
    live_checks=[check for r in rows for check in r['payload'].get('wma_gap_checks') or []]
    assert live_checks==baseline['checks'],'MINUTE_GATE_PARITY_MISMATCH'
    setups=[setup for r in rows for setup in r['payload'].get('setup_attempts') or []]
    assert setups==baseline['setup_attempts'],'SETUP_PARITY_MISMATCH'
    assert len(calls)==2*len(trades),'OPTION_LIFECYCLE_COUNT_MISMATCH'
    assert [kind for kind,_ in calls]==['ENTRY','EXIT']*len(trades),'OPTION_EXIT_ENTRY_ORDER_MISMATCH'
    return dict(session_date=day,status='PASS',entries=len(trades),net_points=round(sum(t['points'] for t in trades),2),
        minute_checks=len(live_checks),setups=len(setups),warmup_sessions=len(warm),
        target_sha256=hashlib.sha256(index[day].read_bytes()).hexdigest(),broker_called=False)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--dates',nargs='+',required=True)
    p.add_argument('--cache-root',action='append',type=Path)
    a=p.parse_args()
    for day in a.dates:print(json.dumps(verify(date.fromisoformat(day).isoformat(),a.cache_root)),flush=True)
if __name__=='__main__':main()
