from datetime import datetime,date,timedelta
import pytest
from market_lab.domain import IST
from market_lab.live_option_minute_source_v1 import CompletedOptionMinute
from market_lab.hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set
from market_lab.hilega_milega_pe_option_candidate_v1 import build_bearish_pe_candidate_set
from market_lab.hilega_milega_option_shadow_lifecycle_v1 import HilegaMilegaOptionShadowLifecycleV1
from market_lab.hilega_milega_pe_option_shadow_lifecycle_v1 import HilegaMilegaPEOptionShadowLifecycleV1

@pytest.mark.parametrize('side',['CE','PE'])
def test_three_minute_entry_and_last_minute_shadow_close(side):
    strikes=[23300,23350,23400,23450,23500];expiry=date(2026,10,29)
    builder=build_bullish_ce_candidate_set if side=='CE' else build_bearish_pe_candidate_set
    candidates=builder(signal_spot=23400,expiry=expiry,strike_step=50,wings=2,
        contracts=[dict(expiry=expiry.isoformat(),strike_price=s,instrument_type=side,instrument_key=f'{side}-{s}') for s in strikes])
    lifecycle=(HilegaMilegaOptionShadowLifecycleV1 if side=='CE' else HilegaMilegaPEOptionShadowLifecycleV1)()
    label=datetime(2026,10,26,9,15,tzinfo=IST);entry=label+timedelta(minutes=3)
    end=datetime(2026,10,26,15,30,tzinfo=IST)
    include_close=False
    def rows(key):
        result=[CompletedOptionMinute(key,entry,100,102,99,101,100)]
        if include_close:result.append(CompletedOptionMinute(key,end-timedelta(minutes=1),110,115,109,114,100))
        return result
    snap=lifecycle.start(signal_bar_ts=label,signal_interval_minutes=3,signal_spot=23400,
        source='TEST',candidate_set=candidates,option_minutes=rows)
    assert snap.status=='ACTIVE' and snap.signal_boundary==entry.isoformat()
    pending=lifecycle.close(exit_boundary=end,exit_reason='SESSION_END_1530',option_minutes=rows)
    assert pending.status=='PENDING_EXACT_EXIT'
    include_close=True
    closed=lifecycle.retry_pending_exit(option_minutes=rows)
    assert closed.status=='CLOSED'
    assert all(leg.exit_open==114 and leg.realized_points==14 for leg in closed.legs)
    assert closed.payload()['execution_enabled'] is False
