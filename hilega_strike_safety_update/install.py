"""Guarded installer. Run from the VM repository root, never starts services."""
import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def guard_stopped_and_flat(root):
    pid_path=root/'data/hilega-upstox-sandbox-worker.pid'
    if pid_path.exists():
        pid=int(pid_path.read_text().strip())
        try:os.kill(pid,0)
        except ProcessLookupError:pass
        else:raise RuntimeError('STOP_SANDBOX_WORKER_BEFORE_INSTALL')
    journal=root/'data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl'
    rows=[json.loads(line) for line in journal.read_text().splitlines() if line.strip()] if journal.exists() else []
    accepted=[r for r in rows if r.get('status')=='ACCEPTED']
    opened={}
    for r in accepted:
        key=(r['trade_id'],r['role'])
        if r['event_type']=='ENTRY':opened[key]=r
        else:opened.pop(key,None)
    done={r.get('request_id') for r in rows if r.get('status') in {'ACCEPTED','REQUEST_RESOLVED_NO_FILL'}}
    if opened or any(r.get('status')=='REQUESTED' and r.get('request_id') not in done for r in rows):
        raise RuntimeError('OPEN_OR_UNCERTAIN_LEGS_RECONCILE_BEFORE_INSTALL')
    ev={r['request_id']:r['evidence'] for r in rows if r.get('status')=='ORDER_FILL_VERIFIED'}
    manual={(r['trade_id'],r['role']) for r in accepted if r.get('manual_exit_confirmed')}
    aware=[r for r in accepted if r.get('automatic_fill_ledger_version') and not r.get('manual_exit_confirmed')]
    for r in aware:
        key=(r['trade_id'],r['role'])
        if key in manual:continue
        if not ev.get(r['request_id'],{}).get('terminal'):
            raise RuntimeError('PENDING_FILL_ORDER_RECONCILE_BEFORE_INSTALL')
        if r['event_type']=='ENTRY':
            sold=sum(ev.get(s['request_id'],{}).get('filled',0) for s in aware if s['event_type']=='EXIT' and (s['trade_id'],s['role'])==key)
            if sold!=ev[r['request_id']]['filled']:
                raise RuntimeError('CONFIRMED_POSITION_NOT_FLAT')
    control=root/'data/live-observation/hilega-upstox-sandbox-v2/control.json'
    if control.exists():
        c=json.loads(control.read_text())
        if c.get('entries_blocked'):
            raise RuntimeError('EXISTING_SAFETY_BLOCK_REQUIRES_REVIEW')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check',action='store_true')
    args=p.parse_args();root=Path.cwd()
    if not (root/'backend/market_lab').is_dir():p.error('Run from repository root')
    manifest=json.loads((HERE/'manifest.json').read_text())
    errors=[]
    for row in manifest:
        incoming=HERE/'files'/row['path']
        if digest(incoming)!=row['after']:errors.append('PACKAGE_HASH_MISMATCH:'+row['path'])
        if digest(root/row['path']) not in {row['before'],row['after']}:
            errors.append('SOURCE_HASH_MISMATCH:'+row['path'])
    if errors:raise SystemExit(json.dumps(dict(status='BLOCKED',errors=errors)))
    print(json.dumps(dict(status='VALIDATED',files=[r['path'] for r in manifest],tests_run=False)))
    if args.check:return
    guard_stopped_and_flat(root)
    backup=root/'backups'/('strike-safety-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    created=[]
    for row in manifest:
        target=root/row['path']
        if digest(target)==row['after']:continue
        if target.exists():
            old=backup/row['path'];old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,old)
        else:created.append(row['path'])
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+'.strike-safety.tmp')
        shutil.copy2(HERE/'files'/row['path'],temporary);os.replace(temporary,target)
    (backup/'created-files.json').write_text(json.dumps(created,indent=2))
    print(json.dumps(dict(status='APPLIED',backup=str(backup),activation_changed=False,tests_run=False)))

if __name__=='__main__':main()
