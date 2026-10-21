"""Apply bounded display/quote changes without replacing existing strategy modules."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
PROTECTED=['backend/market_lab/'+n for n in (
    'hilega_combined_policy_v1.py','hilega_combined_replay_v1.py','hilega_alignment_dual_exit_live_v1.py',
    'hilega_v2_alignment_replay_v1.py','hilega_upstox_sandbox_basket_v2.py','hilega_sandbox_event_bridge_v1.py')]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
def build(root):
    changes={}
    steps=json.loads((HERE/'transforms.json').read_text())
    for step in steps:
        name=step['file'];text=changes.get(name,(root/name).read_text())
        count=text.count(step['old'])
        if (count<1 if step.get('firstOnly') else count!=step['count']):
            raise ValueError('SOURCE_ANCHOR_DIFFERS:'+name+':'+step['old'][:70])
        changes[name]=text.replace(step['old'],step['new'],1 if step.get('firstOnly') else step['count'])
    for p in (HERE/'files').rglob('*'):
        if not p.is_file():continue
        name=p.relative_to(HERE/'files').as_posix()
        if (root/name).exists() and (root/name).read_bytes()!=p.read_bytes():raise ValueError('NEW_FILE_ALREADY_EXISTS:'+name)
        changes[name]=p.read_text()
    for name,text in changes.items():
        if name.endswith('.py'):compile(text,name,'exec')
    return changes
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');args=ap.parse_args()
    root=Path.cwd();manifest=json.loads((HERE/'bundle-sha256.json').read_text())
    for name,sha in manifest.items():
        if digest(HERE/name)!=sha:raise ValueError('BUNDLE_INTEGRITY_MISMATCH:'+name)
    marker=root/'data/runtime/hilega-live-refresh-install.json'
    if marker.is_file():
        recorded=json.loads(marker.read_text())
        if recorded.get('bundle')==digest(HERE/'bundle-sha256.json') and all(digest(root/n)==v for n,v in recorded['files'].items()):
            print(json.dumps(dict(status='ALREADY_APPLIED',tests_run=False,orders_sent=False)));return
    changes=build(root);protected={n:digest(root/n) for n in PROTECTED}
    print(json.dumps(dict(status='SOURCE_VALIDATED',files=list(changes),tests_run=False,orders_sent=False)))
    if not args.apply:return
    backup=root/'backups'/('hilega-live-refresh-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True);written=[]
    try:
        for name,text in changes.items():
            target=root/name;saved=backup/name
            if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
            target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text);written.append(name)
        if any(digest(root/n)!=v for n,v in protected.items()):raise ValueError('PROTECTED_STRATEGY_SOURCE_CHANGED')
        proof=dict(bundle=digest(HERE/'bundle-sha256.json'),files={n:digest(root/n) for n in changes},protected_sha256=protected,backup=str(backup))
        marker.parent.mkdir(parents=True,exist_ok=True);marker.write_text(json.dumps(proof,indent=2))
    except Exception:
        for name in reversed(written):
            saved=backup/name
            if saved.exists():shutil.copy2(saved,root/name)
            else:(root/name).unlink(missing_ok=True)
        raise
    print(json.dumps(dict(status='APPLIED',backup=str(backup),protected_strategy_hashes_unchanged=True,services_started=False,orders_sent=False)))
if __name__=='__main__':main()
