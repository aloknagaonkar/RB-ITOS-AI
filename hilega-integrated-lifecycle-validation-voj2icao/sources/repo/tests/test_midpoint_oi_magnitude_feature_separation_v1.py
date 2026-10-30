from market_lab.midpoint_oi_magnitude_feature_separation_v1 import stats, summarize_group

def test_stats():
    s=stats([1,2,3])
    assert s["count"]==3
    assert s["mean"]==2

def test_summary_has_oi_fields():
    rows=[{
        "atm_ce_oi":"100",
        "atm_pe_oi":"120",
        "atm_ce_oi_change_pct_5m":"-5",
        "atm_pe_oi_change_pct_5m":"8",
        "pm2_ce_oi":"500",
        "pm2_pe_oi":"600",
        "pm2_ce_oi_change_pct_5m":"-3",
        "pm2_pe_oi_change_pct_5m":"4",
        "pm2_oi_pcr":"1.2",
        "ce_minus_pe_change_pct":"-13",
        "abs_change_divergence":"13",
    }]
    out=summarize_group(rows)
    assert out["atm_ce_oi"]["mean"]==100
    assert out["atm_pe_oi_change_pct_5m"]["mean"]==8
