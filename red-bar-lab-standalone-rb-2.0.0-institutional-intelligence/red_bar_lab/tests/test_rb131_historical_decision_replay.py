from datetime import date
import pandas as pd

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.historical_decision_replay import HistoricalDecisionReplayService
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.storage.artifacts import ArtifactLayout


class CacheOnly:
    def historical_candles(self, *a, **k): raise AssertionError
    def intraday_candles(self, *a, **k): raise AssertionError


def session(day):
    ts = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq="1min", tz="Asia/Kolkata")
    rows=[]
    for i,t in enumerate(ts):
        base=100 + ((i//5)%4-2)*2
        rows.append({"timestamp":t,"open":base,"high":base+3,"low":base-3,"close":base+(1 if i%2==0 else -1),"volume":1000+i,"oi":0})
    return pd.DataFrame(rows)


def write(layout, day, frame):
    p=layout.candle_path("upstox","NSE_INDEX|Nifty 50",1,day.isoformat()); p.parent.mkdir(parents=True,exist_ok=True); frame.to_csv(p,index=False)


def test_historical_decision_replay_is_point_in_time_and_reports_take_or_wait(tmp_path):
    settings=RedBarSettings(artifacts_root=tmp_path/"red_bar")
    layout=ArtifactLayout(settings); layout.ensure()
    hist=RedBarHistoricalService(CacheOnly(),layout)
    d0=date(2026,8,6); d1=date(2026,8,7)
    write(layout,d0,session(d0.isoformat())); write(layout,d1,session(d1.isoformat()))
    result=HistoricalDecisionReplayService(hist).run_day("NSE_INDEX|Nifty 50",d1)
    assert result.active_signals >= 0
    assert result.data_fidelity.startswith("POINT_IN_TIME")
    for row in result.rows:
        assert row.execution in {"WOULD_TAKE","WOULD_WAIT","WOULD_BLOCK"}
        assert "NO_INTRADAY" not in row.data_fidelity  # row uses explicit option limitation wording
        assert row.shadow_decision == "WAIT"
