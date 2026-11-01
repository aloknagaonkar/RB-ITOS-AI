from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock,patch
import pytest
from release_tools import (
    TARGETS,UNITS,SUPERVISOR_SHA,prepare_rehearsal,apply_rehearsal,rollback_rehearsal,
    service_inventory,release_plan,probe_unit,sha,
)


@pytest.fixture
def rehearsal(tmp_path):
    root=tmp_path/'disposable';root.mkdir()
    (root/'REHEARSAL_ROOT.json').write_text(json.dumps(dict(model='HILEGA_DISPOSABLE_FILE_REHEARSAL_V1',root=str(root))))
    for name in TARGETS[:2]:
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(('original '+name).encode());p.chmod(0o640)
    replacements={n:('candidate '+n).encode() for n in TARGETS}
    return root,replacements


def original(root):
    assert not (root/TARGETS[2]).exists()
    for name in TARGETS[:2]:
        assert (root/name).read_bytes()==('original '+name).encode()
        assert (root/name).stat().st_mode&0o777==0o640


def test_file_release_and_rollback_preserve_originals_and_remove_new_module(rehearsal):
    root,new=rehearsal;prepare_rehearsal(root,new);apply_rehearsal(root)
    assert all((root/n).read_bytes()==v for n,v in new.items())
    rollback_rehearsal(root);original(root)
    rollback_rehearsal(root);original(root)


@pytest.mark.parametrize('point',['AFTER_FILE_1','AFTER_FILE_2','AFTER_FILE_3'])
def test_restart_can_restore_every_interrupted_file_swap(rehearsal,point):
    root,new=rehearsal;prepare_rehearsal(root,new)
    def stop(at):
        if at==point:raise RuntimeError('interrupted file swap')
    with pytest.raises(RuntimeError):apply_rehearsal(root,checkpoint=stop)
    rollback_rehearsal(root);original(root)


def test_external_edit_blocks_rollback_before_restoring_any_file(rehearsal):
    root,new=rehearsal;prepare_rehearsal(root,new);apply_rehearsal(root)
    (root/TARGETS[1]).write_bytes(b'external edit')
    with pytest.raises(ValueError,match='REHEARSAL_TARGET_CHANGED_EXTERNALLY'):rollback_rehearsal(root)
    assert (root/TARGETS[0]).read_bytes()==new[TARGETS[0]] and (root/TARGETS[1]).read_bytes()==b'external edit'


def test_changed_backup_cannot_be_restored(rehearsal):
    root,new=rehearsal;prepare_rehearsal(root,new);apply_rehearsal(root)
    (root/'rehearsal-transaction/0.old').write_bytes(b'changed backup')
    with pytest.raises(ValueError,match='REHEARSAL_BACKUP_CHANGED'):rollback_rehearsal(root)
    assert all((root/n).read_bytes()==v for n,v in new.items())


def test_live_checkout_or_unmarked_root_is_rejected(rehearsal,tmp_path):
    root,new=rehearsal
    with pytest.raises(ValueError):prepare_rehearsal(tmp_path,new)
    (root/'.git').mkdir()
    with pytest.raises(ValueError,match='GIT_CHECKOUT_NOT_A_REHEARSAL_ROOT'):prepare_rehearsal(root,new)


def test_symlink_target_is_rejected_before_replacing_it(rehearsal,tmp_path):
    root,new=rehearsal;outside=tmp_path/'outside';outside.write_bytes(b'untouched')
    (root/TARGETS[0]).unlink();(root/TARGETS[0]).symlink_to(outside)
    with pytest.raises(ValueError,match='SYMLINK_RELEASE_TARGET_FORBIDDEN'):prepare_rehearsal(root,new)
    assert outside.read_bytes()==b'untouched'


def test_rollback_is_retired_not_automatically_reapplied(rehearsal):
    root,new=rehearsal;prepare_rehearsal(root,new);apply_rehearsal(root);rollback_rehearsal(root)
    with pytest.raises(ValueError,match='REHEARSAL_APPLY_REQUIRES_PREPARED'):apply_rehearsal(root)
    original(root)


def test_source_mapping_export_never_contains_raw_arguments_or_secrets(tmp_path):
    repo=tmp_path/'repo';repo.mkdir();home=tmp_path/'home';home.mkdir()
    runner=home/'hilega-persistent-supervision-stage-v1/runner.py';runner.parent.mkdir();runner.write_bytes(b'synthetic supervisor')
    command=str(runner)+' production-source-worker TOKEN=must-not-export'
    stdout='ActiveState=active\nSubState=running\nUnitFileState=enabled\nWorkingDirectory='+str(repo)+'\nExecStart='+command+'\n'
    with patch('release_tools.subprocess.run',return_value=Mock(returncode=0,stdout=stdout)),patch('release_tools.SUPERVISOR_SHA',sha(runner.read_bytes())):
        report=service_inventory(repo,home)
    assert report['source_service_mapping_confirmed'] is True
    assert 'must-not-export' not in json.dumps(report) and 'ExecStart' not in json.dumps(report)
    assert report['service_control_commands_issued'] is False


def test_service_query_failure_remains_explicit(tmp_path):
    with patch('release_tools.subprocess.run',side_effect=OSError('systemctl unavailable')):
        report=service_inventory(tmp_path,tmp_path)
    assert report['source_service_mapping_confirmed'] is False
    assert len(report['services'])==len(UNITS) and report['limitations']


def test_release_plan_is_review_only_and_detects_changed_staged_content(rehearsal,tmp_path):
    root,new=rehearsal;candidate=tmp_path/'candidate';candidate.mkdir()
    pins={}
    for name,data in new.items():
        p=candidate/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);pins[name]=sha(data)
    report=release_plan(root,candidate,pins,dict(source_service_mapping_confirmed=True))
    assert [r['operation'] for r in report['files']]==['REPLACE','REPLACE','CREATE']
    assert report['live_apply_available'] is False and report['services_changed'] is False
    (candidate/TARGETS[0]).write_bytes(b'changed')
    with pytest.raises(ValueError,match='STAGED_RELEASE_CONTENT_CHANGED'):
        release_plan(root,candidate,pins,dict(source_service_mapping_confirmed=True))


def test_probe_unit_is_bounded_and_cannot_restart_automatically(tmp_path):
    unit=probe_unit(Path(sys.executable),tmp_path/'probe.py')
    assert '--max-ticks 2' in unit and 'Restart=no' in unit and 'TimeoutStartSec=15' in unit
    assert 'UPSTOX' not in unit and 'EnvironmentFile' not in unit


@pytest.mark.parametrize('run_number',[1,2])
def test_staged_closed_probe_starts_and_exits_without_backend(tmp_path,run_number):
    stage=Path(os.environ['HILEGA_RELEASE_STAGE']);script=stage/'closed_application_coordinator_v1.py'
    result=subprocess.run([sys.executable,'-I',str(script),'--watch','--interval','1','--max-ticks','2'],
        cwd=tmp_path,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    rows=[json.loads(x) for x in result.stdout.splitlines()]
    assert len(rows)==2 and all(r['status']=='EXECUTION_COORDINATOR_CLOSED_IN_CODE' for r in rows)
    assert all(r['application_database_opened'] is False and r['token_loaded'] is False for r in rows)
    assert not list(tmp_path.iterdir())


def test_dependency_inventory_does_not_execute_package_initializers(tmp_path):
    from release_tools import direct_dependency_inventory
    package=tmp_path/'synthetic';package.mkdir()
    (package/'__init__.py').write_text("raise AssertionError('Do not execute dependency packages')\n")
    (package/'child.py').write_text('value=1\n')
    report=direct_dependency_inventory({'entry':'from synthetic.child import value\nimport missing_module_xyz\n'},[tmp_path])
    assert report['unresolved_count']==1 and report['package_code_executed'] is False
    assert next(r for r in report['modules'] if r['module']=='synthetic.child')['resolution']=='RESOLVED_WITHOUT_IMPORT'
