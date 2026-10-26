"""Build a guarded application checkout for VM validation. No apply option."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

HERE=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.cwd())
    p.add_argument('--stage',type=Path,required=True)
    args=p.parse_args();root=args.root.resolve();stage=args.stage.resolve()
    manifest=json.loads((HERE/'manifest.json').read_text())
    errors=[]
    for name,wanted in manifest['files'].items():
        packaged=HERE/'files'/name;existing=root/name
        if sha(packaged)!=wanted:errors.append(name+': PACKAGE_HASH_MISMATCH')
        if name in manifest['expected']:
            if not existing.is_file() or sha(existing) not in {manifest['expected'][name],wanted}:
                errors.append(name+': CURRENT_APPLICATION_SOURCE_DIFFERS')
        elif existing.exists() and (not existing.is_file() or sha(existing)!=wanted):
            errors.append(name+': NEW_APPLICATION_PATH_ALREADY_DIFFERS')
    for name,wanted in manifest['dependencies'].items():
        existing=root/name
        if not existing.is_file() or sha(existing)!=wanted:errors.append(name+': DEPENDENCY_CHANGED')
    if errors:raise SystemExit('\n'.join(['STOPPED_WITHOUT_SOURCE_CHANGES',*errors]))
    if stage.exists() or stage==root or root in stage.parents or stage in root.parents:
        raise SystemExit('FRESH_STAGE_OUTSIDE_REPOSITORY_REQUIRED')
    stage.mkdir(parents=True,mode=0o700)
    for folder in ('backend','scripts','tests'):
        shutil.copytree(root/folder,stage/folder,ignore=shutil.ignore_patterns(
            '__pycache__','*.pyc','.env*','.venv','node_modules','data','*.sqlite*','*.db','*.pem','*.key'))
    for name in ('pyproject.toml','pytest.ini','setup.cfg'):
        if (root/name).is_file():shutil.copy2(root/name,stage/name)
    # Only the pinned existing helper sources needed by evidence validation.
    for name in manifest['dependencies']:
        destination=stage/name
        if not destination.exists():
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,destination)
    for name in manifest['files']:
        destination=stage/name;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(HERE/'files'/name,destination)
    (stage/'APPLICATION_PREPARATION_STAGED.json').write_text(json.dumps(dict(
        model='APPLICATION_PREPARATION_STAGED_V1',files=manifest['files'],production_execution_enabled=False)))
    print(json.dumps(dict(status='APPLICATION_SOURCES_STAGED',path=str(stage),
        source_repository_modified=False,services_started=False,production_execution_enabled=False)))


if __name__=='__main__':main()
