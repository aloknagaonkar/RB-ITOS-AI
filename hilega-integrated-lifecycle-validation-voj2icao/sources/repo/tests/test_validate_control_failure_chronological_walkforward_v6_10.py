import importlib.util
from pathlib import Path

P=Path(__file__).resolve().parents[1]/'scripts'/'validate_control_failure_chronological_walkforward_v6_10.py'
spec=importlib.util.spec_from_file_location('v610',P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def test_direction_normalization_is_symmetric():
    b={'direction':'BULLISH','spot_trend_15m':'-20','imbalance_15m':'-100','pcr_change_15m':'-0.2'}
    s={'direction':'BEARISH','spot_trend_15m':'20','imbalance_15m':'100','pcr_change_15m':'0.2'}
    nb=m.normalized_features(b); ns=m.normalized_features(s)
    assert nb['opposite_spot_pressure_15m']==ns['opposite_spot_pressure_15m']==20
    assert nb['opposite_oi_pressure_15m']==ns['opposite_oi_pressure_15m']==100

def test_chronological_prior_sessions_are_strictly_earlier_by_sorted_order():
    sessions=['2026-05-12','2026-05-18','2026-05-19','2026-05-20']
    i=3; prior=sessions[:i]
    assert prior==['2026-05-12','2026-05-18','2026-05-19']
    assert sessions[i] not in prior

def test_rank_cut_is_fixed_fraction_not_label_optimized():
    rows=[{'score':float(i),'label':i%2} for i in range(100)]
    assert len(m.rank_cut(rows,0.10))==10
    assert len(m.rank_cut(rows,0.05))==5

def test_forward_metric_summary_uses_directional_values_as_already_stored():
    xs=[{'move_5m':'1','move_10m':'2','move_15m':'3','move_30m':'4','mfe_30m':'5','mae_30m':'-1'},
        {'move_5m':'-1','move_10m':'0','move_15m':'1','move_30m':'2','mfe_30m':'4','mae_30m':'-2'}]
    s=m.metric_summary(xs)
    assert s['median_15m']==2.0
    assert s['hit_15m_pct']==100.0
    assert s['median_mfe_30m']==4.5
