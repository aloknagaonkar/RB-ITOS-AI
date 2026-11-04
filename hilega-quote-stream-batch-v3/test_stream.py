from datetime import date,datetime,timezone,timedelta
import pytest
from quote_core import INDEX,basket,decode,valid,stamp
NOW=datetime(2026,11,3,6,30,tzinfo=timezone.utc)
META={'NSE_FO|1':dict(instrument_key='NSE_FO|1',expiry='2026-11-05',strike_price=25000,instrument_type='CE',lot_size=65,underlying_key=INDEX)}
def feed(at=NOW):
    return dict(currentTs=str(int(at.timestamp()*1000)),feeds={'NSE_FO|1':dict(fullFeed=dict(marketFF=dict(ltpc=dict(ltp=100,ltt=str(int(at.timestamp()*1000))),marketLevel=dict(bidAskQuote=[dict(bidP=99,askP=101,bidQ='65',askQ='130')]))))})
def test_real_full_feed_shape_decodes_depth_and_int64_quantities():
    q=decode(feed(),META)['NSE_FO|1'];assert q['bid_quantity']==65 and valid(q,NOW)
def test_stale_feed_cannot_be_made_fresh_by_snapshot_clock():
    q=decode(feed(NOW-timedelta(seconds=11)),META)['NSE_FO|1'];assert not valid(q,NOW)
def test_future_feed_rejected():assert not valid(decode(feed(NOW+timedelta(seconds=1)),META)['NSE_FO|1'],NOW)
def test_feed_heartbeat_without_instrument_does_not_refresh_quote():assert decode(dict(currentTs=str(int(NOW.timestamp()*1000)),feeds={}),META)=={}
def test_naive_timestamp_rejected():
    with pytest.raises(ValueError,match='NAIVE'):stamp('2026-11-03T12:00:00')
def test_crossed_book_rejected():
    q=decode(feed(),META)['NSE_FO|1'];q.update(bid=102,ask=101);assert not valid(q,NOW)
def test_zero_depth_rejected():
    q=decode(feed(),META)['NSE_FO|1'];q['ask_quantity']=0;assert not valid(q,NOW)
def test_unrequested_feed_not_added():assert decode(feed(),{})=={}
def contracts():
    return [dict(instrument_key=f'NSE_FO|{n}{side}',expiry='2026-11-05',strike_price=24900+n*50,instrument_type=side,lot_size=65,underlying_key=INDEX,exchange='NSE',segment='NSE_FO') for n in range(5) for side in ('CE','PE')]
def test_exact_paired_atm_basket():
    b=basket(contracts(),25000,date(2026,11,3));assert len(b)==10 and {x['instrument_type'] for x in b.values()}=={'CE','PE'}
def test_duplicate_contract_is_not_arbitrarily_selected():
    c=contracts();c.append(dict(c[0]))
    with pytest.raises(ValueError,match='AMBIGUOUS'):basket(c,25000,date(2026,11,3))
def test_missing_lot_is_not_guessed():
    c=contracts();c[0]['lot_size']=None
    with pytest.raises(ValueError,match='METADATA'):basket(c,25000,date(2026,11,3))
def test_incomplete_pair_basket_blocks():
    with pytest.raises(ValueError,match='PAIRED'):basket(contracts()[:-1],25000,date(2026,11,3))


def test_saturday_defers_even_during_regular_clock_hours():
    from quote_core import session_preflight
    assert session_preflight(datetime.fromisoformat('2026-10-31T11:00:00+05:30'))['status']=='WEEKEND'
def test_after_hours_utc_converts_to_ist_without_network():
    from quote_core import session_preflight
    value=session_preflight(datetime.fromisoformat('2026-11-03T14:56:32+00:00'))
    assert value['status']=='AFTER_SESSION_CLOSE' and not value['clock_window_open']
def test_exact_open_is_allowed_by_clock_gate():
    from quote_core import session_preflight
    assert session_preflight(datetime.fromisoformat('2026-11-03T09:15:00+05:30'))['clock_window_open']
def test_exact_close_is_deferred():
    from quote_core import session_preflight
    assert session_preflight(datetime.fromisoformat('2026-11-03T15:30:00+05:30'))['status']=='AFTER_SESSION_CLOSE'
def test_near_close_cannot_start_long_qualification():
    from quote_core import session_preflight
    assert session_preflight(datetime.fromisoformat('2026-11-03T15:29:00+05:30'),180)['status']=='INSUFFICIENT_SESSION_TIME_FOR_VALIDATION'
def test_preopen_is_deferred():
    from quote_core import session_preflight
    assert session_preflight(datetime.fromisoformat('2026-11-03T09:14:59+05:30'))['status']=='BEFORE_SESSION_OPEN'


def test_successor_driver_is_exact_not_arbitrary(tmp_path):
    from successor import status_driver,MODEL
    p=dict(model=MODEL,repo=str(tmp_path),production_execution_enabled=False,status_driver=str(tmp_path/'hilega-warmup-prevention-deploy-v1/manage.py'))
    assert status_driver(tmp_path,p)==tmp_path/'hilega-warmup-prevention-deploy-v1/manage.py'
    p['status_driver']='/tmp/other.py'
    with pytest.raises(ValueError,match='UNAPPROVED'):status_driver(tmp_path,p)
def test_predecessor_model_cannot_silently_select_successor(tmp_path):
    from successor import status_driver
    with pytest.raises(ValueError,match='SUCCESSOR'):status_driver(tmp_path,dict(model='old',repo=str(tmp_path),production_execution_enabled=False))
def test_status_cannot_pass_if_controller_resumed():
    from successor import validate_status
    v=dict(phase='CLOSED_WARMUP_PREVENTION_RUNNING',prevention_deployed=True,controller_resumed=False,production_execution_enabled=False)
    assert validate_status(v)
    v['controller_resumed']=True
    with pytest.raises(ValueError,match='NOT_VERIFIED'):validate_status(v)
