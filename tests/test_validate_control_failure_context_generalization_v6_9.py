import importlib.util, pathlib, sys
P=pathlib.Path(__file__).resolve().parents[1]/'scripts'/'validate_control_failure_context_generalization_v6_9.py'
spec=importlib.util.spec_from_file_location('v69',P); m=importlib.util.module_from_spec(spec); sys.modules['v69']=m; spec.loader.exec_module(m)

def test_direction_normalization_mirrors_bull_and_bear():
    b={'direction':'BULLISH','spot_trend_5m':'-10','spot_trend_10m':'-20','spot_trend_15m':'-30','imbalance_5m':'-100','imbalance_10m':'-200','imbalance_15m':'-300','pcr_change_5m':'-0.1','pcr_change_10m':'-0.2','pcr_change_15m':'-0.3','imbalance_velocity_5m':'-20','imbalance_acceleration_5m':'-10','failure_count_5m':'2','max_consecutive_failure_count':'2','first_failure_minute':'1','decay_count_5m':'0'}
    s=dict(b); s['direction']='BEARISH'
    for k in ('spot_trend_5m','spot_trend_10m','spot_trend_15m','imbalance_5m','imbalance_10m','imbalance_15m','pcr_change_5m','pcr_change_10m','pcr_change_15m','imbalance_velocity_5m','imbalance_acceleration_5m'):
        s[k]=str(-float(b[k]))
    nb=m.normalized_features(b); ns=m.normalized_features(s)
    assert nb['opposite_spot_pressure_15m']==ns['opposite_spot_pressure_15m']==30.0
    assert nb['opposite_oi_pressure_15m']==ns['opposite_oi_pressure_15m']==300.0

def test_auc_is_half_for_ties():
    assert m.auc([1,0],[1.0,1.0])==0.5

def test_score_prefers_near_median():
    stats=[{'feature':'x','near_median':10.0,'non_median':0.0,'scale':2.0}]
    assert m.score_row({'x':10},stats)>m.score_row({'x':0},stats)

def test_loso_feature_stats_use_training_population_only_shape():
    rows=[{'label':1,'x':20+i} for i in range(5)]+[{'label':0,'x':i/10} for i in range(40)]
    st=m.feature_stats(rows,'x')
    assert st is not None and st['near_n']==5 and st['non_n']==40 and st['separation']>0
