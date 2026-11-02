from datetime import date,datetime,timedelta
import json
import pytest
from repair_core import IST,UNDERLYING,missing_minutes,normalize_v3,proposed_cache,atomic_repair
DAY=date(2026,10,30)


def rows():
    start=datetime(2026,10,30,9,15,tzinfo=IST)
    return [dict(timestamp=(start+timedelta(minutes=i)).isoformat(),open=100,high=102,low=99,close=101,volume=0,open_interest=0) for i in range(375)]


def cache(values):return dict(schema_version=1,underlying=UNDERLYING,session_date=DAY.isoformat(),candles=values)


def test_complete_session_has_exactly_375_minutes():assert missing_minutes(rows(),DAY)==[]


def test_truncated_360_cache_identifies_all_fifteen_tail_minutes():
    m=missing_minutes(rows()[:360],DAY);assert len(m)==15 and m[0]=='15:15' and m[-1]=='15:29'


def test_incomplete_provider_cannot_replace_cache():
    with pytest.raises(ValueError,match='PROVIDER_SESSION_INCOMPLETE'):proposed_cache(cache(rows()[:360]),rows()[:360],DAY)


def test_duplicate_minute_is_rejected():
    r=rows();r.append(r[-1]);
    with pytest.raises(ValueError,match='DUPLICATE'):missing_minutes(r,DAY)


def test_missing_final_1529_is_rejected():assert missing_minutes(rows()[:-1],DAY)==['15:29']


def test_inconsistent_ohlc_is_rejected():
    r=rows();r[0]['high']=99
    with pytest.raises(ValueError,match='OHLC_RANGE'):missing_minutes(r,DAY)


def test_wider_response_filters_other_days_without_inventing_target_minutes():
    r=rows();raw=[[x['timestamp'],x['open'],x['high'],x['low'],x['close'],0,0] for x in r]
    raw.append(['2026-10-29T09:15:00+05:30',100,102,99,101,0,0])
    result=normalize_v3(dict(status='success',data={'candles':raw}),DAY);assert len(result)==375


def test_overlap_revisions_need_explicit_acceptance():
    fresh=rows();fresh[0]['close']=100.5
    with pytest.raises(ValueError,match='OVERLAPPING_BROKER_VALUES_CHANGED'):proposed_cache(cache(rows()[:360]),fresh,DAY)


def test_atomic_repair_preserves_exact_original_bytes(tmp_path):
    p=tmp_path/'2026-10-30.json';old=json.dumps(cache(rows()[:360])).encode();p.write_bytes(old)
    payload,_=proposed_cache(cache(rows()[:360]),rows(),DAY);backup=tmp_path/'backup'
    atomic_repair(p,old,payload,backup)
    assert backup.read_bytes()==old and len(json.loads(p.read_text())['candles'])==375


def test_concurrent_cache_change_is_not_overwritten(tmp_path):
    p=tmp_path/'2026-10-30.json';old=b'old';p.write_bytes(old)
    with pytest.raises(ValueError,match='CHANGED_DURING'):atomic_repair(p,old,{'candidate':True},tmp_path/'backup',checkpoint=lambda:p.write_bytes(b'other-writer'))
    assert p.read_bytes()==b'other-writer'
