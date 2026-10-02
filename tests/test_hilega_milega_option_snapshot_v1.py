from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set
from market_lab.hilega_milega_option_snapshot_v1 import observe_exact_candidate_market_snapshot
from market_lab.live_option_minute_source_v1 import CompletedOptionMinute

IST=ZoneInfo('Asia/Kolkata')


def contracts():
    expiry='2026-09-24'
    return [
        {"expiry":expiry,"strike_price":strike,"instrument_type":"CE","instrument_key":f"CE-{strike}"}
        for strike in [23250,23300,23350,23400,23450]
    ]


def candidate_set():
    return build_bullish_ce_candidate_set(
        signal_spot=23355,
        expiry=date(2026,9,24),
        contracts=contracts(),
        wings=2,
    )


def test_snapshot_uses_exact_last_completed_minute_at_signal_boundary():
    cs=candidate_set()
    signal=datetime(2026,9,23,9,55,tzinfo=IST)
    def source(key):
        return [
            CompletedOptionMinute(key,datetime(2026,9,23,9,58,tzinfo=IST),100,102,99,101,10),
            CompletedOptionMinute(key,datetime(2026,9,23,9,59,tzinfo=IST),101,104,100,103,20),
        ]
    out=observe_exact_candidate_market_snapshot(signal_bar_ts=signal,candidate_set=cs,option_minutes=source)
    assert out.status=='AVAILABLE'
    assert out.signal_boundary.endswith('10:00:00+05:30')
    assert out.expected_option_minute.endswith('09:59:00+05:30')
    assert len(out.snapshots)==5
    assert {x.close for x in out.snapshots}=={103.0}
    assert out.selected_instrument_key is None


def test_snapshot_fails_closed_when_exact_minute_missing_no_nearest_fallback():
    cs=candidate_set()
    signal=datetime(2026,9,23,9,55,tzinfo=IST)
    def source(key):
        if key=='CE-23350':
            return [CompletedOptionMinute(key,datetime(2026,9,23,9,58,tzinfo=IST),100,101,99,100,10)]
        return [CompletedOptionMinute(key,datetime(2026,9,23,9,59,tzinfo=IST),100,101,99,100,10)]
    out=observe_exact_candidate_market_snapshot(signal_bar_ts=signal,candidate_set=cs,option_minutes=source)
    assert out.status=='INCOMPLETE'
    assert 'CE-23350:EXACT_MINUTE_MATCH_COUNT=0' in out.issue
    assert out.selected_instrument_key is None
