from datetime import datetime,timedelta,timezone
import pytest
from adoption_contract import authority_request,seed_handoff
NOW=datetime(2026,11,2,8,tzinfo=timezone.utc)
def intent():return authority_request('UPSTOX:'+'a'*64,'b'*64)
def seed():return dict(account_scope='UPSTOX:'+'a'*64,release_sha256='b'*64,signal_at=NOW.isoformat(),resumed_at=(NOW-timedelta(seconds=1)).isoformat(),state='PREPARED',order_id=None,attempt_count=0,receipt_count=0,owner_exists=False,binding_verified=True,cash_signature_verified=True,source_cursor_verified=True,context_digest='c'*64,seed_request_id='synthetic-seed',bridge_run_id='synthetic-lease',source_sequence=1,source_record_hash='e'*64)
def test_public_request_contains_no_authority():assert intent()['authority_created'] is False and not intent()['live_arming_permitted']
def test_secret_material_cannot_enter_public_descriptor():
    with pytest.raises(ValueError,match='PUBLIC_AUTHORITY_DESCRIPTOR_ONLY'):authority_request('UPSTOX:'+'a'*64,'b'*64,{'key':'secret'})
def test_fresh_verified_seed_remains_review_only():
    x=seed_handoff(intent(),seed(),now=NOW);assert not x['owner_commit_permitted'] and not x['production_execution_enabled']
def test_stale_seed_rejected():
    with pytest.raises(ValueError,match='FRESH_POST_RESUME_SEED_REQUIRED'):seed_handoff(intent(),seed(),now=NOW+timedelta(seconds=61))
def test_existing_attempt_rejected():
    s=seed();s['attempt_count']=1
    with pytest.raises(ValueError,match='UNSENT_DISABLED_REQUEST_REQUIRED'):seed_handoff(intent(),s,now=NOW)
def test_cross_account_rejected():
    s=seed();s['account_scope']='UPSTOX:'+'d'*64
    with pytest.raises(ValueError,match='SEED_ACCOUNT_OR_RELEASE_CHANGED'):seed_handoff(intent(),s,now=NOW)
