from datetime import date
import pandas as pd

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.historical_option_sync import HistoricalOptionChainStore, HistoricalOptionChainSyncService
from red_bar_lab.services.historical_decision_replay import HistoricalDecisionReplayService
from red_bar_lab.storage.artifacts import ArtifactLayout


class CacheOnly:
    def historical_candles(self,*a,**k): raise AssertionError
    def intraday_candles(self,*a,**k): raise AssertionError


class NoNetwork:
    def expired_option_expiries(self,*a,**k): raise AssertionError


def session(day):
    ts=pd.date_range(f"{day} 09:15",f"{day} 15:29",freq="1min",tz="Asia/Kolkata")
    rows=[]
    for i,t in enumerate(ts):
        base=100+((i//5)%4-2)*2
        rows.append({"timestamp":t,"open":base,"high":base+3,"low":base-3,
                     "close":base+(1 if i%2==0 else -1),"volume":100000+i*10,"oi":150000})
    return pd.DataFrame(rows)


def option_session(day, start=100.0):
    ts=pd.date_range(f"{day} 09:15",f"{day} 15:29",freq="1min",tz="Asia/Kolkata")
    rows=[]
    for i,t in enumerate(ts):
        px=start+i*0.08
        rows.append({"timestamp":t,"open":px-0.2,"high":px+0.5,"low":px-0.5,"close":px,
                     "volume":100000+i,"oi":200000+i})
    return pd.DataFrame(rows)


def setup(tmp_path):
    settings=RedBarSettings(artifacts_root=tmp_path/"red_bar")
    layout=ArtifactLayout(settings); layout.ensure()
    hist=RedBarHistoricalService(CacheOnly(),layout)
    d0=date(2026,8,6); d1=date(2026,8,7); key="NSE_INDEX|Nifty 50"
    for d in (d0,d1):
        p=layout.candle_path("upstox",key,1,d.isoformat()); p.parent.mkdir(parents=True,exist_ok=True); session(d.isoformat()).to_csv(p,index=False)
    store=HistoricalOptionChainStore(layout)
    contracts=[]
    for typ in ("CE","PE"):
        for strike in (100,105,110):
            ik=f"NSE_FO|{strike}{typ}"
            contracts.append({"instrument_key":ik,"trading_symbol":f"NIFTY{strike}{typ}","instrument_type":typ,
                              "strike_price":strike,"expiry":"2026-08-13","lot_size":75})
            store.write_candles(key,d1,ik,option_session(d1.isoformat(),95+strike/10))
    store.write_manifest(key,d1,"2026-08-13",contracts)
    sync=HistoricalOptionChainSyncService(NoNetwork(),layout,hist)
    return key,d1,hist,sync


def test_rb151_option_chain_validator_proves_contract_candle_and_oi_coverage(tmp_path):
    key,day,hist,sync=setup(tmp_path)
    report=sync.validate_day(key,day)
    assert report.contracts_discovered==6
    assert report.contracts_stored==6
    assert report.contract_coverage_pct==100.0
    assert report.candle_coverage_pct==100.0
    assert report.oi_coverage_pct==100.0
    assert report.replay_ready is True
    assert report.fidelity=="PARTIAL_LIVE_PARITY_HIGH"


def test_rb151_replay_uses_live_policy_engines_when_option_data_ready(tmp_path):
    key,day,hist,sync=setup(tmp_path)
    result=HistoricalDecisionReplayService(hist,option_chain_sync=sync,minimum_confidence_pct=70.0).run_day(key,day)
    assert result.replay_ready is True
    assert result.data_fidelity=="PARTIAL_LIVE_PARITY_HIGH"
    assert result.option_contract_coverage_pct==100.0
    if result.rows:
        assert any(r.candidate_symbol for r in result.rows)
        assert all(r.shadow_adjustment_pct==0.0 for r in result.rows)
        assert all(r.final_confidence_pct==r.primary_confidence_pct for r in result.rows)
        assert all(r.portfolio_status in {"APPROVED","WATCHLIST","NOT_QUALIFIED","BLOCKED"} for r in result.rows)


def test_rb151_replay_refuses_unreliable_option_coverage(tmp_path):
    settings=RedBarSettings(artifacts_root=tmp_path/"red_bar"); layout=ArtifactLayout(settings); layout.ensure()
    hist=RedBarHistoricalService(CacheOnly(),layout); day=date(2026,8,7); key="NSE_INDEX|Nifty 50"
    p=layout.candle_path("upstox",key,1,day.isoformat()); p.parent.mkdir(parents=True,exist_ok=True); session(day.isoformat()).to_csv(p,index=False)
    sync=HistoricalOptionChainSyncService(NoNetwork(),layout,hist)
    try:
        HistoricalDecisionReplayService(hist,option_chain_sync=sync).run_day(key,day)
    except ValueError as exc:
        assert "Sync / Repair Historical Option Chain" in str(exc)
    else:
        raise AssertionError("Replay must refuse unreliable option coverage")
