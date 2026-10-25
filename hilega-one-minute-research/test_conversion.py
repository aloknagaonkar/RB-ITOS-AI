import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('one_study',Path(__file__).with_name('run.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_policy_conversion_preserves_exit_thresholds():
    source=Path(m.core.policy5.__file__).read_text();converted=m.convert('hilega_combined_policy_v1',source)
    assert 'current.wma21_rsi>40' in converted
    assert 'bullish_signal_gap_min=2' in converted and 'bullish_full_wma_min=2' in converted
    assert 'timedelta(minutes=5)' not in converted and 'at.minute%5' not in converted
    assert 'FULLY_CONFIRMED_OPPOSITE_BULLISH' in converted

def test_one_minute_bar_aggregation():
    day='2026-10-22';until=m.datetime.fromisoformat(day+'T09:17:00+05:30')
    rows=[dict(timestamp=day+'T09:15:00+05:30',open=100,high=102,low=99,close=101),dict(timestamp=day+'T09:16:00+05:30',open=101,high=103,low=100,close=102)]
    bars=m.core.aggregate(rows,day,1,until)
    assert len(bars)==2 and bars[0].close==101 and bars[1].close==102

def test_followup_and_monitor_use_one_minute(tmp_path):
    p,l=m.isolated_one(tmp_path)
    from datetime import timedelta
    at=m.datetime.fromisoformat('2026-10-22T10:01:00+05:30')
    signal=dict(time=at-timedelta(minutes=1),due=at,close=100,midpoint=99)
    evidence=p.followup_check('BULLISH',signal,dict(available_at=at.isoformat(),close=101),at)
    assert 'NOT_IMMEDIATE_NEXT_1M_BOUNDARY' not in evidence['reasons']
