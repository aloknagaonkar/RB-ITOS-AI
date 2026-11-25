"""Exact journal schema for synthetic post-resume five-minute boundary fixtures."""
from datetime import datetime
from window import need

def entry_payload(stamp):
    t=datetime.fromisoformat(stamp)
    need(t.tzinfo is not None and t.second==t.microsecond==0 and t.minute%5==0,'EXACT_FIXTURE_FIVE_MINUTE_BOUNDARY_REQUIRED')
    event='ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'
    return dict(policy_id='BULLISH_GAP2_FULL_WMA2',strategy_version='bullish-gap2-full-wma2-2.0.0-wma40-reversal',
        reconstructed=False,decision_timestamp=stamp,accepted_events=[event],
        event_details=[dict(event_type=event,event_time=stamp,entry_time=stamp,qualified_signal_time=None)])
