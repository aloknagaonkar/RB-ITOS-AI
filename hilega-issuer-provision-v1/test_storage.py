import json,os,stat
from pathlib import Path
import pytest
from storage import provision,status,private,sha


def plan(tmp_path):
    home=tmp_path/'home';home.mkdir(mode=0o700);target=home/'hilega-private/production-issuers'/'account'
    return dict(home=str(home),private_parent=str(target),key_file=str(target/'issuer.key'),registry_file=str(target/('b'*64+'.registry.json')),
        issuer_id='synthetic-issuer',account_scope='UPSTOX:'+'a'*64,release_sha256='b'*64,registry_enabled=False,production_execution_enabled=False)


def make(p,**kwargs):return provision(p,'c'*64,random_bytes=lambda n:b'K'*n,**kwargs)
def interrupted(point):
    def fail(at):
        if at==point:raise RuntimeError('synthetic interruption')
    return fail


def test_key_and_disabled_registry_private_and_verifiable(tmp_path):
    p=plan(tmp_path);r=make(p)
    assert private(Path(p['key_file']))==b'K'*32 and not json.loads(private(Path(p['registry_file'])))['enabled']
    assert stat.S_IMODE(Path(p['key_file']).stat().st_mode)==0o400
    assert r['registry_enabled'] is False and status(p,'c'*64)==r


def test_second_apply_never_replaces_key(tmp_path):
    p=plan(tmp_path);make(p)
    with pytest.raises(ValueError,match='EXISTING_ISSUER'):make(p)
    assert private(Path(p['key_file']))==b'K'*32


def test_after_key_recovery_reuses_same_key_without_generation(tmp_path):
    p=plan(tmp_path)
    with pytest.raises(RuntimeError):make(p,checkpoint=interrupted('AFTER_KEY'))
    before=private(Path(p['key_file']))
    r=provision(p,'c'*64,recover=True,random_bytes=lambda n:(_ for _ in ()).throw(AssertionError('No key generation')))
    assert private(Path(p['key_file']))==before and r['registry_enabled'] is False


def test_after_registry_recovery_is_idempotent(tmp_path):
    p=plan(tmp_path)
    with pytest.raises(RuntimeError):make(p,checkpoint=interrupted('AFTER_REGISTRY'))
    first=provision(p,'c'*64,recover=True);second=provision(p,'c'*64,recover=True)
    assert first==second and status(p,'c'*64)==second


def test_changed_key_blocks_recovery(tmp_path):
    p=plan(tmp_path)
    with pytest.raises(RuntimeError):make(p,checkpoint=interrupted('AFTER_KEY'))
    key=Path(p['key_file']);key.chmod(0o600);key.write_bytes(b'T'*32)
    with pytest.raises(ValueError,match='KEY_CHANGED_OR_INCOMPLETE'):provision(p,'c'*64,recover=True)


def test_enabled_external_registry_is_not_overwritten(tmp_path):
    p=plan(tmp_path);make(p);path=Path(p['registry_file']);value=json.loads(private(path));value['enabled']=True
    path.chmod(0o600);path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='EXTERNAL_REGISTRY_CHANGE'):provision(p,'c'*64,recover=True)
    assert json.loads(path.read_text())['enabled'] is True


def test_intent_without_durable_key_cannot_generate_on_recovery(tmp_path):
    p=plan(tmp_path)
    with pytest.raises(RuntimeError):make(p,checkpoint=interrupted('AFTER_INTENT_BEFORE_KEY'))
    with pytest.raises(ValueError,match='DURABLE_KEY_RECOVERY'):provision(p,'c'*64,recover=True)
    assert not Path(p['key_file']).exists()


def test_symlink_parent_is_rejected(tmp_path):
    p=plan(tmp_path);home=Path(p['home']);elsewhere=tmp_path/'elsewhere';elsewhere.mkdir(mode=0o700);(home/'hilega-private').symlink_to(elsewhere)
    with pytest.raises(ValueError):make(p)
    assert not (elsewhere/'production-issuers').exists()


def test_existing_insecure_parent_is_not_chmodded(tmp_path):
    p=plan(tmp_path);parent=Path(p['home'])/'hilega-private';parent.mkdir(mode=0o755);parent.chmod(0o755)
    with pytest.raises(ValueError,match='PARENT_REQUIRES_REVIEW'):make(p)
    assert stat.S_IMODE(parent.stat().st_mode)==0o755


def test_capture_or_token_key_reuse_is_rejected(tmp_path):
    p=plan(tmp_path)
    with pytest.raises(ValueError,match='INDEPENDENT_RANDOM'):make(p,forbidden=[b'K'*32])
    assert not Path(p['key_file']).exists()
