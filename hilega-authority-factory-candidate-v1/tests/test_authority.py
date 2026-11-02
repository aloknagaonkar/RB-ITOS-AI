from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import hmac
import pytest
from authority_contract import verify,canonical,digest

NOW=datetime(2026,11,2,8,tzinfo=timezone.utc)
ROOT=b'R'*32


def expected():
    return dict(account_scope='UPSTOX:'+'a'*64,release_sha256='b'*64,policy_sha256='c'*64,
        private_context_sha256='d'*64,authority_id='synthetic-authority',authority_key_sha256='e'*64,
        owner_row_sha256='1'*64,seed_request_id='synthetic-seed',bridge_run_id='synthetic-lease')


def seal(value,key=ROOT):
    value=deepcopy(value);value.pop('signature',None)
    value['signature']=hmac.new(key,canonical(value),hashlib.sha256).hexdigest();return value


def grant(bind=None,now=NOW):
    return seal(dict(model='HILEGA_OFFLINE_AUTHORITY_GRANT_CANDIDATE_V1',issuer_id='synthetic-root',grant_id='synthetic-grant',
        binding=bind or expected(),issued_at=(now-timedelta(seconds=1)).isoformat(),expires_at=(now+timedelta(hours=1)).isoformat(),production_execution_enabled=False))


def test_valid_binding_is_not_execution_permission():
    r=verify(grant(),expected(),{'synthetic-root':ROOT},NOW)
    assert not r['execution_permission'] and not r['production_trust_provisioned']


@pytest.mark.parametrize('field',['account_scope','release_sha256','policy_sha256','private_context_sha256','authority_id','authority_key_sha256','owner_row_sha256','seed_request_id','bridge_run_id'])
def test_every_binding_field_is_exact(field):
    value=grant()
    value['binding'][field]=('UPSTOX:'+'f'*64 if field=='account_scope' else 'f'*64 if field.endswith('sha256') else 'changed')
    with pytest.raises(ValueError,match='BINDING_CHANGED'):verify(seal(value),expected(),{'synthetic-root':ROOT},NOW)


@pytest.mark.parametrize('kind',['expired','future','naive','long'])
def test_time_bounds(kind):
    value=grant()
    if kind=='expired':value['expires_at']=NOW.isoformat()
    if kind=='future':value['issued_at']=(NOW+timedelta(seconds=1)).isoformat()
    if kind=='naive':value['issued_at']=NOW.replace(tzinfo=None).isoformat()
    if kind=='long':value['expires_at']=(NOW+timedelta(days=2)).isoformat()
    with pytest.raises(ValueError):verify(seal(value),expected(),{'synthetic-root':ROOT},NOW)


def test_bad_signature():
    value=grant();value['signature']='0'*64
    with pytest.raises(ValueError,match='SIGNATURE'):verify(value,expected(),{'synthetic-root':ROOT},NOW)


def test_revoked_or_unknown_root():
    with pytest.raises(ValueError,match='UNTRUSTED'):verify(grant(),expected(),{},NOW)


def test_authority_key_cannot_be_its_own_issuer():
    bind=expected();bind['authority_key_sha256']=digest(ROOT)
    with pytest.raises(ValueError,match='INDEPENDENT'):verify(grant(bind),bind,{'synthetic-root':ROOT},NOW)


def test_grant_cannot_enable_production():
    value=grant();value['production_execution_enabled']=True
    with pytest.raises(ValueError,match='CANNOT_ENABLE'):verify(seal(value),expected(),{'synthetic-root':ROOT},NOW)
