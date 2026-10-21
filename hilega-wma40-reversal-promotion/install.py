"""Stage/apply only explicitly listed promotion files. No services or orders."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check',action='store_true')
    ap.add_argument('--stage',type=Path)
    ap.add_argument('--apply',action='store_true')
    ap.add_argument('--validation',type=Path)
    args=ap.parse_args()
    if args.stage and args.apply:raise ValueError('SELECT_STAGE_OR_APPLY')
    root=Path.cwd()
    manifest=json.loads((HERE/'manifest.json').read_text())
    hashes=json.loads((HERE/'source-hashes.json').read_text())
    for name,sha in manifest.items():
        if digest(HERE/'files'/name)!=sha:raise ValueError('BUNDLE_INTEGRITY:'+name)
        if name in hashes:
            if digest(root/name) not in (hashes[name],sha):raise ValueError('INSTALLED_SOURCE_DIFFERS:'+name)
        elif (root/name).exists() and digest(root/name)!=sha:raise ValueError('NEW_FILE_CONFLICT:'+name)
        if name.endswith('.py'):compile((HERE/'files'/name).read_text(),name,'exec')
    print(json.dumps(dict(status='SOURCE_VALIDATED',files=len(manifest),orders_sent=False,tests_run=False)))
    if args.stage:
        if args.stage.exists():raise ValueError('STAGE_EXISTS_USE_NEW_PATH')
        for part in ('backend','frontend'):
            shutil.copytree(root/part,args.stage/part,ignore=shutil.ignore_patterns('node_modules','dist','__pycache__','.venv','.env','*.pyc'))
        modules=root/'frontend/node_modules'
        if modules.exists():(args.stage/'frontend/node_modules').symlink_to(modules.resolve(),target_is_directory=True)
        for name in manifest:
            target=args.stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(HERE/'files'/name,target)
        print(json.dumps(dict(status='STAGED',path=str(args.stage.resolve()),services_started=False)));return
    if not args.apply:return
    if not args.validation:raise ValueError('VALIDATION_REQUIRED')
    proof=json.loads(args.validation.read_text())
    if proof.get('status')!='PASS' or not proof.get('sessions'):raise ValueError('PASSING_PARITY_REQUIRED')
    if proof.get('strategy_version')!='bullish-gap2-full-wma2-2.0.0-wma40-reversal':raise ValueError('WRONG_VALIDATION_VERSION')
    covered={r['session_date'] for r in proof['sessions'] if r.get('status')=='PASS'}
    if not {'2026-09-25','2026-09-29','2026-10-08','2026-10-12','2026-10-19','2026-10-21'}<=covered:
        raise ValueError('REQUIRED_PARITY_DATES_MISSING')
    for name,sha in proof['implementation_sha256'].items():
        if manifest.get(name)!=sha:raise ValueError('VALIDATION_SOURCE_MISMATCH:'+name)
    protected=['backend/market_lab/'+n for n in ('hilega_upstox_sandbox_basket_v2.py','hilega_sandbox_event_bridge_v1.py','hilega_sandbox_fill_ledger_v1.py')]
    originals={n:digest(root/n) for n in protected}
    backup=root/'backups'/('hilega-wma40-reversal-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True);written=[]
    try:
        for name in manifest:
            target=root/name;saved=backup/name
            if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(HERE/'files'/name,target);written.append(name)
        if any(digest(root/n)!=sha for n,sha in originals.items()):raise ValueError('EXECUTION_SOURCE_CHANGED')
    except Exception:
        for name in reversed(written):
            if (backup/name).exists():shutil.copy2(backup/name,root/name)
            else:(root/name).unlink(missing_ok=True)
        raise
    (backup/'receipt.json').write_text(json.dumps(dict(files=manifest,validation=proof,protected=originals),indent=2))
    print(json.dumps(dict(status='APPLIED',backup=str(backup),orders_sent=False,services_started=False,
        live_execution_enabled=False,strategy_version=proof['strategy_version'])))

if __name__=='__main__':main()
