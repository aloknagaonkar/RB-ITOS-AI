"""Select and arm the tested strategy; no broker/order API calls."""
import argparse,json,os,re,shutil,sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT))
from market_lab.domain import IST
from market_lab.hilega_alignment_dual_exit_live_v1 import STRATEGY_ID
from market_lab.hilega_upstox_sandbox_basket_v2 import (
    BasketStore,JsonControl,CONTROL,JOURNAL,arm,ensure_clear,DEFAULT_SOURCE,
)
from market_lab.hilega_upstox_sandbox_execution_v1 import SandboxConfig
from dotenv import dotenv_values

def validate_warmup(session):
    from datetime import date
    from market_lab.hilega_alignment_dual_exit_live_v1 import cache_index, candles, aggregate_exact_5m, ExitFirstCanonical
    day=date.fromisoformat(session); coordinator=ExitFirstCanonical(); count=0
    for stamp,path in sorted(cache_index().items()):
        if stamp>=day.isoformat():continue
        rows=json.loads(path.read_text()).get("candles") or []
        if not rows:continue
        try:
            bars=aggregate_exact_5m(candles(rows),date.fromisoformat(stamp))
        except ValueError as exc:
            raise ValueError("WARMUP_CACHE_INVALID:"+str(path)+":"+str(exc)) from exc
        for bar in bars:coordinator.on_bar(bar)
        count+=1
    snapshot=coordinator.bullish.previous_indicators
    if not snapshot or not snapshot.ready:raise ValueError("ALIGNMENT_LIVE_LOCAL_WARMUP_NOT_READY")
    print("PASS: historical warmup validated; sessions="+str(count))

def select(session):
    os.chdir(ROOT)
    pidpath=Path('data/hilega-upstox-sandbox-worker.pid')
    if pidpath.exists():
        try:os.kill(int(pidpath.read_text().strip()),0)
        except (ProcessLookupError,ValueError):pass
        else:raise ValueError('Stop the Sandbox worker before switching strategy')
    if os.getenv('LIVE_SHADOW_STRATEGY') and os.getenv('LIVE_SHADOW_STRATEGY')!=STRATEGY_ID:
        raise ValueError('Run: unset LIVE_SHADOW_STRATEGY; an exported value overrides .env')
    env=Path('.env')
    config=SandboxConfig.from_env(env);config.assert_ready('SANDBOX_ONLY')
    ensure_clear(BasketStore(JOURNAL))
    validate_warmup(session)
    oldenv=env.read_bytes()
    oldcontrol=CONTROL.read_bytes() if CONTROL.exists() else None
    values=dotenv_values(env);text=oldenv.decode()
    lines=text.splitlines(keepends=True)
    matches=[i for i,line in enumerate(lines) if re.match(r'^\s*(?:export\s+)?LIVE_SHADOW_STRATEGY\s*=',line)]
    if len(matches)>1:raise ValueError('Duplicate LIVE_SHADOW_STRATEGY assignments; resolve before activation')
    if matches:lines[matches[0]]='LIVE_SHADOW_STRATEGY='+STRATEGY_ID+'\n'
    else:
        if lines and not lines[-1].endswith('\n'):lines[-1]+='\n'
        lines.append('LIVE_SHADOW_STRATEGY='+STRATEGY_ID+'\n')
    updated=''.join(lines)
    stamp=datetime.now(IST).strftime('%Y%m%dT%H%M%S%f')
    backup=Path('data/backups')/('hilega-alignment-activation-'+stamp);backup.mkdir(parents=True)
    (backup/'env.before').write_bytes(oldenv);os.chmod(backup/'env.before',0o600)
    if oldcontrol is not None:(backup/'control.before.json').write_bytes(oldcontrol)
    try:
        env.write_text(updated);os.chmod(env,0o600)
        # Existing arm function checks legacy/open/uncertain exposure and sets a fresh baseline.
        source=Path(os.getenv('HILEGA_SANDBOX_BRIDGE_SOURCE',str(DEFAULT_SOURCE)))
        result=arm(session,source,JsonControl(CONTROL),BasketStore(JOURNAL),env=env)
        after=dotenv_values(env)
        assert {k:v for k,v in values.items() if k!='LIVE_SHADOW_STRATEGY'}=={k:v for k,v in after.items() if k!='LIVE_SHADOW_STRATEGY'}
    except BaseException:
        env.write_bytes(oldenv);os.chmod(env,0o600)
        if oldcontrol is None:CONTROL.unlink(missing_ok=True)
        else:CONTROL.write_bytes(oldcontrol)
        raise
    print(json.dumps({k:result.get(k) for k in (
        'strategy_id','session_date','armed','kill_switch','execution_mode',
        'order_count_limit','sandbox_only','live_execution_enabled')},indent=2))
    print('PASS: strategy selected and Sandbox armed; no broker calls or orders sent')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--session',required=True)
    select(p.parse_args().session)
