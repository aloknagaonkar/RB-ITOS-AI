"""Exercise the reissued CLI against an isolated candidate source tree."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

@pytest.fixture
def candidate():
    repo=os.getenv('HILEGA_ROLLOUT_TEST_REPO')
    package=os.getenv('HILEGA_ROLLOUT_TEST_PACKAGE')
    if not repo or not package:pytest.skip('Run through rollout.py for isolated candidate paths')
    return Path(repo),Path(package)

def check(repo,package,action='check'):
    return subprocess.run([sys.executable,'-B',str(package/'cli.py'),action,'--repo',str(repo)],
        capture_output=True,text=True,timeout=60)

def test_candidate_check_remains_closed_and_read_only(candidate):
    repo,package=candidate;result=check(repo,package)
    assert result.returncode==0
    report=json.loads(result.stdout)
    assert report['status']=='PACKAGE_AND_RUNTIME_CHECK_PASS'
    for flag in ('database_access_performed','credentials_opened','broker_reads_performed',
                 'order_actions_available','production_execution_enabled'):
        assert report[flag] is False

def test_modified_package_module_still_rejected(candidate,tmp_path):
    repo,package=candidate;copy=tmp_path/'package';shutil.copytree(package,copy)
    p=copy/'operational_lifecycle_review.py';p.write_text(p.read_text()+'\n# tampered\n')
    result=check(repo,copy)
    assert result.returncode==2
    assert json.loads(result.stdout)['status']=='PACKAGE_OR_RUNTIME_CHECK_FAILED'

def test_modified_manifest_still_rejected(candidate,tmp_path):
    repo,package=candidate;copy=tmp_path/'package';shutil.copytree(package,copy)
    (copy/'manifest.json').write_text('{"private":"DO_NOT_ECHO_TEST_SENTINEL"}')
    result=check(repo,copy)
    assert result.returncode==2 and 'DO_NOT_ECHO_TEST_SENTINEL' not in result.stdout

@pytest.mark.parametrize('relative',[
    'backend/market_lab/live_shadow_worker_v1.py',
    'backend/market_lab/hilega_three_minute_v1/worker_close.py'])
def test_modified_old_and_new_runtime_modules_rejected(candidate,tmp_path,relative):
    repo,package=candidate;copy=tmp_path/'repo'
    shutil.copytree(repo/'backend',copy/'backend')
    path=copy/relative;path.write_text(path.read_text()+'\n# changed\n')
    assert check(copy,package).returncode==2

def test_missing_runtime_rejected(candidate,tmp_path):
    _,package=candidate;empty=tmp_path/'empty';empty.mkdir()
    assert check(empty,package).returncode==2

@pytest.mark.parametrize('action',['submit','cancel','release'])
def test_order_actions_remain_unavailable(candidate,action):
    repo,package=candidate
    assert check(repo,package,action).returncode==2

def test_all_candidate_namespace_files_are_pinned(candidate):
    repo,package=candidate
    manifest=json.loads((package/'manifest.json').read_text())
    assert manifest['order_actions_available'] is False
    assert manifest['production_execution_enabled'] is False
    for path in (repo/'backend/market_lab/hilega_three_minute_v1').glob('*.py'):
        assert manifest['runtime'][path.relative_to(repo).as_posix()]==hashlib.sha256(path.read_bytes()).hexdigest()

def test_rebinding_preserves_existing_pins_and_authority():
    from companion_bindings import rebind,PACKAGE,SERVICE,digest
    manifest=dict(model='HILEGA_OPERATIONAL_LIFECYCLE_PACKAGE_V1',
        modules={'unchanged.py':'module-digest'},order_actions_available=False,production_execution_enabled=False,
        runtime={'backend/old.py':'previous','backend/keep.py':'keep-digest'})
    raw=(json.dumps(manifest,indent=2)+'\n').encode()
    cli=("EXPECTED_MANIFEST = '"+digest(raw)+"'\n").encode()
    service=("CLI_SHA = '"+digest(cli)+"'\n").encode()
    original={str(PACKAGE/'manifest.json'):raw,str(PACKAGE/'cli.py'):cli,str(SERVICE):service}
    changed=rebind(original,{'backend/old.py':b'new','backend/new.py':b'added','frontend/test.tsx':b'ignored'})
    current=json.loads(changed['files'][str(PACKAGE/'manifest.json')])
    assert current['modules']==manifest['modules']
    assert current['runtime']['backend/keep.py']=='keep-digest'
    assert current['runtime']['backend/old.py']==digest(b'new')
    assert current['runtime']['backend/new.py']==digest(b'added')
    assert 'frontend/test.tsx' not in current['runtime']
    assert current['production_execution_enabled'] is False and current['order_actions_available'] is False
    assert changed['changed_runtime']==['backend/old.py'] and changed['added_runtime']==['backend/new.py']

def test_service_preview_forces_check_without_mutating_runtime_arguments():
    from companion_bindings import service_check_arguments
    original=['--watch','--repo','old','--package','old-package','--env-file','private-env']
    args=service_check_arguments(original,Path('/candidate'),Path('/candidate-package'))
    assert original[0]=='--watch' and args[0]=='--check'
    assert args[args.index('--env-file')+1]=='private-env'
    assert args[args.index('--repo')+1]=='/candidate'
