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


def test_extracted_exception_is_identical_and_preserves_boundary_behavior():
    import ast,json,math
    root=Path(__file__).resolve().parent
    pins=json.loads((root/'POLICY-PINS.json').read_text())
    tree=ast.parse((root/'runtime_rsi_exception_v1.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef))
    from ast_compat import reviewed_dump
    assert reviewed_dump(node)==pins['exception_function_ast']
    namespace={};exec(compile(tree,'reviewed-exception','exec'),namespace)
    f=namespace['exception_allows']
    assert f('BEARISH','BULLISH',40.01,40.01) is True
    assert f('BEARISH','BULLISH',40,41) is False
    assert f('BULLISH','BEARISH',59.99,59.99) is True
    assert f('BULLISH','BEARISH',60,59) is False
    with pytest.raises(ValueError):f('BULLISH','BEARISH',float('nan'),50)


def wheel_fixture(tmp_path,changed=False,requires=''):
    from types import SimpleNamespace
    from zipfile import ZipFile
    p=tmp_path/'core';p.mkdir();(p/'native.so').write_bytes(b'installed-native')
    wheel=tmp_path/'core.whl'
    with ZipFile(wheel,'w') as z:
        z.writestr('core/native.so',b'changed' if changed else b'installed-native')
        z.writestr('core.dist-info/METADATA','Name: core\nVersion: 1.0\n'+requires)
    dist=SimpleNamespace(metadata={'Name':'core'},version='1.0',requires=[],files=['core/native.so'],locate_file=lambda n:tmp_path/n)
    return wheel,dist


def test_native_wheel_payload_is_verified_without_loading_it(tmp_path):
    from wheel_closure import check_wheel
    wheel,dist=wheel_fixture(tmp_path);result=check_wheel(wheel,dist)
    assert result['installed_python_and_native_payload_match'] is True
    assert 'core/native.so' in result['payload_hashes']


def test_changed_native_payload_blocks_runtime_lock(tmp_path):
    from wheel_closure import check_wheel
    wheel,dist=wheel_fixture(tmp_path,changed=True)
    with pytest.raises(ValueError,match='PAYLOAD_DIFFERS'):check_wheel(wheel,dist)


def test_changed_wheel_requirements_metadata_blocks(tmp_path):
    from wheel_closure import check_wheel
    wheel,dist=wheel_fixture(tmp_path,requires='Requires-Dist: unexpected\n')
    with pytest.raises(ValueError,match='METADATA_DIFFERS'):check_wheel(wheel,dist)


def test_reviewed_ast_format_explicitly_preserves_empty_fields_on_new_python():
    from ast_compat import reviewed_dump
    seen={}
    def modern(node,*,include_attributes=True,show_empty=False):
        seen.update(include_attributes=include_attributes,show_empty=show_empty)
        return 'reviewed'
    assert reviewed_dump(None,dumper=modern)=='reviewed'
    assert seen==dict(include_attributes=False,show_empty=True)


def test_reviewed_ast_format_supports_python_without_show_empty():
    from ast_compat import reviewed_dump
    seen={}
    def legacy(node,*,include_attributes=True):
        seen['include_attributes']=include_attributes
        return 'reviewed'
    assert reviewed_dump(None,dumper=legacy)=='reviewed'
    assert seen==dict(include_attributes=False)
