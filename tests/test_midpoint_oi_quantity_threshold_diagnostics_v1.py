from market_lab.midpoint_oi_quantity_threshold_diagnostics_v1 import qtile, summarize

def test_qtile():
    assert qtile([1,2,3,4],0.5)==2.5

def test_summarize():
    rows=[
        {"outcome_group":"WINNER","net_5m_pct":"5"},
        {"outcome_group":"LOSER","net_5m_pct":"-2"},
    ]
    out=summarize(rows)
    assert out["count"]==2
    assert out["winner_count"]==1
    assert out["win_rate_pct"]==50.0
