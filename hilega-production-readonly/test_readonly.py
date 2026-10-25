import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('readonly',Path(__file__).with_name('run.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def response(data):return {'status':'success','data':data}
def snapshot(q):
 return {'session_date':'2026-10-23','checks':{'positions':{'status':'PASS','rows':[{'instrument_token':'NSE_FO|1','product':'I','quantity':q}]}}}

def test_flat_detected_without_false_attribution():
 e=m.changes(snapshot(65),snapshot(0))[0]
 assert e['status']=='BROKER_POSITION_NOW_FLAT'
 assert e['application_state_updated'] is False

def test_partial_exit():
 assert m.changes(snapshot(130),snapshot(65))[0]['status']=='BROKER_POSITION_REDUCED'

def test_missing_row_not_flat():
 after=snapshot(0);after['checks']['positions']['rows']=[]
 assert m.changes(snapshot(65),after)[0]['status']=='POSITION_ROW_APPEARED_OR_MISSING'

def test_first_sample_not_exit():
 assert m.changes(None,snapshot(0))[0]['status']=='BASELINE_ONLY'

def test_different_day_not_exit():
 old=snapshot(65);old['session_date']='2026-10-22'
 assert m.changes(old,snapshot(0))[0]['status']=='BASELINE_ONLY'

def test_failed_positions_unknown():
 after=snapshot(0);after['checks']['positions']={'status':'FAIL'}
 assert m.changes(snapshot(65),after)[0]['status']=='UNKNOWN'

def test_negative_position_not_silently_flat():
 assert m.changes(snapshot(65),snapshot(-65))[0]['status']=='POSITION_CHANGE_REQUIRES_RECONCILIATION'

def test_sensitive_fields_removed():
 r=m.sanitize(response([{'instrument_token':'NSE_FO|1','product':'I','quantity':65,'user_id':'secret','access_token':'secret'}]),'positions')
 assert 'secret' not in str(r)

def test_profile_never_saved():
 assert m.sanitize(response({'name':'secret','email':'secret'}),'profile')=={'status':'PASS'}

def test_malformed_quantity_fails():
 assert m.sanitize(response([{'instrument_token':'NSE_FO|1','product':'I','quantity':'bad'}]),'positions')['status']=='FAIL'

def test_error_body_not_logged():
 assert 'secret' not in str(m.sanitize({'status':'error','error':'secret','data':'secret'},'orders'))

def test_endpoint_guard_precedes_network():
 c=m.ReadOnlyClient('placeholder')
 with pytest.raises(ValueError,match='ENDPOINT_NOT_ALLOWED'): c.get('place')

def test_no_redirect():
 assert m.NoRedirect().redirect_request(None,None,None,None,None,None) is None

def test_readiness_always_blocked():
 r=m.collect(lambda name:response({'user_id':'private'}) if name=='profile' else response([]))
 assert r['connection_status']=='PASS'
 assert r['production_activation_allowed'] is False
 assert r['orders_sent'] is False
 assert r['readiness']=='NOT_CLEARED_FOR_PRODUCTION'

def test_duplicate_positions_unknown():
 old=snapshot(65);old['checks']['positions']['rows']*=2
 assert m.changes(old,snapshot(0))[0]['status']=='UNKNOWN'
