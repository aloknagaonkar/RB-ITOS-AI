from market_lab.midpoint_v2_exit_duration_research_v1 import *
def B(i,o,h,l,c): return Bar(i,o,h,l,c)
def test_e15_hard_time_exit_when_no_stop_hit():
    bars=[B(i,100,104,99,103) for i in range(16)]; r=replay(entry_price=100,bars=bars,policy_id=POLICY_E15); assert r.exit_reason=='TIME_EXIT' and r.exit_minute==15
def test_hybrid_exits_at_15_when_trail_never_activated():
    bars=[B(i,100,104,99,103) for i in range(16)]; r=replay(entry_price=100,bars=bars,policy_id=POLICY_HYBRID); assert r.exit_reason=='TIME15_NO_TRAIL_EXIT' and r.exit_minute==15
def test_hybrid_continues_after_15_when_trail_was_active():
    bars=[B(0,100,100,99,100),B(1,100,111,100,110)]+[B(i,111,112,109,111) for i in range(2,17)]+[B(17,107,108,106,107)]
    r=replay(entry_price=100,bars=bars,policy_id=POLICY_HYBRID); assert r.trail_was_active and r.exit_minute>15 and r.exit_reason in {'STOP_GAP','STOP_TOUCH'}
def test_trail_changes_activate_next_bar_not_same_bar():
    r=replay(entry_price=100,bars=[B(0,100,111,94,105)],policy_id=POLICY_TRAIL_ONLY); assert r.exit_reason=='STOP_TOUCH' and round(r.exit_price,8)==95.0
def test_gap_through_stop_exits_at_open():
    r=replay(entry_price=100,bars=[B(0,100,106,100,105),B(1,98,101,97,99)],policy_id=POLICY_TRAIL_ONLY); assert r.exit_reason=='STOP_GAP' and r.exit_price==98
