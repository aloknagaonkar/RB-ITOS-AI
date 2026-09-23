from __future__ import annotations
from datetime import date,datetime,timedelta
from urllib.parse import quote
from .domain import IST
from .gateways import normalize_upstox_historical_candles
from .live_nifty_futures_oi_producer_v1 import CompletedFuturesCandle,LiveNiftyFuturesOIProducerV1
from .live_option_minute_source_v1 import CompletedOptionMinute
from .upstox_live_futures_v1 import UpstoxLiveFuturesGatewayV1

class UpstoxLiveShadowSourcesV1:
    def __init__(self,token:str,client=None):self.gateway=UpstoxLiveFuturesGatewayV1(token,client=client)
    def close(self):self.gateway.close()
    def futures_oi_at_checkpoint(self,checkpoint:datetime):
        local=checkpoint.astimezone(IST); instrument=self.gateway.resolve_nifty_front_future(today=local.date()); encoded=quote(instrument.instrument_key,safe="")
        body=self.gateway._get(f"/v3/historical-candle/intraday/{encoded}/minutes/5"); by_end={}
        for raw in body.get("data",{}).get("candles",[]):
            if not isinstance(raw,list) or len(raw)<7 or raw[6] is None:continue
            start=datetime.fromisoformat(str(raw[0]).replace("Z","+00:00")).astimezone(IST); end=start+timedelta(minutes=5)
            by_end[end]=CompletedFuturesCandle(instrument.instrument_key,end,float(raw[1]),float(raw[2]),float(raw[3]),float(raw[4]),float(raw[6]))
        prev=by_end.get(local-timedelta(minutes=5)); cur=by_end.get(local)
        if prev is None or cur is None:raise ValueError("Exact completed futures OI pair unavailable")
        p=LiveNiftyFuturesOIProducerV1(); assert p.process(prev) is None; out=p.process(cur)
        if out is None:raise ValueError("Futures OI observation unavailable")
        return out
    def option_intraday_1m(self,instrument_key:str):
        encoded=quote(instrument_key,safe="");body=self.gateway._get(f"/v3/historical-candle/intraday/{encoded}/minutes/1");rows=[]
        for raw in body.get("data",{}).get("candles",[]):
            if not isinstance(raw,list) or len(raw)<5:continue
            ts=datetime.fromisoformat(str(raw[0]).replace("Z","+00:00")).astimezone(IST)
            rows.append(CompletedOptionMinute(instrument_key,ts,float(raw[1]),float(raw[2]),float(raw[3]),float(raw[4]),float(raw[5]) if len(raw)>5 and raw[5] is not None else None))
        rows.sort(key=lambda x:x.timestamp)
        if len({x.timestamp for x in rows})!=len(rows):raise ValueError("Duplicate option minute timestamps")
        return rows
    def option_contracts(self,underlying:str,expiry:date):
        body=self.gateway._get("/v2/option/contract",params={"instrument_key":underlying,"expiry_date":expiry.isoformat()})
        rows=body.get("data")
        if not isinstance(rows,list):raise ValueError("Option contract catalog unavailable")
        return rows

    def historical_candles(self,instrument_key:str,session_date:date):
        encoded=quote(instrument_key,safe="");d=session_date.isoformat()
        body=self.gateway._get(f"/v3/historical-candle/{encoded}/minutes/1/{d}/{d}")
        return normalize_upstox_historical_candles(instrument_key,session_date,body)

    def nifty_intraday_1m(self,*,now:datetime|None=None):
        local=(now or datetime.now(IST)).astimezone(IST);instrument_key="NSE_INDEX|Nifty 50"
        encoded=quote(instrument_key,safe="")
        body=self.gateway._get(f"/v3/historical-candle/intraday/{encoded}/minutes/1")
        return normalize_upstox_historical_candles(instrument_key,local.date(),body)

