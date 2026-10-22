from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
import batch as b

def test_warmup_moves_forward_without_sharing_session_state(monkeypatch):
    class Canonical:
        def __init__(self):self.seen=[]
        def on_bar(self,bar):self.seen.append(bar)
    class Tracker:
        def __init__(self):self.seen=[]
        def seed(self,bar):self.seen.append(bar)
    monkeypatch.setattr(b.core,'aggregate',lambda rows,*a:rows)
    pool=b.WarmPool(NS(PriceFrames=Tracker),NS(ExitFirstCanonical=Canonical),[('2026-09-29',[1]),('2026-09-30',[2]),('2026-10-01',[3])],1)
    first=deepcopy(pool.prepare('2026-10-01'))
    first[0].seen.append(999)
    current=pool.prepare('2026-10-02')
    assert current[0].seen==[1,2,3] and current[1].seen==[1,2,3]
    assert current[2]==3
    with pytest.raises(ValueError):pool.prepare('2026-10-01')

def test_stats_drawdown_is_chronological():
    trades=[dict(exit_time='2026-10-02',points=-4),dict(exit_time='2026-10-01',points=10),dict(exit_time='2026-10-03',points=-3)]
    s=b.stats(trades)
    assert s['net_points']==3 and s['drawdown']==7 and s['trades']==3

def test_fingerprint_changes_on_input_change():
    assert b.digest({'raw':[1]})!=b.digest({'raw':[2]})

def test_one_minute_conversion_keeps_import():
    s='from .hilega_milega_historical_replay_v1 import aggregate_exact_5m'
    assert b.study.convert('hilega_v2_alignment_replay_v1',s)==s
