"""Hash-guarded additive installer. No services, strategy changes or orders."""
import argparse
from datetime import datetime,timezone
import hashlib,json,shutil,os
from pathlib import Path

HERE=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def preflight(root,manifest):
    failures=[]
    for name,expected in manifest.get('requires',{}).items():
        dependency=root/name
        if not dependency.is_file() or sha(dependency)!=expected:failures.append(name+': REQUIRED_VALIDATED_DEPENDENCY_DIFFERS')
    for name,new in manifest['files'].items():
        source=HERE/'files'/name;dest=root/name
        if sha(source)!=new:failures.append(name+': PACKAGE_HASH_MISMATCH');continue
        if dest.exists():
            actual=sha(dest)
            if actual!=new and actual!=manifest['expected'].get(name):failures.append(name+': TARGET_DIFFERS_FROM_UPLOADED_SOURCE')
        elif name in manifest['expected']:failures.append(name+': EXPECTED_TARGET_MISSING')
    if failures:raise SystemExit('\n'.join(['STOPPED_WITHOUT_CHANGES',*failures]))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.cwd());p.add_argument('--stage',type=Path);p.add_argument('--apply',action='store_true');p.add_argument('--validation',type=Path)
    a=p.parse_args();root=a.root.resolve();manifest=json.loads((HERE/'manifest.json').read_text())
    if a.stage and a.apply:p.error('Choose staging or apply')
    preflight(root,manifest)
    if a.stage:
        stage=a.stage.resolve()
        if stage==root or root in stage.parents and stage.parts[-1] in ('backend','frontend','scripts','tests'):raise SystemExit('INVALID_STAGE_PATH')
        if stage.exists():raise SystemExit('STAGE_EXISTS_USE_NEW_PATH')
        stage.mkdir(parents=True)
        for name in ('backend','frontend','scripts','tests'):
            shutil.copytree(root/name,stage/name,ignore=shutil.ignore_patterns('node_modules','dist','__pycache__','.env*','*.bak','*.pyc'))
        if (root/'pyproject.toml').exists():shutil.copy2(root/'pyproject.toml',stage/'pyproject.toml')
        modules=root/'frontend/node_modules'
        if modules.exists():(stage/'frontend/node_modules').symlink_to(modules,target_is_directory=True)
        for name in manifest['files']:
            dest=stage/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(HERE/'files'/name,dest)
        print(json.dumps(dict(status='STAGED',path=str(stage),services_started=False,orders_sent=False)));return
    if not a.apply:
        print(json.dumps(dict(status='SOURCE_VALIDATED',files=len(manifest['files']),archive_commit=manifest['archive_commit'],tests_run=False,orders_sent=False)));return
    from dotenv import dotenv_values
    values=dotenv_values(root/'.env')
    if str(os.getenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED',values.get('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED') or '0')).strip()=='1':
        raise SystemExit('STOP_READER_AND_DISABLE_BRIDGE_FLAG_BEFORE_APPLY')
    if not a.validation:raise SystemExit('VALIDATION_REPORT_REQUIRED')
    proof=json.loads(a.validation.read_text())
    if proof.get('status')!='PASS' or proof.get('files')!=manifest['files'] or proof.get('model')!='HILEGA_BRIDGE_HEALTH_VALIDATION_V1':raise SystemExit('VALIDATION_FAILED_OR_SOURCE_CHANGED')
    backup=root/'backups'/('hilega-bridge-health-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
    existing=[];created=[]
    for name in manifest['files']:
        dest=root/name
        if dest.exists():
            saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,saved);existing.append(name)
        else:created.append(name)
    (backup/'rollback.json').write_text(json.dumps(dict(existing=existing,created=created),indent=2))
    for name in manifest['files']:
        dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(HERE/'files'/name,dest)
    print(json.dumps(dict(status='APPLIED',backup=str(backup),orders_sent=False,services_started=False,
        production_execution_enabled=False,strategy_files_modified=False)))

if __name__=='__main__':main()
