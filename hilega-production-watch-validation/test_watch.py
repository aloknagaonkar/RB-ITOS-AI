import importlib.util,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
spec=importlib.util.spec_from_file_location('watch_validation_runner',Path(__file__).with_name('run.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_child_environment_excludes_credentials_and_active_db(monkeypatch,tmp_path):
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','fixture-not-a-real-token')
    monkeypatch.setenv('HILEGA_PRODUCTION_CONTROL_TOKEN','fixture-control')
    monkeypatch.setenv('HILEGA_PRODUCTION_SIM_DB','active.sqlite')
    env=m.child_env(tmp_path,tmp_path/'isolated.sqlite')
    assert 'UPSTOX_ACCESS_TOKEN' not in env
    assert 'HILEGA_PRODUCTION_CONTROL_TOKEN' not in env
    assert env['HILEGA_PRODUCTION_SIM_DB']==str(tmp_path/'isolated.sqlite')
    assert env['HILEGA_PRODUCTION_WORKSPACE_MODE']=='SIMULATION_ONLY'

def test_synthetic_append_has_valid_original_reader_chain(tmp_path):
    p=tmp_path/'source.jsonl';p.touch()
    m.append(p,['PATH1_ARMED_RSI_CROSS_EMA3_UP'])
    m.append(p,['ENTRY_BEARISH_ROUTE_B_STRUCTURAL'])
    rows=m.j.b.verified_records(p)
    assert len(rows)==2 and rows[1]['previous_hash']==rows[0]['record_hash']
    assert m.j.b.accepted(rows[0])==[]
    assert m.j.b.accepted(rows[1])[0]['direction']=='BEARISH'

def test_latest_ignores_partial_log_line(tmp_path):
    p=tmp_path/'worker.log';p.write_text('{"status":"ready"}\n{')
    assert m.latest(p)=={'status':'ready'}

def test_dependencies_match_installed_health_milestone():m.j.installed()
