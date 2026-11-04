from datetime import timedelta
import hashlib,hmac,json,os,signal,uuid
from pathlib import Path
import pytest
from test_bootstrap import approve,run,folder
from test_provisioning import setup
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from handoff import Approval,MODEL,canonical,sha,propose,apply,recover,intent_path,read_handoff
from market_lab.hilega_production_bridge_health_v1 import claim
from market_lab.hilega_exclusive_closed_route_v1 import TABLE
from market_lab.hilega_execution_port_v1 import adapter as port

ROOT=b'HANDOFF-INDEPENDENT-SYNTHETIC-ROOT-0000'


def prepared(setup,rebind=True):
    e,parent,pin,secret=setup;run(setup,approve(setup));p=folder(parent)/'context.json'
    if rebind:e['source'].run_id=claim(e['source'].s)
    release=Path(os.environ['HILEGA_PACKAGE_B_BUNDLE'])
    proposal=propose(e['source'],e['adapter_store'],pin,e['path'],p,sha(p.read_bytes()),release,sha((release/'RELEASE-MANIFEST.json').read_bytes()),uuid.uuid4().hex,lambda:e['clock'][0])
    return proposal


def approval(setup,p,operation=None,roots=None):
    e=setup[0];b=p['binding'];roots=roots if roots is not None else {'synthetic':ROOT}
    op=operation or ('ATTACH_DISABLED_CONTEXT' if b['from_run_id']==b['to_run_id'] else 'REBIND_DISABLED_LEASE')
    g=dict(model=MODEL,operation=op,issuer_id='synthetic',binding=b,issued_at=e['clock'][0].isoformat(),expires_at=(e['clock'][0]+timedelta(seconds=50)).isoformat(),order_transport_permission=False,production_execution_enabled=False)
    g['signature']=hmac.new(roots['synthetic'],canonical(g),hashlib.sha256).hexdigest()
    return Approval(g,b,lambda:roots,lambda:e['clock'][0])


def execute(setup,p,a,**kw):
    e,parent,pin,secret=setup
    return apply(e['source'],e['adapter_store'],pin,e['path'],p,a,lambda:e['clock'][0],**kw)


def restore(setup,p):
    e,parent,pin,secret=setup
    return recover(e['source'],e['adapter_store'],pin,e['path'],intent_path(p),approval(setup,p,'RECOVER_DISABLED_REBIND'),lambda:e['clock'][0])


def unchanged(setup,p):
    e,parent,pin,secret=setup
    assert e['store'].control()['mode']=='PAUSED' and e['send'].call_count==0 and secret.call_count==1
    with e['store'].db() as db:assert db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0]==p['cursor']
    cfg=json.loads(Path(p['binding']['context_path']).read_text())
    assert all(sha(Path(cfg[k+'_file']).read_bytes())==p['protected'][k] for k in p['protected'])
    with e['adapter_store'].tx() as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]==0
    with pytest.raises(port.GateClosed):port.require_live_clearance()


@pytest.mark.parametrize('rebind',[False,True])
def test_signed_handoff_and_receipt_consumer(setup,rebind):
    p=prepared(setup,rebind);out=execute(setup,p,approval(setup,p));e,parent,pin,secret=setup
    result=read_handoff(e['source'],e['adapter_store'],pin,e['path'],out['receipt'],out['receipt_sha256'],lambda:e['clock'][0])
    assert result['execution_permission'] is False and result['ready_for_local_review'] is True
    unchanged(setup,p)


@pytest.mark.parametrize('point',['AFTER_INTENT','BEFORE_OWNER_COMMIT','AFTER_OWNER_COMMIT','AFTER_CONTEXT_REPLACE'])
def test_interrupted_commit_explicit_recovery(setup,point):
    p=prepared(setup)
    def fail(at):
        if at==point:raise RuntimeError('checkpoint interruption')
    with pytest.raises(RuntimeError):execute(setup,p,approval(setup,p),checkpoint=fail)
    assert restore(setup,p)['new_key_created'] is False
    assert restore(setup,p)['new_key_created'] is False
    unchanged(setup,p)


@pytest.mark.parametrize('point',['AFTER_OWNER_COMMIT','AFTER_CONTEXT_REPLACE'])
def test_actor_sigkill_and_explicit_recovery(setup,point):
    p=prepared(setup);a=approval(setup,p);pid=os.fork()
    if pid==0:
        def kill(at):
            if at==point:os.kill(os.getpid(),signal.SIGKILL)
        try:execute(setup,p,a,checkpoint=kill)
        except BaseException:os._exit(91)
        os._exit(92)
    _,status=os.waitpid(pid,0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
    restore(setup,p);unchanged(setup,p)


def test_unsigned_new_lease_cannot_reuse_approval(setup):
    p=prepared(setup);a=approval(setup,p);setup[0]['source'].run_id='unapproved-next-lease'
    with pytest.raises(ValueError):execute(setup,p,a)
    assert not intent_path(p).exists()


def test_expired_approval_creates_no_intent(setup):
    p=prepared(setup);a=approval(setup,p);setup[0]['clock'][0]+=timedelta(seconds=51)
    with pytest.raises(ValueError,match='EXPIRED'):execute(setup,p,a)
    assert not intent_path(p).exists()


def test_revoked_issuer_rolls_back_owner(setup):
    p=prepared(setup);roots={'synthetic':ROOT};a=approval(setup,p,roots=roots)
    def revoke(at):
        if at=='BEFORE_OWNER_COMMIT':roots.clear()
    with pytest.raises(ValueError,match='NOT_TRUSTED'):execute(setup,p,a,checkpoint=revoke)
    with setup[0]['store'].db() as db:assert db.execute('SELECT data FROM '+TABLE+' WHERE id=1').fetchone()[0]==p['old_owner']
    unchanged(setup,p)


def test_external_context_edit_is_not_overwritten(setup):
    p=prepared(setup)
    def fail(at):
        if at=='AFTER_OWNER_COMMIT':raise RuntimeError('interrupted')
    with pytest.raises(RuntimeError):execute(setup,p,approval(setup,p),checkpoint=fail)
    path=Path(p['binding']['context_path']);raw=path.read_bytes()+b' '
    path.write_bytes(raw)
    with pytest.raises(ValueError,match='EXTERNAL_HANDOFF_CHANGE'):restore(setup,p)
    assert path.read_bytes()==raw


def test_capture_key_cannot_approve_handoff(setup):
    p=prepared(setup);a=approval(setup,p,roots={'synthetic':bytes.fromhex(setup[2]['key'])})
    with pytest.raises(ValueError,match='INDEPENDENT'):execute(setup,p,a)
    assert not intent_path(p).exists()
