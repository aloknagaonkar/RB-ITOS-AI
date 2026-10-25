"""Stage or install the reviewed combined strategy. Does not start services/orders."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

HERE=Path(__file__).resolve().parent
VERSION='bullish-gap2-full-wma2-1.0.0'
POLICY='BULLISH_GAP2_FULL_WMA2'
REQUIRED_DAYS={'2026-10-01','2026-10-05','2026-10-06','2026-10-07','2026-10-08','2026-10-09','2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'}

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def stopped(root):
    markers=('live_shadow_worker','hilega_upstox_sandbox','hilega_policy_live/publisher','uvicorn')
    for proc in Path('/proc').glob('[0-9]*'):
        if proc.name==str(os.getpid()):continue
        try:
            if (proc/'cwd').resolve()!=root:continue
            command=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
        except (OSError,RuntimeError):continue
        if any(m in command for m in markers):raise ValueError('STOP_MANAGED_SERVICES_FIRST:PID_'+proc.name)

def flat(root):
    sys.path.insert(0,str(root/'backend'))
    from market_lab.hilega_upstox_sandbox_basket_v2 import BasketWorker
    status=BasketWorker().status()
    if any(status.get(k) for k in ('open_legs','pending_fill_orders','uncertain_requests')):
        raise ValueError('SANDBOX_EXPOSURE_OR_UNRESOLVED_ORDERS:do not switch policy')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path.cwd())
    modes=ap.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check',action='store_true')
    modes.add_argument('--stage',type=Path)
    modes.add_argument('--apply',action='store_true')
    ap.add_argument('--validation',type=Path,action='append',default=[])
    args=ap.parse_args();root=args.root.resolve()
    manifest=json.loads((HERE/'manifest.json').read_text())
    for name,meta in manifest['files'].items():
        source=HERE/'files'/name;current=root/name
        if digest(source)!=meta['new_sha256']:raise ValueError('BUNDLE_INTEGRITY_MISMATCH:'+name)
        if digest(current) not in (meta['old_sha256'],meta['new_sha256']):raise ValueError('LOCAL_SOURCE_DIFFERS:'+name)
        if name.endswith('.py'):compile(source.read_text(),name,'exec')
    if args.check:
        print(json.dumps(dict(status='SOURCE_VALIDATED',policy_id=POLICY,files=len(manifest['files']),tests_run=False,orders_sent=False)));return
    if args.stage:
        destination=args.stage.resolve()
        if destination==root or root in destination.parents and not str(destination).startswith(str(root/'data/research')):
            raise ValueError('STAGE_MUST_BE_SEPARATE_OR_UNDER_DATA_RESEARCH')
        if destination.exists():raise ValueError('STAGE_ALREADY_EXISTS:choose a new directory')
        destination.mkdir(parents=True)
        for name in ('backend','hilega_policy_live','frontend'):
            shutil.copytree(root/name,destination/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','node_modules','dist'))
        if (root/'frontend/node_modules').is_dir():
            (destination/'frontend/node_modules').symlink_to(root/'frontend/node_modules',target_is_directory=True)
        for name in manifest['files']:
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(HERE/'files'/name,target)
        print(json.dumps(dict(status='STAGED',path=str(destination),services_started=False,orders_sent=False)));return
    # Approval is the user's --apply command; validate every prerequisite before writes.
    dates=set()
    for path in args.validation:
        report=json.loads(path.read_text())
        if report.get('status')!='PASS' or report.get('strategy_version')!=VERSION:raise ValueError('PASS_PARITY_REPORT_REQUIRED')
        for row in report['sessions']:
            if any(row.get(k)!='PASS' for k in ('research_trade_parity','live_replay_event_parity','shadow_event_dispatch_parity')):raise ValueError('INCOMPLETE_PARITY_REPORT')
            dates.add(row['session_date'])
        for name,sha in report.get('implementation_sha256',{}).items():
            if sha!=manifest['files'][name]['new_sha256']:raise ValueError('VALIDATION_USED_DIFFERENT_CODE:'+name)
        if len(report.get('implementation_sha256',{}))!=3:raise ValueError('VALIDATED_IMPLEMENTATION_HASHES_REQUIRED')
    if not REQUIRED_DAYS<=dates:raise ValueError('ELEVEN_OCTOBER_SESSION_PARITY_REQUIRED:'+','.join(sorted(REQUIRED_DAYS-dates)))
    os.chdir(root);stopped(root);flat(root)
    backup=root/'backups'/('combined-gap2-promotion-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True);written=[]
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    try:
        for name,meta in manifest['files'].items():
            target=root/name
            if target.exists():
                saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(HERE/'files'/name,target);written.append(name)
    except Exception:
        for name in reversed(written):
            saved=backup/name
            if saved.exists():shutil.copy2(saved,root/name)
            else:(root/name).unlink(missing_ok=True)
        raise
    print(json.dumps(dict(status='APPLIED',policy_id=POLICY,strategy_version=VERSION,backup=str(backup),services_started=False,orders_sent=False)))

if __name__=='__main__':main()
