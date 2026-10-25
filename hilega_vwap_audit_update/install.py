"""Guarded audit-view installer. No services, token reads or trading actions."""
import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime,timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');args=p.parse_args()
    root=Path.cwd()
    if not (root/'backend/market_lab').is_dir():p.error('Run from repository root')
    manifest=json.loads((HERE/'manifest.json').read_text());selected=[];errors=[]
    for row in manifest:
        for variant in row['variants']:
            if sha(HERE/variant['source'])!=variant['after']:errors.append('PACKAGE_HASH_MISMATCH:'+row['path'])
        current=sha(root/row['path'])
        chosen=next((v for v in row['variants'] if current in (v['before'],v['after'])),None)
        if chosen is None:errors.append('SOURCE_HASH_MISMATCH:'+row['path'])
        else:selected.append((row['path'],chosen))
    if errors:raise SystemExit(json.dumps(dict(status='BLOCKED',errors=errors)))
    print(json.dumps(dict(status='VALIDATED',files=[x[0] for x in selected],tests_run=False)))
    if args.check:return
    backup=root/'backups'/('vwap-audit-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True);created=[]
    for relative,v in selected:
        target=root/relative
        if sha(target)==v['after']:continue
        if target.exists():
            old=backup/relative;old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,old)
        else:created.append(relative)
        target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_name(target.name+'.vwap.tmp')
        shutil.copy2(HERE/v['source'],temp);os.replace(temp,target)
    (backup/'created-files.json').write_text(json.dumps(created,indent=2))
    print(json.dumps(dict(status='APPLIED',backup=str(backup),activation_changed=False,tests_run=False)))


if __name__=='__main__':main()
