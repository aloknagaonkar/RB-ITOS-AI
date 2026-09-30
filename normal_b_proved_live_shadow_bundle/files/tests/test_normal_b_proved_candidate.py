from datetime import datetime, timedelta, timezone
import unittest
from market_lab.midpoint_strategy.normal_b_proved_candidate import Bar, NormalBProvedCandidate, Policy

START = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)

def setup(direction="BULLISH"):
    c = NormalBProvedCandidate(entry_timestamp=START, entry_price=100,
        direction=direction, midpoint=0 if direction == "BULLISH" else 200)
    def send(i, excursion=25, close=24, classifier=None):
        b = (Bar(START+timedelta(minutes=i),100+excursion,100+min(close,0),100+close)
             if direction == "BULLISH" else
             Bar(START+timedelta(minutes=i),100-min(close,0),100-excursion,100-close))
        return c.on_bar(b, classifier_result=classifier)
    for i in range(1,11): send(i)
    send(11,classifier="NORMAL_B")
    return c,send

class Tests(unittest.TestCase):
    def test_strict_tier_boundaries(self):
        _,s=setup();self.assertIsNone(s(12,30,28)["floor_points"])
        self.assertEqual(s(13,30.01,28)["floor_points"],15)
        self.assertEqual(s(14,45,40)["floor_points"],15)
        r=s(15,45.01,41);self.assertEqual(r["state"],"NORMAL_B_PROVED_TIER3");self.assertEqual(r["floor_points"],31)
    def test_ratchet_uses_highest_close_and_never_falls(self):
        _,s=setup();self.assertEqual(s(12,46,40)["floor_points"],30)
        self.assertEqual(s(13,47,44)["floor_points"],34)
        self.assertEqual(s(14,47,38)["floor_points"],34)
        r=s(15,47,33);self.assertEqual(r["reason"],"TIER3_RATCHET_FLOOR_CLOSE");self.assertEqual(r["pnl_points"],33)
    def test_floor_equality_does_not_exit(self):
        _,s=setup();self.assertEqual(s(12,31,15)["state"],"NORMAL_B_PROVED_TIER2")
        self.assertEqual(s(13,31,14)["reason"],"TIER2_PROTECTIVE_FLOOR_CLOSE")
    def test_exact_target_assumption_is_symmetric(self):
        for d in ("BULLISH","BEARISH"):
            _,s=setup(d);r=s(12,50,42);self.assertEqual(r["pnl_points"],50)
            self.assertEqual(r["valuation_basis"],"ASSUMED_EXACT_TARGET_FILL")
    def test_classification_bar_cannot_retroactively_fill_target(self):
        c=NormalBProvedCandidate(entry_timestamp=START,entry_price=100,direction="BULLISH",midpoint=0)
        for i in range(1,11):c.on_bar(Bar(START+timedelta(minutes=i),125,100,124))
        r=c.on_bar(Bar(START+timedelta(minutes=11),151,100,145),classifier_result="NORMAL_B")
        self.assertEqual(r["state"],"NORMAL_B_PROVED");self.assertIsNone(c.exit)
    def test_inactivity_exits_following_minute(self):
        _,s=setup()
        for i in range(12,41):self.assertIsNone(s(i)["inactivity_exit_due"])
        self.assertEqual(s(41)["inactivity_exit_due"],(START+timedelta(minutes=42)).isoformat())
        self.assertEqual(s(42)["reason"],"NO_NEW_MFE_TIME_EXIT")
    def test_new_mfe_resets_clock(self):
        _,s=setup()
        for i in range(12,40):s(i)
        s(40,26,25);self.assertIsNone(s(41)["inactivity_exit_due"])
    def test_scheduled_inactivity_exit_cannot_be_cancelled(self):
        _,s=setup()
        for i in range(12,42):s(i)
        r=s(42,29,28)
        self.assertEqual(r["reason"],"NO_NEW_MFE_TIME_EXIT")
    def test_missing_minute_and_reentry_fail(self):
        _,s=setup()
        with self.assertRaises(ValueError):s(13)
        _,s=setup();s(12,50,42)
        with self.assertRaises(ValueError):s(13)
    def test_policy_validation(self):
        with self.assertRaises(ValueError):Policy(tier3_mfe_points=29)

if __name__=="__main__":unittest.main()
