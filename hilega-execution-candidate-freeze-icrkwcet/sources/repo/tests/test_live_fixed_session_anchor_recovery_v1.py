from datetime import date, datetime
from zoneinfo import ZoneInfo
import pytest
from market_lab.domain import Contract, Quote, Snapshot
from market_lab.live_fixed_session_anchor_recovery_v1 import (
    AnchorRecoveryError, FixedAnchorLeg, FixedSessionAnchor,
    UpstoxIntradayAnchorSourceV1, capture_live_fixed_anchor,
    fixed_session_metrics, recover_upstox_fixed_anchor,
)
IST=ZoneInfo("Asia/Kolkata")

class R:
    def __init__(self,code,body): self.status_code=code; self.body=body
    def json(self): return self.body
class C:
    def __init__(self,routes): self.routes=routes
    def get(self,path,params=None,headers=None):
        return R(200,self.routes[(path,tuple(sorted((params or {}).items())))]) if (path,tuple(sorted((params or {}).items()))) in self.routes else R(404,{})

def candle(ts,close=100,oi=1000): return [ts,close,close,close,close,1,oi]
def routes(source_minute="09:19",missing=None,missing_oi=None):
    u="NSE_INDEX|Nifty 50"; e="2026-09-22"; s="2026-09-21"; cs=[]
    for strike in range(23150,23700,50):
        for side in ("CE","PE"):
            if missing==(strike,side): continue
            cs.append({"underlying_key":u,"expiry":e,"strike_price":float(strike),"instrument_type":side,"instrument_key":f"K-{strike}-{side}"})
    out={("/v2/option/contract",tuple(sorted({"instrument_key":u,"expiry_date":e}.items()))):{"data":cs},
         ("/v3/historical-candle/intraday/NSE_INDEX%7CNifty%2050/minutes/1",()):{"data":{"candles":[candle(f"{s}T{source_minute}:00+05:30",23384.65,0)]}}}
    for x in cs:
        strike=int(x["strike_price"]); side=x["instrument_type"]; oi=None if missing_oi==(strike,side) else strike*(2 if side=="CE" else 3)
        out[(f'/v3/historical-candle/intraday/{x["instrument_key"]}/minutes/1',())]={"data":{"candles":[[f"{s}T{source_minute}:00+05:30",10,10,10,10,1,oi]]}}
    return out

def patch_today(monkeypatch):
    import market_lab.live_fixed_session_anchor_recovery_v1 as m
    real=datetime
    class D(datetime):
        @classmethod
        def now(cls,tz=None):
            v=real(2026,9,21,12,0,tzinfo=IST); return v if tz is None else v.astimezone(tz)
    monkeypatch.setattr(m,"datetime",D)

def test_exact_previous_minute_required(monkeypatch):
    patch_today(monkeypatch); src=UpstoxIntradayAnchorSourceV1("x",client=C(routes("09:18")))
    with pytest.raises(AnchorRecoveryError,match="EXACT_CANDLE_COUNT"):
        recover_upstox_fixed_anchor(source=src,session_date=date(2026,9,21),underlying="NSE_INDEX|Nifty 50",expiry=date(2026,9,22))

def test_exact_11_strikes_22_contracts(monkeypatch):
    patch_today(monkeypatch); src=UpstoxIntradayAnchorSourceV1("x",client=C(routes()))
    a=recover_upstox_fixed_anchor(source=src,session_date=date(2026,9,21),underlying="NSE_INDEX|Nifty 50",expiry=date(2026,9,22))
    assert a.status=="AVAILABLE" and a.provenance=="ANCHOR_RECOVERED_UPSTOX_INTRADAY_1M"
    assert a.source_candle_time.endswith("09:19:00+05:30") and a.atm==23400 and len(a.strikes)==11 and len(a.legs)==22 and not a.fallback_used
    assert a.fixed_pcr==pytest.approx(a.pe_total/a.ce_total)

def test_missing_contract_fails(monkeypatch):
    patch_today(monkeypatch); src=UpstoxIntradayAnchorSourceV1("x",client=C(routes(missing=(23450,"PE"))))
    with pytest.raises(AnchorRecoveryError,match="EXACT_CONTRACT_MISSING_23450_PE"):
        recover_upstox_fixed_anchor(source=src,session_date=date(2026,9,21),underlying="NSE_INDEX|Nifty 50",expiry=date(2026,9,22))

def test_missing_oi_fails(monkeypatch):
    patch_today(monkeypatch); src=UpstoxIntradayAnchorSourceV1("x",client=C(routes(missing_oi=(23400,"CE"))))
    with pytest.raises(AnchorRecoveryError,match="OPTION_OI_INVALID_OR_MISSING"):
        recover_upstox_fixed_anchor(source=src,session_date=date(2026,9,21),underlying="NSE_INDEX|Nifty 50",expiry=date(2026,9,22))

def snap(bump=0):
    cs=[]; qs=[]
    for strike in range(23150,23700,50):
        for side in ("CE","PE"):
            key=f"K-{strike}-{side}"; cs.append(Contract(key=key,strike=float(strike),side=side)); qs.append(Quote(key=key,oi=strike*(2 if side=="CE" else 3)+bump))
    t=datetime(2026,9,21,9,20,10,tzinfo=IST)
    return Snapshot(provider="upstox",underlying="NSE_INDEX|Nifty 50",expiry=date(2026,9,22),started_at=t,received_at=t,spot=23384.65,spot_feed_at=t,catalog=cs,quotes=qs,raw={})

def test_live_capture_and_deltas():
    a=capture_live_fixed_anchor(snapshot=snap(),session_date=date(2026,9,21),anchor_time="09:20",wings=5)
    m=fixed_session_metrics(anchor=a,snapshot=snap(10),checkpoint=datetime(2026,9,21,10,0,tzinfo=IST))
    assert a.provenance=="ANCHOR_LIVE" and len(a.legs)==22
    assert m.status=="AVAILABLE" and m.ce_delta==110 and m.pe_delta==110 and m.imbalance==0
