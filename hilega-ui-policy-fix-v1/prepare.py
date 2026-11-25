#!/usr/bin/env python3
"""Source-guarded UI correction staging. Does not install or restart services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen

PACKAGE=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path):
    return path.is_file() and not path.is_symlink() and not any(p.is_symlink() for p in path.absolute().parents)


def run(command,cwd,log,env=None):
    with log.open('w') as stream:
        p=subprocess.run(command,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT)
    if p.returncode:raise ValueError('CHECK_FAILED_SEE_LOG:'+str(log))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--prepare',action='store_true',required=True)
    p.add_argument('--work',type=Path,default=Path('/tmp/hilega-ui-policy-fix-v1'))
    p.add_argument('--api-url',default='http://127.0.0.1:8123')
    a=p.parse_args();repo=a.repo.resolve();manifest=json.loads((PACKAGE/'manifest.json').read_text())
    mismatches=[]
    for rel,item in manifest['files'].items():
        if not regular(PACKAGE/'files'/rel) or sha(PACKAGE/'files'/rel)!=item['after']:
            raise ValueError('PACKAGE_FILE_MODIFIED:'+rel)
        file=repo/rel
        if not regular(file) or sha(file)!=item['before']:
            mismatches.append(dict(path=rel,expected=item['before'],actual=sha(file) if regular(file) else 'MISSING_OR_SYMLINK'))
    if mismatches:
        print(json.dumps(dict(status='SOURCE_MISMATCH_NO_INSTALLATION',mismatches=mismatches,
            installed_files_modified=False,services_restarted=False),indent=2));return
    with urlopen(a.api_url.rstrip('/')+'/api/live-shadow/hilega-directional/status?fast=true',timeout=30) as response:
        status=json.load(response)
    if (status.get('strategy_version')!=manifest['strategy_version'] or
        status.get('observation_only') is not True or status.get('execution_enabled') is not False):
        raise ValueError('EXPECTED_OBSERVATION_POLICY_NOT_VERIFIED')
    work=a.work.resolve()
    if work==repo or repo in work.parents:raise ValueError('STAGING_MUST_BE_OUTSIDE_INSTALLED_REPO')
    work.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='candidate-',dir=work))
    print('Preparing isolated candidate:',stage,flush=True)
    shutil.copytree(repo/'backend',stage/'backend',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(repo/'frontend',stage/'frontend',ignore=shutil.ignore_patterns('node_modules','dist','*.tsbuildinfo'))
    shutil.copytree(repo/'hilega-operational-lifecycle-tools-6cexrur_',stage/'hilega-operational-lifecycle-tools-6cexrur_',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for rel in manifest['files']:
        target=stage/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(PACKAGE/'files'/rel,target)
    if not (repo/'frontend/node_modules/typescript').is_dir():raise ValueError('EXISTING_FRONTEND_DEPENDENCIES_REQUIRED')
    (stage/'frontend/node_modules').symlink_to(repo/'frontend/node_modules',target_is_directory=True)
    env=dict(os.environ,HILEGA_UI_CANDIDATE=str(stage),PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(stage/'backend'))
    logs={}
    checks=[('policy_tests',[sys.executable,'-B','-m','unittest','discover','-s',str(PACKAGE/'tests')],stage),
        ('ui_contract_tests',['node',str(PACKAGE/'tests/test_ui.cjs')],stage),
        ('frontend_build',['npm','run','build'],stage/'frontend'),
        ('companion_runtime_pins',[sys.executable,'-B',str(stage/'hilega-operational-lifecycle-tools-6cexrur_/cli.py'),'check','--repo',str(stage)],stage)]
    for name,cmd,cwd in checks:
        print('Checking:',name,flush=True);log=stage/(name+'.log');run(cmd,cwd,log,env);logs[name]=str(log)
    pins=json.loads((stage/'companion_runtime_pins.log').read_text())
    if pins.get('status')!='PACKAGE_AND_RUNTIME_CHECK_PASS':raise ValueError('UNEXPECTED_COMPANION_CHECK_RESULT')
    for flag in ['database_access_performed','credentials_opened','broker_reads_performed','order_actions_available','production_execution_enabled']:
        if pins.get(flag) is not False:raise ValueError('COMPANION_CHECK_SCOPE_CHANGED:'+flag)
    # Assert the installed sources are still at the reviewed baseline after all checks.
    for rel,item in manifest['files'].items():
        if sha(repo/rel)!=item['before']:raise ValueError('INSTALLED_SOURCE_CHANGED_DURING_PREPARATION:'+rel)
    assets={str(f.relative_to(stage/'frontend/dist')):sha(f) for f in sorted((stage/'frontend/dist').rglob('*')) if f.is_file()}
    if 'index.html' not in assets:raise ValueError('BUILT_INDEX_MISSING')
    result=dict(status='UI_POLICY_FIX_PREPARED_NOT_INSTALLED',repo=str(repo),stage=str(stage),
        strategy_version=manifest['strategy_version'],checks=logs,built_asset_sha256=assets,
        files=manifest['files'],runtime_pin_changes=manifest['runtime_pin_changes'],
        unchanged_runtime_pins=manifest['unchanged_runtime_count'],
        installed_files_modified=False,services_restarted=False,broker_requests_sent=False,
        journals_rewritten=False,strategy_rules_changed=False,
        remaining='Controlled installation of reviewed UI files, built assets and companion hash anchors; API/reference-service restart and rendered-table verification')
    (stage/'preparation.json').write_text(json.dumps(result,indent=2)+'\n')
    (work/'latest-preparation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
