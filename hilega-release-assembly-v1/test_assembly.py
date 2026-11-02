import hashlib
import json
from pathlib import Path
import pytest
from assembly import place,verify,disposable_rollback,assemble


def test_relative_escape_rejected(tmp_path):
    with pytest.raises(ValueError,match='RELATIVE_RELEASE_PATH'):place(tmp_path,'../escape',b'x',{})


def test_conflicting_input_cannot_overwrite(tmp_path):
    files={};place(tmp_path,'a.py',b'a',files)
    with pytest.raises(ValueError,match='COLLISION'):place(tmp_path,'a.py',b'b',files)
    assert (tmp_path/'a.py').read_bytes()==b'a'


def test_identical_duplicate_has_one_manifest_entry(tmp_path):
    files={};place(tmp_path,'a.py',b'a',files);place(tmp_path,'a.py',b'a',files);assert len(files)==1


def test_tamper_is_detected(tmp_path):
    files={};place(tmp_path,'a.py',b'a',files);(tmp_path/'RELEASE-MANIFEST.json').write_text('{}');(tmp_path/'a.py').write_bytes(b'b')
    with pytest.raises(ValueError,match='FILE_CHANGED'):verify(tmp_path,dict(files=files))


def test_unmanifested_file_blocks(tmp_path):
    (tmp_path/'RELEASE-MANIFEST.json').write_text('{}');(tmp_path/'extra.py').write_text('')
    with pytest.raises(ValueError,match='UNMANIFESTED'):verify(tmp_path,dict(files={}))


def test_symlink_input_is_rejected(tmp_path):
    actual=tmp_path/'actual';actual.write_bytes(b'x');(tmp_path/'link').symlink_to(actual)
    with pytest.raises(ValueError,match='REGULAR_RELEASE'):verify(tmp_path,dict(files={'link':hashlib.sha256(b'x').hexdigest()}))


def test_disposable_rollback_does_not_certify_live_runtime(tmp_path):
    r=disposable_rollback(tmp_path);assert r['status']=='DISPOSABLE_FILE_ROLLBACK_PASS'
    assert r['actual_runtime_rollback_tested'] is False and r['live_databases_restored'] is False


def test_existing_destination_is_never_overwritten(tmp_path):
    dest=tmp_path/'release';dest.mkdir()
    with pytest.raises(ValueError,match='NEW_RELEASE_DIRECTORY'):assemble(tmp_path,tmp_path,{}, {},None,{},dest)
