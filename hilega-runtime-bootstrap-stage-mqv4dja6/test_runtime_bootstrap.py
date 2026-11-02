import json
from pathlib import Path
from unittest.mock import patch
import pytest
from market_lab.hilega_execution_port_v1 import adapter as port
from market_lab.hilega_runtime_bootstrap_v1 import RegisteredBootstrap,existing_adapter
from test_provisioning import setup,run
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from runtime_inventory import build


def test_default_gate_precedes_all_bootstrap_io():
    b=RegisteredBootstrap(None,None,None,'/missing/private','invalid',clock=lambda:None)
    with patch('sqlite3.connect',side_effect=AssertionError('no database')):
        assert b.poll()['status']=='EXECUTION_SESSION_FACTORY_CLOSED_IN_CODE'
    assert b.factory is None


def test_missing_adapter_is_not_created(tmp_path):
    p=tmp_path/'absent.sqlite'
    with pytest.raises(ValueError,match='EXISTING_REGULAR'):existing_adapter(p,'x')
    assert not p.exists()


def test_existing_adapter_preflight_is_read_only(flow):
    p=flow['adapter_store'].path;before=p.read_bytes()
    existing_adapter(p,flow['adapter_store'].scope)
    assert p.read_bytes()==before


def test_wrong_account_is_rejected_without_write(flow):
    p=flow['adapter_store'].path;before=p.read_bytes()
    with pytest.raises(ValueError,match='META_CHANGED'):existing_adapter(p,'wrong')
    assert p.read_bytes()==before


def test_bootstrap_uses_committed_signed_context_without_new_store(setup):
    e,_,_,_=setup
    with patch.object(port,'require_live_clearance',return_value=None):result=run(setup)
    folder=Path(result['private_folder']);digest=json.loads((folder/'INTENT.json').read_text())['config_sha256']
    b=RegisteredBootstrap(e['source'],e['adapter_store'],e['path'],folder/'context.json',digest,clock=lambda:e['clock'][0])
    with patch.object(port,'require_live_clearance',return_value=None),patch.object(port.Store,'__init__',side_effect=AssertionError('no new Store')):
        # Exercise verified loader/owner assembly without any broker capture or order transport.
        with patch('market_lab.hilega_execution_session_factory_v1.ExecutionSessionFactory.poll',return_value={'status':'INTERCEPTED'}) as poll:
            assert b.poll()['status']=='INTERCEPTED';assert b.factory is not None;poll.assert_called_once()
            value=b.factory._loader();assert value['seed_request_id']==e['key']
    assert e['send'].call_count==0


def test_changed_public_digest_blocks_before_private_loading(flow):
    e=flow;b=RegisteredBootstrap(e['source'],e['adapter_store'],e['path'],'/missing','bad',clock=lambda:e['clock'][0])
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError,match='PUBLIC_CONTEXT_DIGEST'):b.poll()
    assert b.factory is None


def test_inventory_copies_transitive_flat_module_without_execution(tmp_path):
    source=tmp_path/'source';stage=tmp_path/'stage';source.mkdir();stage.mkdir()
    (source/'closed_application_coordinator_v1.py').write_text('import helper_v1\nraise RuntimeError("must not execute")\n')
    (source/'helper_v1.py').write_text('import json\n')
    result=build(stage,[source]);assert 'helper_v1' in result['modules']
    assert (stage/'helper_v1.py').is_file();assert result['dependency_manifest_fully_reconciled'] is False


def test_inventory_reports_missing_local_runtime(tmp_path):
    stage=tmp_path/'stage';stage.mkdir();result=build(stage,[stage])
    assert 'closed_application_coordinator_v1' in result['unresolved_local']
