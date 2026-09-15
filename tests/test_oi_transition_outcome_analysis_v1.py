from market_lab.oi_transition_outcome_analysis_v1 import outcome20,signed_move
def test_outcome20():
 assert outcome20({"directional_move_20m_points":5})=="CONTINUES_20M";assert outcome20({"directional_move_20m_points":0})=="FAILS_20M";assert outcome20({"directional_move_20m_points":None})=="UNKNOWN_20M"
def test_signed_bull():assert signed_move({"direction":"BULLISH","spot_close":100},{"spot_close":112})==12
def test_signed_bear():assert signed_move({"direction":"BEARISH","spot_close":100},{"spot_close":88})==12
