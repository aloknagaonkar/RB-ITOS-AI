from market_lab.all3_persistence_daytype_validation_v1 import (
    FROZEN_BULLISH,FROZEN_BEARISH,all3_state,directional_runs,summarize_direction
)

def test_frozen_sets():
    assert len(FROZEN_BULLISH)==18
    assert len(FROZEN_BEARISH)==18
    assert FROZEN_BULLISH.isdisjoint(FROZEN_BEARISH)

def test_states_and_runs():
    bull={h:{"existing_horizon_state":"BULLISH"} for h in ("5m","10m","15m")}
    bear={h:{"existing_horizon_state":"BEARISH"} for h in ("5m","10m","15m")}
    mix={"5m":{"existing_horizon_state":"BULLISH"},"10m":{"existing_horizon_state":"BEARISH"},"15m":{"existing_horizon_state":"BULLISH"}}
    assert all3_state(bull)=="BULLISH_ALL_3"
    assert all3_state(bear)=="BEARISH_ALL_3"
    assert all3_state(mix)=="MIXED"
    runs=directional_runs([("09:30","BULLISH_ALL_3"),("09:35","BULLISH_ALL_3"),("09:40","MIXED"),
                           ("09:45","BEARISH_ALL_3"),("09:50","BEARISH_ALL_3"),("09:55","BEARISH_ALL_3")])
    assert [r["length_candles"] for r in runs]==[2,3]
    assert summarize_direction(runs,"BULLISH_ALL_3")["max_run_length"]==2
    assert summarize_direction(runs,"BEARISH_ALL_3")["max_run_length"]==3
