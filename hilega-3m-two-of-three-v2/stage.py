"""Hash-guarded offline staging. Never applies files to the installed app."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import ast
import zipfile

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

def export_review(repo,result,destination):
    """Export current guarded Python source and its static local dependencies."""
    destination=destination.resolve()
    if destination.exists():raise ValueError('REVIEW_ARCHIVE_ALREADY_EXISTS')
    manifest=json.loads((HERE/'manifest.json').read_text())
    selected=set();pending=[repo/n for n in manifest['baseline_sha256'] if n.endswith('.py')]
    while pending:
        path=pending.pop()
        if not path.is_file():continue
        path=path.resolve()
        try:relative=path.relative_to(repo)
        except ValueError:raise ValueError('REVIEW_SOURCE_OUTSIDE_REPOSITORY')
        if relative in selected:continue
        selected.add(relative)
        tree=ast.parse(path.read_text(),filename=str(relative))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and node.level==1 and node.module:
                dependency=path.parent/(node.module.replace('.','/')+'.py')
                if dependency.is_file():pending.append(dependency)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('source-check.json',json.dumps(result,indent=2)+'\n')
        for relative in sorted(selected):archive.write(repo/relative,relative.as_posix())
    return str(destination)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd())
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check',action='store_true')
    group.add_argument('--stage',type=Path)
    p.add_argument('--export-review',type=Path,help='On mismatch only, export current Python sources; no environment/config/database files')
    a=p.parse_args();repo=a.repo.resolve();result=check(repo)
    if result['status']!='SOURCE_MATCH':
        if a.export_review:result['review_archive']=export_review(repo,result,a.export_review)
        print(json.dumps(result,indent=2));return 2
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
