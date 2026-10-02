from market_lab.oi_pm2_trend_day_profile_v1 import sign_combo
def test_sign_combo():
    assert sign_combo(-10,20)=="CE_DOWN_PE_UP"
    assert sign_combo(10,-20)=="CE_UP_PE_DOWN"
