from datetime import datetime,timezone,timedelta
from window_review import assess
NOW=datetime(2026,11,2,5,tzinfo=timezone.utc)
def run(**kw):
    return assess(kw.get('control',dict(mode='PAUSED',session_date='2026-11-02')),kw.get('counts',{'plans':0}),
        kw.get('allocation',dict(required=True)),now=NOW,bridge_healthy=kw.get('healthy',True),route=kw.get('route','SIMULATOR'))
def test_native_resume_dependency():assert 'NATIVE_RESUME_REQUIRES_SYNTHETIC_FUNDS' in run()['blockers']
def test_paused_required():assert 'PAUSED_CONTROLLER_REQUIRED' in run(control={})['blockers']
def test_current_session():assert 'CURRENT_CONTROLLER_SESSION_REQUIRED' in run(control=dict(mode='PAUSED',session_date='2026-10-30'))['blockers']
def test_nonempty():assert 'NONEMPTY_LIFECYCLE_REQUIRES_REVIEW' in run(counts={'plans':1})['blockers']
def test_health():assert 'CURRENT_HEALTHY_BRIDGE_REQUIRED' in run(healthy=False)['blockers']
def test_missing_allocation():assert 'SIM_ALLOCATION_CONFIG_UNAVAILABLE' in run(allocation=None)['blockers']
def test_stale_funds():assert 'NATIVE_RESUME_SYNTHETIC_FUNDS_STALE' in run(allocation=dict(required=True,funds=dict(at=(NOW-timedelta(seconds=31)).isoformat())))['blockers']
def test_never_authorizes_even_when_checks_pass():
    x=run(allocation=dict(required=True,funds=dict(at=NOW.isoformat())))
    assert not x['blockers'] and not x['live_apply_available'] and not x['controller_resumed']

def test_preparation_does_not_require_synthetic_funds():assert not run(route="PREPARATION_ONLY",allocation=None)["blockers"]
def test_unverified_route_blocks():assert "VERIFIED_EXECUTION_ROUTE_REQUIRED" in run(route="OTHER")["blockers"]
