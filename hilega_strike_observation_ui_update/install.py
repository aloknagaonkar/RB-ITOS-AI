"""Guarded read-only observation dashboard installer. No service, order or arming actions."""
import argparse,hashlib,json,os,shutil
from datetime import datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args()
    root=Path.cwd()
    if not (root/'backend/market_lab').is_dir():p.error('Run from repository root')
    rows=json.loads((HERE/'manifest.json').read_text());errors=[]
    for row in rows:
        if sha(HERE/'files'/row['path'])!=row['after']:errors.append('PACKAGE_HASH_MISMATCH:'+row['path'])
        if sha(root/row['path']) not in {row['before'],row['after'],*row.get('accepted_before',[])}:errors.append('SOURCE_HASH_MISMATCH:'+row['path'])
    if errors:raise SystemExit(json.dumps(dict(status='BLOCKED',errors=errors)))
    print(json.dumps(dict(status='VALIDATED',files=[r['path'] for r in rows],tests_run=False)))
    if a.check:return
    backup=root/'backups'/('strike-observation-ui-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True);created=[]
    for row in rows:
        target=root/row['path']
        if sha(target)==row['after']:continue
        if target.exists():
            old=backup/row['path'];old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,old)
        else:created.append(row['path'])
        target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_name(target.name+'.observation.tmp')
        shutil.copy2(HERE/'files'/row['path'],temp);os.replace(temp,target)
    (backup/'created-files.json').write_text(json.dumps(created,indent=2))
    print(json.dumps(dict(status='APPLIED',backup=str(backup),research_only=True,activation_changed=False,tests_run=False)))
if __name__=='__main__':main()
