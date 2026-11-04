import json
import pytest
from bindings import chain,sha,constant
SOURCE='backend/writer.py'
def inputs():
    m=json.dumps(dict(model='HILEGA_OPERATIONAL_LIFECYCLE_PACKAGE_V1',production_execution_enabled=False,order_actions_available=False,runtime={SOURCE:'old','backend/other.py':'unchanged'},modules={'helper.py':'pinned'})).encode()
    c=('EXPECTED_MANIFEST='+repr(sha(m))+'\ndef run():\n    return False\n').encode()
    s=('CLI_SHA='+repr(sha(c))+'\ndef main():\n    return 0\n').encode()
    return m,c,s
def test_all_three_bindings_are_consistent():
    m,c,s=chain(*inputs(),SOURCE,'old','new');assert constant(c.decode(),'EXPECTED_MANIFEST').value==sha(m) and constant(s.decode(),'CLI_SHA').value==sha(c)
def test_unrelated_runtime_and_module_pins_preserved():
    m,_,_=chain(*inputs(),SOURCE,'old','new');m=json.loads(m);assert m['runtime']['backend/other.py']=='unchanged' and m['modules']=={'helper.py':'pinned'}
def test_wrong_old_writer_binding_rejected():
    with pytest.raises(ValueError,match='WRITER_BINDING'):chain(*inputs(),SOURCE,'different','new')
def test_changed_manifest_cannot_be_silently_repinned():
    m,c,s=inputs();m=m+b' '
    with pytest.raises(ValueError,match='CLI_MANIFEST'):chain(m,c,s,SOURCE,'old','new')
def test_changed_cli_cannot_be_silently_repinned():
    m,c,s=inputs();c=c+b'\n'
    with pytest.raises(ValueError,match='SERVICE_CLI'):chain(m,c,s,SOURCE,'old','new')
def test_duplicate_hash_constants_rejected():
    m,c,s=inputs();s+=b'CLI_SHA="extra"\n'
    with pytest.raises(ValueError,match='EXACT_HASH_CONSTANT'):chain(m,c,s,SOURCE,'old','new')
