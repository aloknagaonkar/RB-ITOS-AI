from datetime import datetime,timedelta
import copy
from market_lab.operational_readiness_v1 import evaluate,phase

def inputs(stamp='2026-10-13T10:13:58+05:30'):
 now=datetime.fromisoformat(stamp)
 live={'active_strategy_id':'HILEGA_V2_ALIGNMENT_DUAL_EXIT','current_session_ready':True,'current':{'session_date':'2026-10-13','last_completed_bar':'2026-10-13T10:05:00+05:30'}}
 sb={'worker':{'running':True,'armed':True,'session_date':'2026-10-13','strategy_id':'HILEGA_V2_ALIGNMENT_DUAL_EXIT','kill_switch':False,'uncertain_requests':0}}
 warm={'ready':True,'session_date':'2026-10-13','issues':[],'analytics_probe':{'status':'PASS','checked_at':now.isoformat()}};local={'latest_decision':'2026-10-13T10:10:00+05:30','missing_dispatch':[]};health={'timestamp':now.isoformat(),'components':{'hilega':'OK','midpoint':'OK'}}
 return now,live,sb,warm,local,health

def setup_module():
 import os
 os.environ.update(LIVE_SHADOW_STRATEGY='HILEGA_V2_ALIGNMENT_DUAL_EXIT',UPSTOX_ACCESS_TOKEN='TEST',UPSTOX_SANDBOX_ACCESS_TOKEN='TEST')

def test_five_minute_cadence_not_90_second_decision_age():
 assert evaluate(*inputs(),{})['status']=='READY'

def test_pre_market_does_not_require_current_bootstrap():
 a=list(inputs('2026-10-13T09:10:00+05:30'));a[1]['current_session_ready']=False;a[1]['current']={};a[4]={};a[5]={}
 assert evaluate(*a,{})['status']=='READY'

def test_stale_heartbeat_detected_and_recovery_persists():
 a=list(inputs());a[5]['timestamp']=(a[0]-timedelta(seconds=61)).isoformat();bad=evaluate(*a,{})
 assert bad['status']=='NOT_READY';assert any(x['id']=='HEARTBEAT' and x['active'] for x in bad['alerts'])
 again=evaluate(*a,bad);assert len(again['notifications'])==len(bad['notifications'])
 ok=evaluate(*inputs(),again);assert any(x['kind']=='RECOVERY' for x in ok['notifications']);assert ok['status']=='READY'

def test_exact_warmup_error_and_backoff_are_visible():
 a=list(inputs());a[3]['ready']=False;a[3]['issues']=[{'message':'Warmup 2026-10-12: incomplete exact 5m candle 15:25; missing 1m: 15:29'}];a[5]['components']['hilega']='RETRY_BACKOFF'
 r=evaluate(*a,{});assert any('15:29' in x['message'] for x in r['alerts']);assert r['status']=='NOT_READY'

def test_no_bootstrap_before_first_boundary_grace():
 a=list(inputs('2026-10-13T09:19:00+05:30'));a[1]['current_session_ready']=False;a[1]['current']={};a[4]={}
 assert not any(x['id']=='BOOTSTRAP' for x in evaluate(*a,{})['alerts'])

def test_dispatch_issue_stays_unresolved_until_outcome():
 a=list(inputs());a[4]['missing_dispatch']=['2026-10-13T09:22:00+05:30'];bad=evaluate(*a,{})
 a[4]['missing_dispatch']=[];still=evaluate(*a,bad);assert still['status']=='NOT_READY'
 a[4]['resolved_dispatch']=['2026-10-13T09:22:00+05:30'];assert evaluate(*a,still)['status']=='READY'

def test_off_hours_do_not_falsely_recover():
 a=list(inputs());a[5]['components']['hilega']='RETRY_BACKOFF';bad=evaluate(*a,{})
 a[0]=datetime.fromisoformat('2026-10-13T18:00:00+05:30');r=evaluate(*a,bad)
 assert any(x['active'] for x in r['alerts']);assert len(r['notifications'])==len(bad['notifications'])

def test_bad_analytics_auth_is_not_ready():
 a=list(inputs());a[3]['analytics_probe']['status']='FAIL'
 assert any(x['id']=='ANALYTICS_TOKEN' for x in evaluate(*a,{})['alerts'])

def test_wrong_sandbox_session_is_not_ready():
 a=list(inputs());a[2]['worker']['session_date']='2026-10-12'
 assert any(x['id']=='SANDBOX' for x in evaluate(*a,{})['alerts'])

def test_after_cutoff_does_not_expect_new_strategy_candles():
 a=list(inputs('2026-10-13T15:10:00+05:30'));a[1]['current']['last_completed_bar']='2026-10-13T14:50:00+05:30';a[4]['latest_decision']='2026-10-13T14:55:00+05:30'
 assert evaluate(*a,{})['status']=='READY'
