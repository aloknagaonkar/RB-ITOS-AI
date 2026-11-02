import hashlib
from pathlib import Path
from zipfile import ZipFile
import pytest
from dependency_lock import lock_wheel


def fixture_wheel(tmp_path,version='1.2.3',extra=None):
    p=tmp_path/'synthetic.whl';raw=b'# synthetic wheel source\n'
    with ZipFile(p,'w') as z:
        z.writestr('dotenv/__init__.py',raw)
        z.writestr('python_dotenv.dist-info/METADATA',f'Name: python-dotenv\nVersion: {version}\n')
        if extra:z.writestr(extra,b'x')
    installed=dict(version_matches=True,installed_source_hashes={'dotenv/__init__.py':hashlib.sha256(raw).hexdigest()})
    return p,installed


def test_wheel_match_creates_hash_requirement_without_install(tmp_path):
    p,i=fixture_wheel(tmp_path);r=lock_wheel(p,i)
    assert r['requirement']=='python-dotenv==1.2.3 --hash=sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()
    assert r['package_installed'] is False


def test_wheel_version_mismatch_blocks(tmp_path):
    p,i=fixture_wheel(tmp_path,'other')
    with pytest.raises(ValueError,match='EXACT_DOTENV'):lock_wheel(p,i)


def test_modified_installed_sources_block(tmp_path):
    p,i=fixture_wheel(tmp_path);i['installed_source_hashes']['dotenv/__init__.py']='0'*64
    with pytest.raises(ValueError,match='SOURCES_DIFFER'):lock_wheel(p,i)


def test_wheel_parent_traversal_blocks(tmp_path):
    p,i=fixture_wheel(tmp_path,extra='../outside')
    with pytest.raises(ValueError,match='WHEEL_PATH_INVALID'):lock_wheel(p,i)


def test_wheel_missing_metadata_blocks(tmp_path):
    p=tmp_path/'empty.whl'
    with ZipFile(p,'w') as z:z.writestr('dotenv/a.py','')
    with pytest.raises(ValueError,match='METADATA_REQUIRED'):lock_wheel(p,dict())


def test_unconditional_new_dependency_requires_review(tmp_path):
    p=tmp_path/'dependency.whl'
    with ZipFile(p,'w') as z:z.writestr('pkg.dist-info/METADATA','Name: python-dotenv\nVersion: 1.2.3\nRequires-Dist: unknown\n')
    with pytest.raises(ValueError,match='RUNTIME_DEPENDENCY'):lock_wheel(p,dict())


def test_transitive_review_blocks_additional_external(tmp_path,monkeypatch):
    import dependency_lock as d
    monkeypatch.setattr(d,'build',lambda *a,**k:dict(unresolved_local=[],external_imports=['unapproved'],dynamic_loading_sites=[]))
    # All aliases refer to fixed files checked before graph review.
    paths=['hilega-production-contract-preview/rules.py','hilega-production-real-cash-shadow-gate/gate.py',
        'hilega-production-contract-preview/run.py','hilega-production-cash-observation/analysis.py','hilega-production-cash-observation/run.py']
    pins={}
    for name in paths:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'pass\n');pins[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='UNREVIEWED_EXTERNAL_IMPORT'):d.transitive_review(tmp_path,tmp_path,pins)


def test_transitive_review_blocks_unreviewed_dynamic_site(tmp_path,monkeypatch):
    import dependency_lock as d
    monkeypatch.setattr(d,'build',lambda *a,**k:dict(unresolved_local=[],external_imports=[],
        dynamic_loading_sites=[dict(module='unexpected',call='__import__')]))
    paths=['hilega-production-contract-preview/rules.py','hilega-production-real-cash-shadow-gate/gate.py',
        'hilega-production-contract-preview/run.py','hilega-production-cash-observation/analysis.py','hilega-production-cash-observation/run.py']
    pins={}
    for name in paths:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'pass\n');pins[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='UNREVIEWED_DYNAMIC_LOADER'):d.transitive_review(tmp_path,tmp_path,pins)
