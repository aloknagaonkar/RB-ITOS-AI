from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import pytest
from api_client import Client
from run import next_boundary

def test_next_boundary_requires_future_completed_bar():
    at=datetime.fromisoformat('2026-10-26T09:25:00+05:30')
    assert next_boundary(at).isoformat()=='2026-10-26T09:30:00+05:30'

@pytest.mark.parametrize('url',['https://api.upstox.com','http://127.0.0.1:8123/path','http://localhost:8123','http://127.0.0.1:8123?x=1','http://u:p@127.0.0.1:8123'])
def test_remote_or_nonisolated_target_rejected(tmp_path,url):
    with pytest.raises(ValueError,match='PRIVATE_LOOPBACK_ONLY'):Client(url,tmp_path/'key',tmp_path,{})

def test_installed_cli_uses_isolated_port_and_token_file(tmp_path,monkeypatch):
    captured=[]
    def fake(args,**kwargs):
        captured.append((args,kwargs));return SimpleNamespace(returncode=0,stdout='{"model":"fixture"}')
    monkeypatch.setattr('api_client.subprocess.run',fake)
    client=Client('http://127.0.0.1:43210',tmp_path/'key',tmp_path,{'PATH':'/bin'})
    rc,data=client.cli('status');args,kw=captured[0]
    assert rc==0 and data['model']=='fixture'
    assert args[args.index('--base-url')+1]=='http://127.0.0.1:43210'
    assert '--token-file' in args and kw['cwd']==tmp_path
    assert 'UPSTOX_ACCESS_TOKEN' not in kw['env']

def test_cli_error_does_not_print_arbitrary_stderr(tmp_path,monkeypatch):
    monkeypatch.setattr('api_client.subprocess.run',lambda *a,**k:SimpleNamespace(returncode=2,stdout='not-json',stderr='sensitive response'))
    c=Client('http://127.0.0.1:43210',tmp_path/'key',tmp_path,{})
    with pytest.raises(RuntimeError,match='CONTROL_CLI_RESPONSE_NOT_JSON'):c.cli('status')
