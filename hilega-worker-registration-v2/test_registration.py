import hashlib
import json
from pathlib import Path
import pytest
from worker_registration_v1 import load_closed_registration,MODEL
from registration_tools import probe_command,transform,worker_rollback


def document(tmp_path,**updates):
    value=dict(model=MODEL,mode='CLOSED_PREPARATION_ONLY',base_release_manifest_sha256='a'*64,
        production_execution_enabled=False,execution_factory_configured=False);value.update(updates)
    p=tmp_path/'registration.json';raw=json.dumps(value).encode();p.write_bytes(raw)
    return p,hashlib.sha256(raw).hexdigest()


def test_exact_closed_registration_loads_without_execution(tmp_path):
    p,d=document(tmp_path);assert type(load_closed_registration(p,d)).__name__=='ClosedRegistration'


def test_changed_registration_digest_blocks(tmp_path):
    p,d=document(tmp_path)
    with pytest.raises(ValueError,match='REGISTRATION_CHANGED'):load_closed_registration(p,'0'*64)


def test_live_permission_cannot_be_enabled_in_registration(tmp_path):
    p,d=document(tmp_path,production_execution_enabled=True)
    with pytest.raises(ValueError,match='EXACT_CLOSED'):load_closed_registration(p,d)


def test_factory_cannot_be_enabled_in_closed_registration(tmp_path):
    p,d=document(tmp_path,execution_factory_configured=True)
    with pytest.raises(ValueError,match='EXACT_CLOSED'):load_closed_registration(p,d)


def test_unknown_registration_fields_block(tmp_path):
    p,d=document(tmp_path,token='synthetic-unused')
    with pytest.raises(ValueError,match='EXACT_CLOSED'):load_closed_registration(p,d)


def test_unknown_worker_anchor_blocks():
    with pytest.raises(ValueError,match='ANCHOR'):transform('print("unrecognized worker")')


def test_probe_cannot_target_existing_source_service():
    with pytest.raises(ValueError,match='ISOLATED_PROBE'):probe_command(dict(probe_unit='hilega-production-source-worker.service'))


def test_probe_command_is_bounded_and_network_restricted():
    plan=dict(probe_unit='hilega-closed-registration-probe-abcd.service',release_folder='/release',python='/python',
        probe_script='/probe.py',registration='/registration.json',registration_sha256='a'*64)
    command=probe_command(plan)
    assert '--property=RuntimeMaxSec=20' in command and '--property=RestrictAddressFamilies=AF_UNIX' in command
    assert '--user' in command and '--wait' in command and '--collect' in command


def test_registered_worker_rollback_restores_old_bytes(tmp_path):
    result=worker_rollback(tmp_path,b'old',b'new')
    assert (tmp_path/'worker-rollback-rehearsal/worker.py').read_bytes()==b'old'
    assert result['installed_worker_restored'] is False


def test_registration_symlink_is_rejected(tmp_path):
    p,d=document(tmp_path);link=tmp_path/'link.json';link.symlink_to(p)
    with pytest.raises(ValueError,match='REGULAR_PUBLIC'):load_closed_registration(link,d)


def test_package_boundary_prevents_other_regular_package_shadowing(tmp_path):
    import subprocess,sys,os
    from registration_tools import stage_package_boundary
    release=tmp_path/'release';package=release/'backend/market_lab';package.mkdir(parents=True)
    reviewed=tmp_path/'reviewed.txt';reviewed.write_text('"""Synthetic inert package."""\n')
    stage_package_boundary(release,reviewed)
    (package/'hilega_worker_registration_v1.py').write_text("MARKER='BUNDLED'\n")
    other=tmp_path/'other/market_lab';other.mkdir(parents=True);(other/'__init__.py').write_text('')
    command="import sys;sys.path.insert(0,sys.argv[1]);import market_lab.hilega_worker_registration_v1 as m;assert m.MARKER=='BUNDLED';assert m.__file__==sys.argv[2]"
    r=subprocess.run([sys.executable,'-B','-c',command,str(release/'backend'),str(package/'hilega_worker_registration_v1.py')],
        env={'PATH':os.defpath,'PYTHONPATH':str(other.parent),'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=10)
    assert r.returncode==0,r.stderr


def test_package_boundary_collision_is_not_overwritten(tmp_path):
    from registration_tools import stage_package_boundary
    release=tmp_path/'release';package=release/'backend/market_lab';package.mkdir(parents=True)
    (package/'__init__.py').write_text('unexpected')
    reviewed=tmp_path/'reviewed.txt';reviewed.write_text('reviewed')
    with pytest.raises(ValueError,match='PACKAGE_BOUNDARY_COLLISION'):stage_package_boundary(release,reviewed)
    assert (package/'__init__.py').read_text()=='unexpected'
