from market_lab.trend_day_move_start_oi_replay_v1 import move_anchor
from datetime import datetime

def T(h,m):
    return datetime(2026,1,1,h,m)

def test_bullish_last_minimum():
    pts=[(T(9,20),100),(T(9,25),98),(T(9,30),98),(T(9,35),105)]
    assert move_anchor(pts,"BULLISH_TREND_DAY")[0] == T(9,30)

def test_bearish_last_maximum():
    pts=[(T(9,20),100),(T(9,25),103),(T(9,30),103),(T(9,35),95)]
    assert move_anchor(pts,"BEARISH_TREND_DAY")[0] == T(9,30)
