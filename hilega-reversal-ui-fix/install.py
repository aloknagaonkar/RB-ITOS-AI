"""Guarded UI-only installer. No services, orders or strategy changes."""
import argparse,hashlib,json,shutil
from pathlib import Path
from datetime import datetime,timezone
root=Path(__file__).resolve().parent
ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');a=ap.parse_args()
manifest=json.loads((root/'manifest.json').read_text());repo=Path.cwd()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
target=repo/'frontend/src/hilegaDecisionTable.tsx'
if not target.exists():raise SystemExit('Run from RB-ITOS-AI repository root')
for name,value in manifest['files'].items():
    if sha(root/'files'/name)!=value:raise SystemExit('PAYLOAD_HASH_MISMATCH:'+name)
if sha(target)==manifest['files']['frontend/src/hilegaDecisionTable.tsx']:
    print('ALREADY_APPLIED');raise SystemExit(0)
if sha(target)!=manifest['expected_source_sha256']:raise SystemExit('SOURCE_CHANGED: no files modified; review latest UI source')
print('SOURCE_VALIDATED: UI only; no strategy changes')
if a.apply:
    backup=repo/'backups'/('hilega-reversal-ui-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
    protected={str(p):sha(p) for p in (repo/'backend/market_lab').glob('hilega*.py')}
    for name in manifest['files']:
        dst=repo/name
        if dst.exists():
            b=backup/name;b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,b)
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/'files'/name,dst)
    if any(sha(Path(p))!=value for p,value in protected.items()):raise SystemExit('PROTECTED_SOURCE_CHANGED')
    print(json.dumps(dict(status='APPLIED',backup=str(backup),strategy_sources_unchanged=True,services_started=False,orders_sent=False)))
