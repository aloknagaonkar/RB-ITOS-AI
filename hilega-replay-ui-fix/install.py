"""Presentation-only replay patch. Run from the repository on the Ubuntu VM."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');args=ap.parse_args()
    root=Path.cwd();manifest=json.loads((HERE/'manifest.json').read_text())
    for name,meta in manifest.items():
        if sha(root/name) not in (meta['old'],meta['new']):raise ValueError('LOCAL_SOURCE_DIFFERS:'+name)
        if sha(HERE/'files'/name)!=meta['new']:raise ValueError('PAYLOAD_MISMATCH:'+name)
        if name.endswith('.py'):compile((HERE/'files'/name).read_text(),name,'exec')
    if not args.apply:
        print(json.dumps(dict(status='SOURCE_VALIDATED',files=len(manifest),tests_run=False)));return
    backup=root/'backups'/('combined-replay-display-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True);written=[]
    try:
        for name in manifest:
            target=root/name;saved=backup/name
            if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(HERE/'files'/name,target);written.append(name)
    except Exception:
        for name in reversed(written):
            saved=backup/name
            if saved.is_file():shutil.copy2(saved,root/name)
            else:(root/name).unlink(missing_ok=True)
        raise
    print(json.dumps(dict(status='APPLIED',backup=str(backup),strategy_rules_changed=False,services_started=False,orders_sent=False)))
if __name__=='__main__':main()
