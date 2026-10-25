import sys,importlib.util
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).parent))
spec=importlib.util.spec_from_file_location('funded_watch_runner',Path(__file__).with_name('run.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_next_boundary_always_newer():
    for t,expected in [('2026-10-26T09:25:00+05:30','09:30'),('2026-10-26T09:29:59+05:30','09:30'),('2026-10-26T09:59:59+05:30','10:00')]:
        now=datetime.fromisoformat(t);n=m.next_boundary(now)
        assert n>now and n.strftime('%H:%M')==expected and n.second==0

def test_atomic_synthetic_exit_preserves_entry_reference(tmp_path):
    p=tmp_path/'source.jsonl';p.touch();m.append_event(p,['ENTRY_BEARISH_ROUTE_B_STRUCTURAL'])
    entry=m.j.b.verified_records(p)[-1]['payload']['decision_timestamp']
    m.append_event(p,['STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'],entry)
    rows=m.j.b.verified_records(p)
    assert len(rows)==2 and m.j.b.accepted(rows[1])[0]['entry_reference_at']==entry

def test_child_environment_keeps_active_db_and_tokens_out(monkeypatch,tmp_path):
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','fixture-not-real');monkeypatch.setenv('HILEGA_PRODUCTION_SIM_DB','active.sqlite')
    env=m.w.child_env(tmp_path,tmp_path/'isolated.sqlite')
    assert 'UPSTOX_ACCESS_TOKEN' not in env and env['HILEGA_PRODUCTION_SIM_DB']==str(tmp_path/'isolated.sqlite')

def test_current_installed_source_matches_new_milestone():m.j.installed()
