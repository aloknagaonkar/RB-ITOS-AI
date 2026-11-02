import hashlib
from pathlib import Path
import pytest
from assembly import verify,regular
from group1 import proposal,launcher_text
from rehearse import run


def test_proposal_requires_current_supervisor_review(tmp_path):
    with pytest.raises(ValueError,match='SUPERVISOR_REVIEW_REQUIRED'):proposal(tmp_path,tmp_path,'0'*64,{})


def test_proposal_cannot_enable_execution_or_database_rewind(tmp_path):
    p=tmp_path/'scripts';p.mkdir();(p/'hilega_production_simulator_bridge.py').write_text('old')
    r=proposal(tmp_path,tmp_path,'0'*64,dict(approval_hashes_match=True))
    assert r['live_apply_available'] is False and r['new_release_approved'] is False
    assert r['production_execution_enabled'] is False and r['controller_resume_permitted'] is False
    assert r['rollback_policy']['automatic_live_database_rewind'] is False


def test_disposable_state_cannot_reuse_existing_folder(tmp_path):
    out=tmp_path/'existing';out.mkdir()
    with pytest.raises(ValueError,match='NEW_REHEARSAL_DIRECTORY'):run(tmp_path,out)


def test_launcher_is_explicit_and_has_no_environment_activation():
    text=launcher_text();compile(text,'launcher','exec')
    assert '--closed-registration' in text and 'runpy.run_path' in text
    assert 'os.environ' not in text and 'token' not in text.lower()


def test_manifest_detects_changed_runtime_dependency(tmp_path):
    (tmp_path/'RELEASE-MANIFEST.json').write_text('{}');(tmp_path/'module.py').write_text('new')
    with pytest.raises(ValueError,match='RELEASE_FILE_CHANGED'):verify(tmp_path,dict(files={'module.py':hashlib.sha256(b'old').hexdigest()}))


def test_manifest_rejects_untracked_bundle_file(tmp_path):
    (tmp_path/'RELEASE-MANIFEST.json').write_text('{}');(tmp_path/'unexpected.py').write_text('')
    with pytest.raises(ValueError,match='UNMANIFESTED'):verify(tmp_path,dict(files={}))


def test_symlink_cannot_supply_release_input(tmp_path):
    source=tmp_path/'source';source.write_text('');link=tmp_path/'link';link.symlink_to(source)
    with pytest.raises(ValueError,match='REGULAR_RELEASE_INPUT'):regular(link)


def test_nonempty_output_is_not_modified_on_rehearsal_rejection(tmp_path):
    out=tmp_path/'existing';out.mkdir();marker=out/'marker';marker.write_text('retain')
    with pytest.raises(ValueError):run(tmp_path,out)
    assert marker.read_text()=='retain'
