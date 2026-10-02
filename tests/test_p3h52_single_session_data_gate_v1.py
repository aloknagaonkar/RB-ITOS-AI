import csv,json
from market_lab.session_data_gate_v1 import validate_session
FIELDS=['session_date','expiry','instrument_key','trading_symbol','contract_source','timestamp','open','high','low','close','volume','open_interest','typical_price','session_cumulative_volume','session_vwap']
def test_gate_fails_when_futures_missing(tmp_path):
    root=tmp_path/'data'; pdir=root/'historical-positioning-cache-train'; odir=root/'historical-option-ohlc-cache-train'; pdir.mkdir(parents=True); odir.mkdir(parents=True)
    (pdir/'NSE_INDEX_Nifty_50__2026-05-04__2026-05-04__w5.json').write_text(json.dumps({'status':'AVAILABLE','session_date':'2026-05-04','rows':[{'timestamp':'2026-05-04T09:20:00+05:30','ce_instrument_key':'CE','pe_instrument_key':'PE','ce_oi':100,'pe_oi':110}]}))
    (odir/'NSE_INDEX_Nifty_50__2026-05-04__2026-05-04__w5.json').write_text(json.dumps({'status':'AVAILABLE','session_date':'2026-05-04','rows':[{'instrument_key':'CE','side':'CE','strike':24000,'timestamp':'2026-05-04T09:20:00+05:30','open':10,'high':11,'low':9,'close':10},{'instrument_key':'PE','side':'PE','strike':24000,'timestamp':'2026-05-04T09:20:00+05:30','open':10,'high':11,'low':9,'close':10}]}))
    fut=tmp_path/'f.csv'
    with fut.open('w',newline='') as h: csv.DictWriter(h,fieldnames=FIELDS).writeheader()
    r=validate_session('2026-05-04',data_root=root,futures_csv=fut)
    assert r.status=='FAIL' and 'FUTURES' in r.repair_required
