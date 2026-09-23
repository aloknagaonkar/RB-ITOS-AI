#!/usr/bin/env python3
"""Hash-safe, additive fix for independent Hilega historical session selection.
Does not touch running services, evidence, broker credentials, or backend routes.
"""
import argparse, hashlib, shutil
from datetime import datetime, timezone
from pathlib import Path

OLD_PARENT = '<HilegaHistoricalReplay selectedDate={selected} />'
NEW_PARENT = '<HilegaHistoricalReplay />'
PARENT_REL = 'frontend/src/historicalReplay.tsx'
CHILD_REL = 'frontend/src/hilegaHistoricalReplay.tsx'

def sha(content): return hashlib.sha256(content).hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repo', required=True, type=Path)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check',action='store_true')
    group.add_argument('--apply',action='store_true')
    a=p.parse_args()
    root=a.repo.expanduser().resolve()
    source=Path(__file__).resolve().parent/CHILD_REL
    child=root/CHILD_REL
    parent=root/PARENT_REL
    if not source.is_file() or not child.is_file() or not parent.is_file():
        raise SystemExit('BLOCKED: expected source and installed Historical Replay files must exist')
    c=child.read_text()
    ptext=parent.read_text()
    target=source.read_text()
    # Only apply if the installed version matches the first patch or is already this fix.
    old_markers=(
        'export default function HilegaHistoricalReplay({selectedDate}:{selectedDate:string})',
        'const available=useMemo(()=>captures.filter(c=>c.session_date===selectedDate)',
        '   <label>Historical capture <select value={captureId}',
    )
    already=(c==target and NEW_PARENT in ptext and OLD_PARENT not in ptext)
    if already:
        print('ALREADY APPLIED: independent Hilega session selector; no changes')
        return
    if not all(marker in c for marker in old_markers):
        raise SystemExit('BLOCKED: installed Hilega component differs from expected v1; no files modified')
    if c.count('export default function HilegaHistoricalReplay')!=1:
        raise SystemExit('BLOCKED: unexpected component structure; no files modified')
    if ptext.count(OLD_PARENT)!=1 or NEW_PARENT in ptext:
        raise SystemExit('BLOCKED: parent integration differs from expected v1; no files modified')
    print(f'PATCH: {CHILD_REL} (current sha256 {sha(c.encode())[:12]})')
    print(f'PATCH: {PARENT_REL} (current sha256 {sha(ptext.encode())[:12]})')
    if a.check:
        print('CHECK PASSED; no files changed.')
        return
    backup=root/'.hilega-ui-integration-backup'/('independent-session-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    for rel in (CHILD_REL,PARENT_REL):
        dest=backup/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root/rel,dest)
    # Change only the Hilega component invocation in the existing Historical Replay UI.
    child.write_text(target)
    parent.write_text(ptext.replace(OLD_PARENT, NEW_PARENT, 1))
    print('APPLIED; backup:',backup)
    print('No processes restarted, no historical evidence altered.')

if __name__=='__main__': main()
