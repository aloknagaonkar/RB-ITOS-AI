from datetime import date, datetime, timedelta

from market_lab.domain import HistoricalCandle, HistoricalOptionContract, IST
from market_lab.hilega_milega_functional_parity_replay_v1 import HistoricalParityMarketSourcesV1, normalize_functional_audit


class Gateway:
    def __init__(self):
        self.d=date(2026,9,23)
        self.underlying=[]
        start=datetime(2026,9,23,9,15,tzinfo=IST)
        for i in range(10):
            px=23000+i
            self.underlying.append(HistoricalCandle(provider="upstox",instrument_key="NSE_INDEX|Nifty 50",session_date=self.d,timestamp=start+timedelta(minutes=i),open=px,high=px+1,low=px-1,close=px+.5,volume=100,open_interest=None))
        self.contracts=[HistoricalOptionContract(instrument_key=f"CE-{s}",underlying="NSE_INDEX|Nifty 50",expiry=date(2026,9,29),strike=s,side="CE") for s in [22900,22950,23000,23050,23100]]

    def intraday_candles(self,instrument_key,session_date):
        if instrument_key == "NSE_INDEX|Nifty 50":
            return list(self.underlying)
        return self.historical_option_candles(instrument_key,session_date)
    def active_option_contracts(self, underlying, expiry): return list(self.contracts)
    def historical_candles(self,instrument_key,session_date):
        return list(self.underlying) if instrument_key=="NSE_INDEX|Nifty 50" and session_date==self.d else []
    def historical_option_contracts(self,underlying,expiry):
        return list(self.contracts)
    def historical_option_candles(self,instrument_key,session_date):
        start=datetime(2026,9,23,9,15,tzinfo=IST)
        return [HistoricalCandle(provider="upstox",instrument_key=instrument_key,session_date=self.d,timestamp=start+timedelta(minutes=i),open=100+i,high=102+i,low=99+i,close=101+i,volume=1000,open_interest=None) for i in range(10)]


def test_historical_parity_source_matches_live_source_contract_shape_and_exact_minutes():
    src=HistoricalParityMarketSourcesV1(Gateway(),date(2026,9,23))
    rows=src.nifty_intraday_1m(now=datetime(2026,9,23,9,20,tzinfo=IST))
    assert rows[-1].timestamp.strftime('%H:%M')=='09:20'
    contracts=src.option_contracts('NSE_INDEX|Nifty 50',date(2026,9,29))
    assert contracts[2]['instrument_type']=='CE'
    assert contracts[2]['strike_price']==23000
    bars=src.option_intraday_1m('CE-23000')
    assert bars[0].instrument_key=='CE-23000'
    assert bars[0].timestamp.strftime('%H:%M')=='09:15'


def test_functional_normalizer_removes_runtime_hash_identity_not_semantics():
    rows=[{"sequence":1,"stage":"LIVE_BOOTSTRAP","status":"PASS","checkpoint":None,"payload":{"x":1}},
          {"sequence":2,"stage":"STRATEGY_TRANSITION","status":"ENTRY","checkpoint":"c","payload":{"price":100},"record_hash":"abc"}]
    out=normalize_functional_audit(rows)
    assert out==[{"checkpoint":"c","stage":"STRATEGY_TRANSITION","status":"ENTRY","payload":{"price":100}}]
