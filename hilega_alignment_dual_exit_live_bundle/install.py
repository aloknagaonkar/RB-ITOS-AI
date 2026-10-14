"""Guarded source installation with rollback; does not change .env or arm execution."""
import hashlib,json,os,shutil,subprocess,sys
from datetime import datetime
from pathlib import Path
BUNDLE=Path(__file__).resolve().parent;ROOT=BUNDLE.parent
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    manifest=json.loads((BUNDLE/'source-manifest.json').read_text())
    dependency=ROOT/'backend/market_lab/hilega_v2_alignment_replay_v1.py'
    expected=json.loads((BUNDLE/'dependency-manifest.json').read_text())
    for rel,sha in expected.items():
        if not (ROOT/rel).is_file() or digest(ROOT/rel)!=sha:
            raise SystemExit('STOP: tested historical dependency differs: '+rel)
    pid=ROOT/'data/hilega-upstox-sandbox-worker.pid'
    if pid.exists():
        try:os.kill(int(pid.read_text().strip()),0)
        except (ValueError,ProcessLookupError):pass
        else:raise SystemExit('STOP: stop Sandbox worker before installation')
    for rel,oldsha in manifest.items():
        target=ROOT/rel;payload=BUNDLE/'files'/rel
        if target.exists() and digest(target)==digest(payload):continue
        if oldsha is None:
            if target.exists():raise SystemExit('STOP: new file already exists with different content: '+rel)
        elif not target.is_file() or digest(target)!=oldsha:
            raise SystemExit('STOP: source differs from supplied repository: '+rel)
    backup=ROOT/'data/backups'/('hilega-alignment-live-'+datetime.now().strftime('%Y%m%dT%H%M%S%f'))
    backup.mkdir(parents=True);present=[]
    dist=ROOT/'frontend/dist';had_dist=dist.exists()
    if had_dist:shutil.copytree(dist,backup/'frontend-dist')
    for rel in manifest:
        target=ROOT/rel
        if target.exists():
            dest=backup/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,dest);present.append(rel)
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'backend')+os.pathsep+str(ROOT)
    try:
        for rel in manifest:
            target=ROOT/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(BUNDLE/'files'/rel,target)
        commands=[
            [sys.executable,'-m','pytest','-q','tests/test_hilega_alignment_dual_exit_live_v1.py','tests/test_hilega_alignment_activation.py','tests/test_hilega_sandbox_event_bridge_v1.py','tests/test_hilega_upstox_sandbox_basket_v2.py','tests/test_hilega_v2_alignment_auto_replay.py'],
            [sys.executable,'-m','py_compile',*[r for r in manifest if r.endswith('.py')]],
            ['npm','--prefix','frontend','run','build'],
        ]
        for command in commands:
            print('Running:',' '.join(command),flush=True)
            subprocess.run(command,cwd=ROOT,env=env,check=True)
    except BaseException:
        for rel in manifest:
            target=ROOT/rel
            if rel in present:shutil.copy2(backup/rel,target)
            else:target.unlink(missing_ok=True)
        if dist.exists():shutil.rmtree(dist)
        if had_dist:shutil.copytree(backup/'frontend-dist',dist)
        print('STOP: validation failed; source and frontend dist restored',flush=True)
        raise
    print('PASS: historical alignment + dual-exit live adapter installed.')
    print('Selection and Sandbox arm unchanged until activate.py is run.')
    print('Backup:',backup)
if __name__=='__main__':main()
