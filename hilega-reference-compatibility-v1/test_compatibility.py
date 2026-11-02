from pathlib import Path
import json
from unittest.mock import patch
import pytest
import compatibility as c


@pytest.fixture
def sample(tmp_path):
    repo=tmp_path/'repo';package=tmp_path/'package';repo.mkdir();package.mkdir()
    old=b'class Source:\n    def run_source_once(self,path):\n        return path\n'
    new=b'from market_lab.hilega_exclusive_closed_route_v1 import exclusive_source_guard\nclass Source:\n    @exclusive_source_guard\n    def run_source_once(self,path):\n        return path\n'
    guard=b'value=1\n';old_path=tmp_path/'old.py';old_path.write_bytes(old)
    for name,data in ((c.SOURCE,new),(c.GUARD,guard)):
        p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    helper=package/'helper.py';helper.write_bytes(b'value=1\n')
    runtime=repo/'backend/unchanged.py';runtime.parent.mkdir(exist_ok=True);runtime.write_bytes(b'unchanged=1\n')
    manifest=dict(model='HILEGA_OPERATIONAL_LIFECYCLE_PACKAGE_V1',order_actions_available=False,production_execution_enabled=False,
        modules={'helper.py':c.sha(helper.read_bytes())},runtime={c.SOURCE:c.sha(old),'backend/unchanged.py':c.sha(runtime.read_bytes())})
    raw=json.dumps(manifest).encode();(package/'manifest.json').write_bytes(raw)
    cli=('EXPECTED_MANIFEST='+repr(c.sha(raw))+'\ndef checked():\n    return True\n').encode();(package/'cli.py').write_bytes(cli)
    service=tmp_path/'service.py';service.write_text('CLI_SHA='+repr(c.sha(cli))+'\ndef main():\n    return 0\n')
    with patch.multiple(c,OLD_SOURCE=c.sha(old),NEW_SOURCE=c.sha(new),NEW_GUARD=c.sha(guard)):
        yield repo,package,service,old_path


def test_chain_is_updated_and_unrelated_pins_preserved(sample):
    repo,package,service,old=sample;before=(package/'manifest.json').read_bytes();result=c.prepare(*sample)
    new=result['replacements'];manifest=json.loads(new['manifest.json'])
    assert c.constant(new['cli.py'].decode(),'EXPECTED_MANIFEST').value==c.sha(new['manifest.json'])
    assert c.constant(new['service.py'].decode(),'CLI_SHA').value==c.sha(new['cli.py'])
    assert manifest['runtime'][c.GUARD]==c.NEW_GUARD and manifest['production_execution_enabled'] is False
    assert (package/'manifest.json').read_bytes()==before


def test_unrelated_runtime_change_blocks_refresh(sample):
    repo,package,service,old=sample;(repo/'backend/unchanged.py').write_text('changed=1\n')
    with pytest.raises(ValueError,match='UNRELATED_RUNTIME_MODULE_CHANGED'):c.prepare(*sample)


def test_unrelated_package_change_blocks_refresh(sample):
    repo,package,service,old=sample;(package/'helper.py').write_text('changed=1\n')
    with pytest.raises(ValueError,match='UNRELATED_PACKAGE_MODULE_CHANGED'):c.prepare(*sample)


def test_original_companion_cli_pin_must_match(sample):
    repo,package,service,old=sample;service.write_text("CLI_SHA='wrong'\n")
    with pytest.raises(ValueError,match='ORIGINAL_COMPANION_CLI_PIN_CHANGED'):c.prepare(*sample)


def test_duplicate_hash_constants_are_rejected():
    with pytest.raises(ValueError,match='EXACT_HASH_CONSTANT_REQUIRED'):c.replace_constant("CLI_SHA='a'\nCLI_SHA='b'\n",'CLI_SHA','c')


def test_unapproved_source_hash_is_rejected(sample):
    repo,package,service,old=sample;(repo/c.SOURCE).write_text('different=1\n')
    with pytest.raises(ValueError,match='EXACT_APPROVED_RUNTIME_HASHES_REQUIRED'):c.prepare(*sample)
