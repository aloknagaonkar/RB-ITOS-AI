import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from cache_repair import inventory,protect


def setup_bundle(tmp_path):
    root=tmp_path/'bundle';root.mkdir();(root/'module.py').write_text('VALUE=1\n')
    manifest=dict(files={'module.py':hashlib.sha256((root/'module.py').read_bytes()).hexdigest()})
    (root/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest));return root,manifest


def add_cache(root):
    p=Path(importlib.util.cache_from_source(str(root/'module.py')));p.parent.mkdir();p.write_bytes(b'quarantine-only-cache');return p


def unlock(root):
    root.chmod(0o700)
    for p in root.rglob('*'):p.chmod(0o700 if p.is_dir() else 0o600)


def test_only_cache_with_manifest_source_is_accepted(tmp_path):
    root,m=setup_bundle(tmp_path);p=add_cache(root);rows=inventory(root,m)
    assert rows[0]['source']=='module.py' and rows[0]['path']==p.relative_to(root).as_posix()


def test_unknown_extra_is_never_deleted(tmp_path):
    root,m=setup_bundle(tmp_path);p=root/'unexpected.txt';p.write_text('retain')
    with pytest.raises(ValueError,match='NONCACHE'):inventory(root,m)
    assert p.read_text()=='retain'


def test_changed_manifest_source_blocks_repair(tmp_path):
    root,m=setup_bundle(tmp_path);(root/'module.py').write_text('changed')
    with pytest.raises(ValueError,match='APPROVED_BUNDLE_FILE_CHANGED'):inventory(root,m)


def test_cache_for_unknown_source_blocks_repair(tmp_path):
    root,m=setup_bundle(tmp_path);p=root/'__pycache__';p.mkdir();(p/'unknown.cpython-313.pyc').write_bytes(b'cache')
    with pytest.raises(ValueError,match='CACHE_SOURCE_NOT_IN'):inventory(root,m)


def test_quarantine_preserves_cache_and_source_bytes(tmp_path):
    if os.geteuid()==0:pytest.skip('Read-only protection requires the non-root VM account')
    root,m=setup_bundle(tmp_path);p=add_cache(root);old=p.read_bytes();source=(root/'module.py').read_bytes()
    try:
        r=protect(root,m,tmp_path/'quarantine')
        assert (tmp_path/'quarantine'/r['quarantined'][0]['path']).read_bytes()==old
        assert (root/'module.py').read_bytes()==source and not p.exists()
    finally:unlock(root)


def test_python_import_cannot_regenerate_cache_in_read_only_bundle(tmp_path):
    if os.geteuid()==0:pytest.skip('Read-only protection requires the non-root VM account')
    root,m=setup_bundle(tmp_path)
    try:
        protect(root,m,tmp_path/'quarantine')
        r=subprocess.run([sys.executable,'-c','import sys;sys.path.insert(0,sys.argv[1]);import module;assert module.VALUE==1',str(root)],
            env={'PATH':os.defpath},capture_output=True,text=True,timeout=10)
        assert r.returncode==0,r.stderr
        assert not list(root.rglob('*.pyc'))
    finally:unlock(root)
