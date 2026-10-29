import importlib.util
from pathlib import Path
import sys
from datetime import datetime
HERE=Path(__file__).parent;sys.path.insert(0,str(HERE))
s=importlib.util.spec_from_file_location('protected_runner',HERE/'hybrid.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def at(tm):return datetime.fromisoformat('2026-08-07T'+tm+':00+05:30')
def active(side='BULLISH',route='INDEPENDENT_BODY60_1M_BREAKOUT'):
 return dict(direction=side,route=route,entry_time=at('10:00').isoformat(),setup=at('09:55').isoformat(),entry_price=110,evidence=dict(midpoint=100))
def test_bull_strict_below():
 assert m.protection_check(active(),at('10:01'),99,at('14:55'))['passed']
def test_bear_strict_above():
 assert m.protection_check(active('BEARISH'),at('10:01'),101,at('14:55'))['passed']
def test_equality_holds_both():
 for side in ['BULLISH','BEARISH']:
  assert not m.protection_check(active(side),at('10:01'),100,at('14:55'))['passed']
def test_no_check_on_entry_candle():
 assert m.protection_check(active(),at('10:00'),99,at('14:55')) is None
def test_existing_route_unaffected():
 assert m.protection_check(active(route='EXISTING'),at('10:01'),99,at('14:55')) is None
def test_cutoff_priority():
 assert m.protection_check(active(),at('14:55'),99,at('14:55')) is None
def test_no_active_no_exit():
 assert m.protection_check(None,at('10:01'),99,at('14:55')) is None
def test_original_midpoint_not_trailed():
 a=active();m.protection_check(a,at('10:01'),120,at('14:55'))
 assert a['evidence']['midpoint']==100
 assert m.protection_check(a,at('10:02'),101,at('14:55'))['passed'] is False
