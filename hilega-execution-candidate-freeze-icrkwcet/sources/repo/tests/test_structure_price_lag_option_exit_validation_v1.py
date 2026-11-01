from market_lab.structure_price_lag_option_exit_validation_v1 import replay_policy

def _idx(rows):
    return {"CE": {r["timestamp"]: r for r in rows}}

def test_time_exit():
    trade = {
        "instrument_key":"CE",
        "entry_timestamp":"2026-01-01T10:00:00+05:30",
        "entry_open":"100",
    }
    rows=[]
    for m in range(1,16):
        rows.append({
            "timestamp":f"2026-01-01T10:{m:02d}:00+05:30",
            "open":"100","high":"102","low":"98","close":"101"
        })
    r=replay_policy(trade,_idx(rows),"TIME_15",{
        "initial_stop_pct":None,"breakeven_trigger_pct":None,
        "trail_activation_pct":None,"trail_distance_pct":None,
        "max_hold_minutes":15,
    })
    assert r["available"] is True
    assert r["exit_reason"]=="TIME_EXIT"
    assert round(r["net_return_pct"], 6)==0.5

def test_next_bar_be_then_stop():
    trade = {
        "instrument_key":"CE",
        "entry_timestamp":"2026-01-01T10:00:00+05:30",
        "entry_open":"100",
    }
    rows=[
        {"timestamp":"2026-01-01T10:01:00+05:30","open":"100","high":"106","low":"99","close":"105"},
        {"timestamp":"2026-01-01T10:02:00+05:30","open":"104","high":"105","low":"99","close":"100"},
    ]
    r=replay_policy(trade,_idx(rows),"X",{
        "initial_stop_pct":5.0,"breakeven_trigger_pct":5.0,
        "trail_activation_pct":10.0,"trail_distance_pct":3.0,
        "max_hold_minutes":15,
    })
    assert r["available"] is True
    assert r["be_armed"] is True
    assert r["exit_reason"]=="STOP_TOUCH"
    assert r["exit_price"]==100
    assert r["net_return_pct"]==-0.5

def test_trail_activates_next_bar():
    trade = {
        "instrument_key":"CE",
        "entry_timestamp":"2026-01-01T10:00:00+05:30",
        "entry_open":"100",
    }
    rows=[
        {"timestamp":"2026-01-01T10:01:00+05:30","open":"100","high":"112","low":"99","close":"111"},
        {"timestamp":"2026-01-01T10:02:00+05:30","open":"111","high":"113","low":"108","close":"109"},
    ]
    r=replay_policy(trade,_idx(rows),"X",{
        "initial_stop_pct":5.0,"breakeven_trigger_pct":5.0,
        "trail_activation_pct":10.0,"trail_distance_pct":3.0,
        "max_hold_minutes":15,
    })
    # after bar1, trail from best 112 => 108.64. bar2 touches it.
    assert r["available"] is True
    assert r["trail_armed"] is True
    assert r["exit_reason"]=="STOP_TOUCH"
    assert round(r["exit_price"],2)==108.64
