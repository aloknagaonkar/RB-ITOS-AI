from datetime import datetime,timedelta,timezone
from copy import deepcopy
from market_lab.hilega_active_live_marks_v1 import project
from hilega_policy_live.active_marks import requested_keys

NOW=datetime(2026,10,21,5,0,tzinfo=timezone.utc)
def inputs():
    dashboard=dict(trades=[dict(direction='BULLISH',status='ACTIVE',expiry='2026-10-27',signal_boundary='2026-10-21T09:25:00+05:30',
        legs=[dict(instrument_key='NSE_FO|1',entry_open=100,latest_close=105)])])
    snapshot=dict(generated_at=NOW.isoformat(),stream_connected=True,quotes={'NSE_FO|1':dict(
        feed_timestamp=NOW.isoformat(),ltp=110,bid=109,ask=111,bid_quantity=130,lot_size=65,expiry='2026-10-27')})
    return dashboard,snapshot

def test_separate_indicative_and_exit_estimate():
    d,s=inputs();original=deepcopy(d);q=project(d,s,NOW)['quotes'][0]
    assert q['indicative_one_lot_pnl']==650
    assert q['estimated_exit_one_lot_pnl']==585
    assert d==original and d['trades'][0]['legs'][0]['latest_close']==105

def test_closed_trade_has_no_live_override():
    d,s=inputs();d['trades'][0]['status']='CLOSED'
    assert project(d,s,NOW)['quotes']==[]

def test_stale_quiet_leg_does_not_get_snapshot_timestamp():
    d,s=inputs();s['quotes']['NSE_FO|1']['feed_timestamp']=(NOW-timedelta(seconds=11)).isoformat()
    q=project(d,s,NOW)['quotes'][0]
    assert q['status']=='STALE_OR_UNAVAILABLE' and q['indicative_points'] is None

def test_dead_publisher_disables_marks():
    d,s=inputs();s['generated_at']=(NOW-timedelta(seconds=11)).isoformat()
    assert project(d,s,NOW)['quotes'][0]['estimated_exit_points'] is None

def test_disconnected_feed_disables_marks():
    d,s=inputs();s['stream_connected']=False
    assert project(d,s,NOW)['quotes'][0]['indicative_points'] is None

def test_future_quote_rejected():
    d,s=inputs();s['quotes']['NSE_FO|1']['feed_timestamp']=(NOW+timedelta(seconds=1)).isoformat()
    assert project(d,s,NOW)['quotes'][0]['indicative_points'] is None

def test_crossed_book_rejected_but_ltp_separate():
    d,s=inputs();s['quotes']['NSE_FO|1']['bid']=112
    q=project(d,s,NOW)['quotes'][0]
    assert q['estimated_exit_points'] is None and q['indicative_points']==10

def test_insufficient_depth_not_whole_lot_exit():
    d,s=inputs();s['quotes']['NSE_FO|1']['bid_quantity']=1
    q=project(d,s,NOW)['quotes'][0]
    assert q['estimated_exit_points']==9 and q['estimated_exit_one_lot_pnl'] is None

def test_wrong_expiry_rejects_marks():
    d,s=inputs();s['quotes']['NSE_FO|1']['expiry']='2026-10-20'
    q=project(d,s,NOW)['quotes'][0]
    assert q['indicative_points'] is None and q['indicative_one_lot_pnl'] is None

def test_past_session_not_subscribed():
    d,s=inputs();d['trades'][0]['signal_boundary']='2026-10-20T09:25:00+05:30'
    assert project(d,s,NOW)['quotes']==[]

def test_missing_lot_preserves_points_without_inventing_rupees():
    d,s=inputs();s['quotes']['NSE_FO|1']['lot_size']=None
    q=project(d,s,NOW)['quotes'][0]
    assert q['indicative_points']==10 and q['indicative_one_lot_pnl'] is None

def test_subscription_requests_expire():
    request=dict(requested_at=NOW.isoformat(),instrument_keys=['NSE_FO|1'])
    assert requested_keys(request,NOW)=={'NSE_FO|1'}
    assert not requested_keys(request,NOW+timedelta(seconds=31))

def test_future_request_rejected():
    assert not requested_keys(dict(requested_at=(NOW+timedelta(seconds=1)).isoformat(),instrument_keys=['NSE_FO|1']),NOW)
