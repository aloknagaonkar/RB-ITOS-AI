"""Oct14 research: lock from open with WMA>55 / WMA<45, no slope requirement.
Uses the previous corrected-EMA10 runner; never modifies its source or live code.
"""
import inspect
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest

def threshold_lock_class(Parent):
    class ThresholdLock(Parent):
        def observe(self,at,wma,previous,active):
            # Let the original observer validate the true inputs, timestamps and
            # reverse crosses first, but disable its position-based activation.
            before=self.side; count=len(self.events); prior_at=self.last_at
            super().observe(at,wma,previous,'NONE')
            if prior_at==at:return
            released=before!='NONE' and self.side=='NONE'
            if self.side=='NONE' and not released:
                if wma>55:self.side='BULLISH'
                elif wma<45:self.side='BEARISH'
                if self.side!='NONE':
                    self.events.append(dict(time=at.isoformat(),before=before,after=self.side,
                        reason='FROM_OPEN_WMA_ABOVE_55_NO_SLOPE' if self.side=='BULLISH' else 'FROM_OPEN_WMA_BELOW_45_NO_SLOPE',
                        active_direction=active,wma21=wma,previous_wma21=previous))
            for event in self.events[count:]:
                event['active_direction']=active
                event['activation_basis']='COMPLETED_WMA_THRESHOLD_ONLY_FROM_OPEN'
    return ThresholdLock

def lock_adapter(lock):
    Threshold=threshold_lock_class(lock.DirectionLock)
    def gate(Base,direction,frames):
        Parent=lock.lock_gate(Base,direction,frames)
        class ThresholdGate(Parent):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs);self.direction_lock=Threshold()
        return ThresholdGate
    return SimpleNamespace(lock_gate=gate)

class Checks(unittest.TestCase):
    def setUp(self):
        import hilega_post_entry_wma_lock_today_research as lock
        self.Lock=threshold_lock_class(lock.DirectionLock)
        self.at=datetime.fromisoformat('2026-10-14T09:20:00+05:30')
    def test_high_falling_locks_bullish(self):
        g=self.Lock();g.observe(self.at,80,82,'NONE');self.assertEqual(g.side,'BULLISH');self.assertFalse(g.permits('BEARISH'))
    def test_low_rising_locks_bearish(self):
        g=self.Lock();g.observe(self.at,40,39,'NONE');self.assertEqual(g.side,'BEARISH');self.assertFalse(g.permits('BULLISH'))
    def test_high_flat_locks(self):
        g=self.Lock();g.observe(self.at,60,60,'NONE');self.assertEqual(g.side,'BULLISH')
    def test_opening_can_lock_without_previous(self):
        g=self.Lock();g.observe(self.at,60,None,'NONE');self.assertEqual(g.side,'BULLISH')
    def test_middle_starts_none(self):
        g=self.Lock();g.observe(self.at,50,49,'NONE');self.assertEqual(g.side,'NONE')
    def test_threshold_equality_does_not_activate(self):
        for w in (45,55):
            g=self.Lock();g.observe(self.at,w,w,'NONE');self.assertEqual(g.side,'NONE')
    def test_reverse_cross_releases_without_same_bar_flip(self):
        g=self.Lock();g.observe(self.at,60,59,'NONE');g.observe(self.at+timedelta(minutes=5),40,60,'NONE')
        self.assertEqual(g.side,'NONE');g.observe(self.at+timedelta(minutes=10),40,40,'NONE');self.assertEqual(g.side,'BEARISH')
    def test_lock_persists_on_equality(self):
        g=self.Lock();g.observe(self.at,60,59,'NONE');g.observe(self.at+timedelta(minutes=5),55,60,'NONE');self.assertEqual(g.side,'BULLISH')
    def test_same_boundary_idempotent(self):
        g=self.Lock();g.observe(self.at,80,82,'NONE');g.observe(self.at,80,82,'NONE');self.assertEqual(len(g.events),1)
    def test_non_boundary_rejected(self):
        with self.assertRaises(ValueError):self.Lock().observe(self.at+timedelta(minutes=1),80,82,'NONE')

def main():
    import hilega_wma_lock_from_open_oct14_research as previous
    source=inspect.getsource(previous.main)
    changes={
        "data/research/hilega-wma-lock-from-open-20261014":"data/research/hilega-wma-threshold-only-20261014",
        "'FROM_OPEN_WMA_LOCK'":"'THRESHOLD_ONLY_WMA_LOCK'",
        "'FROM_OPEN_WMA_EXCEPTION'":"'THRESHOLD_ONLY_WMA_EXCEPTION'",
        "'Lock from open'":"'Threshold-only lock from open'",
        "'Lock from open + exceptions'":"'Threshold-only lock + exceptions'",
        "New lock can activate while flat: WMA>55 AND rising, or WMA<45 AND falling.":
            "New lock can activate while flat: WMA>55 bullish, WMA<45 bearish; NO rising/falling requirement.",
        "Above55 but falling does NOT initially lock.":"Above55 even when falling DOES initially lock bullish.",
        "FROM_OPEN_POSITION_INDEPENDENT_SLOPE_REQUIRED_V1":"FROM_OPEN_THRESHOLD_ONLY_NO_SLOPE_V2",
        "Lock from market open — ":"Threshold-only lock from market open — ",
    }
    for old,new in changes.items():
        if old not in source:raise ValueError('PREVIOUS_RUNNER_SOURCE_DIFFERS:'+old)
        source=source.replace(old,new)
    namespace=dict(vars(previous));namespace.update(Checks=Checks,open_lock_class=threshold_lock_class,lock_adapter=lock_adapter)
    exec(compile(source,'<threshold-only-oct14>','exec'),namespace)
    namespace['main']()

if __name__=='__main__':main()
