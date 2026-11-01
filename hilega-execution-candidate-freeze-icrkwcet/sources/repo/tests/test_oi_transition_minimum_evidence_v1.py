import pytest
from datetime import datetime,timedelta
from market_lab.oi_transition_minimum_evidence_v1 import pct,stats,persistence_at

def test_pct():
    assert pct(120,100)==pytest.approx(20.0)

def test_stats():
    s=stats([1,2,3,4])
    assert s["median"]==2.5
    assert s["q25"]==pytest.approx(1.75)
    assert s["q75"]==pytest.approx(3.25)

def test_persistence():
    base=datetime(2026,1,1,9,20)
    rows=[]
    for i,imb in enumerate([1,2,3,-1]):
        rows.append({"timestamp":(base+timedelta(minutes=5*i)).isoformat(),
                     "imbalance_5m":imb})
    assert persistence_at(rows,2,3,1) is True
    assert persistence_at(rows,3,3,1) is False
