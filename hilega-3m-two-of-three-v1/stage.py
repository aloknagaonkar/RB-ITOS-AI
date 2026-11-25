"""Hash-guarded offline staging. Never applies files to the installed app."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE=Path(__file__).resolve().parent

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def check(repo):
    manifest=json.loads((HERE/'manifest.json').read_text())
    mismatches=[]
    for relative,expected in manifest['baseline_sha256'].items():
        path=repo/relative
        actual=digest(path) if path.is_file() else None
        if actual!=expected:mismatches.append(dict(path=relative,expected=expected,actual=actual))
    for relative,expected in manifest['candidate_sha256'].items():
        path=HERE/'files'/relative
        if not path.is_file() or digest(path)!=expected:raise ValueError('PACKAGE_CHANGED:'+relative)
    return dict(status='SOURCE_MATCH' if not mismatches else 'SOURCE_MISMATCH',
        repo=str(repo),mismatches=mismatches,installed_files_modified=False,
        services_restarted=False,broker_requests_sent=False)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd())
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check',action='store_true')
    group.add_argument('--stage',type=Path)
    a=p.parse_args();repo=a.repo.resolve();result=check(repo)
    if result['status']!='SOURCE_MATCH':print(json.dumps(result,indent=2));return 2
    if a.stage:
        stage=a.stage.resolve()
        if stage==repo or repo in stage.parents:raise ValueError('STAGE_MUST_BE_OUTSIDE_REPOSITORY')
        if stage.exists():raise ValueError('STAGE_ALREADY_EXISTS: choose a fresh path')
        stage.mkdir(parents=True)
        try:
            shutil.copytree(repo/'backend',stage/'backend',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            shutil.copytree(repo/'frontend',stage/'frontend',ignore=shutil.ignore_patterns('node_modules','dist','.vite'))
            if (repo/'frontend/node_modules').is_dir():
                (stage/'frontend/node_modules').symlink_to(repo/'frontend/node_modules',target_is_directory=True)
            for src in sorted((HERE/'files').rglob('*')):
                if src.is_file():
                    dst=stage/src.relative_to(HERE/'files');dst.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(src,dst)
            result.update(status='STAGED_ONLY',stage=str(stage),strategy_version=json.loads((HERE/'manifest.json').read_text())['strategy_version'])
            (stage/'stage-receipt.json').write_text(json.dumps(result,indent=2)+'\n')
        except Exception:
            shutil.rmtree(stage);raise
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':sys.exit(main())
