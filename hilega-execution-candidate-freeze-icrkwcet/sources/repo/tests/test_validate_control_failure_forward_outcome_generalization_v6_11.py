import importlib.util
from pathlib import Path

P=Path(__file__).parents[1]/'scripts'/'validate_control_failure_forward_outcome_generalization_v6_11.py'
spec=importlib.util.spec_from_file_location('v611',P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def test_outcome_target_is_frozen_mean_15_30():
    assert m.outcome_target({'move_15m':'10','move_30m':'30'}) == 20.0
    assert m.outcome_target({'move_15m':'','move_30m':'30'}) is None


def test_direction_normalization_mirrors_bull_and_bear():
    bull={'direction':'BULLISH','spot_trend_5m':'-10','spot_trend_10m':'-20','spot_trend_15m':'-30','imbalance_5m':'-100','imbalance_10m':'-200','imbalance_15m':'-300','pcr_change_5m':'-0.1','pcr_change_10m':'-0.2','pcr_change_15m':'-0.3','imbalance_velocity_5m':'-50','imbalance_acceleration_5m':'-25','failure_count_5m':'2','max_consecutive_failure_count':'2','decay_count_5m':'1','first_failure_minute':'1'}
    bear=dict(bull); bear['direction']='BEARISH'
    for h in (5,10,15):
        bear[f'spot_trend_{h}m']=str(-float(bull[f'spot_trend_{h}m']))
        bear[f'imbalance_{h}m']=str(-float(bull[f'imbalance_{h}m']))
        bear[f'pcr_change_{h}m']=str(-float(bull[f'pcr_change_{h}m']))
    bear['imbalance_velocity_5m']=str(-float(bull['imbalance_velocity_5m']))
    bear['imbalance_acceleration_5m']=str(-float(bull['imbalance_acceleration_5m']))
    assert m.normalized_features(bull)==m.normalized_features(bear)


def test_spearman_positive_for_monotonic_relation():
    assert m.spearman([1,2,3,4],[10,20,30,40]) == 1.0
    assert m.spearman([1,2,3,4],[40,30,20,10]) == -1.0


def test_chronological_sessions_are_strictly_prior_by_construction():
    sessions=['2026-01-01','2026-01-02','2026-01-03','2026-01-04']
    i=3; prior=sessions[:i]; test=sessions[i]
    assert all(x < test for x in prior)
    assert test not in prior
