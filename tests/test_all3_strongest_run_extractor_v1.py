from market_lab.all3_strongest_run_extractor_v1 import runs

def test_runs():
    states=[
      ("09:30","BULLISH_ALL_3"),("09:35","BULLISH_ALL_3"),
      ("09:40","MIXED"),
      ("09:45","BEARISH_ALL_3"),("09:50","BEARISH_ALL_3"),("09:55","BEARISH_ALL_3"),
    ]
    r=runs(states)
    assert r[0]["candles"]==2
    assert r[0]["duration_minutes"]==10
    assert r[1]["candles"]==3
    assert r[1]["start_timestamp"]=="09:45"
