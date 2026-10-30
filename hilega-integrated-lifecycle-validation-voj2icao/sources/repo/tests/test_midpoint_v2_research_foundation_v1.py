import pytest
from market_lab.midpoint_v2_research_foundation_v1 import *

def test_v1_continuation_is_unchanged():
    r=route_v2_extension(t3_state='CONFIRM_CONTINUATION',direction='BULLISH',boundary=26000,midpoint=25970,closes_after_t3=[]); assert r.entry_arm==ARM_IMMEDIATE

def test_bullish_base_then_go():
    r=route_v2_extension(t3_state='WAIT_BASE',direction='BULLISH',boundary=26000,midpoint=25970,closes_after_t3=[26006,26008,26007,26018]); assert r.entry_arm==ARM_BASE and r.entry_direction=='BULLISH'

def test_bearish_base_then_go():
    r=route_v2_extension(t3_state='WAIT_BASE',direction='BEARISH',boundary=26000,midpoint=26030,closes_after_t3=[25994,25992,25993,25980]); assert r.entry_arm==ARM_BASE and r.entry_direction=='BEARISH'

def test_base_boundary_reclaim_routes_to_reclaim_watch():
    r=route_v2_extension(t3_state='WAIT_BASE',direction='BULLISH',boundary=26000,midpoint=25970,closes_after_t3=[26006,26008,25999]); assert r.entry_arm is None and r.final_state==STATE_RECLAIM_WATCH

def test_bullish_failure_midpoint_reclaim_can_confirm_bearish_reversal():
    r=route_v2_extension(t3_state='RECLAIM_WATCH',direction='BULLISH',boundary=26000,midpoint=25970,closes_after_t3=[25998,25968,25960],config=V2WatchConfig(min_reversal_hold_bars=2)); assert r.entry_arm==ARM_RECLAIM and r.entry_direction=='BEARISH'

def test_bearish_failure_midpoint_reclaim_can_confirm_bullish_reversal():
    r=route_v2_extension(t3_state='RECLAIM_WATCH',direction='BEARISH',boundary=26000,midpoint=26030,closes_after_t3=[26005,26032,26040],config=V2WatchConfig(min_reversal_hold_bars=2)); assert r.entry_arm==ARM_RECLAIM and r.entry_direction=='BULLISH'

def test_cancel_remains_terminal():
    r=route_v2_extension(t3_state='CANCEL_BREAKOUT',direction='BULLISH',boundary=26000,midpoint=25970,closes_after_t3=[26050]); assert r.final_state==STATE_CANCEL and r.entry_arm is None

def test_h_is_forbidden_for_v2_rule_discovery():
    with pytest.raises(ValueError,match='OOS_H'): assert_development_only(['TRAIN','OOS_H'])
