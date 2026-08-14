from dataclasses import dataclass
import pandas as pd
from red_bar_lab.services.replay_opportunity_accounting import consolidate_replay_rows
from red_bar_lab.services.historical_dri_replay import detect_historical_dri_events
@dataclass
class Row:
    signal_id:str; timestamp:str; candidate_rank:int|None; execution:str; verdict:str; outcome_result:str; outcome_points:float|None
def test_opportunity_accounting_uses_rank_one_only():
    rows=[Row('S1','09:30',1,'WOULD_TAKE','CORRECT_TAKE','WIN',5.0),Row('S1','09:30',2,'WOULD_TAKE','FALSE_POSITIVE','LOSS',-3.0),Row('S2','10:00',None,'WOULD_WAIT','CORRECT_SKIP','LOSS',-1.0)]
    result=consolidate_replay_rows(rows)
    assert result.opportunities==2 and result.candidates_evaluated==2 and result.trades_selected==1 and result.net_points==4.0
def test_historical_dri_detects_completed_break_without_future_data():
    timestamps=pd.date_range('2026-08-12 09:15',periods=35,freq='1min',tz='Asia/Kolkata')
    close=[100+i*0.05 for i in range(34)]+[105.0]
    frame=pd.DataFrame({'timestamp':timestamps,'open':[x-0.02 for x in close],'high':[x+0.05 for x in close],'low':[x-0.05 for x in close],'close':close})
    frame.loc[34,'open']=102.0; frame.loc[34,'low']=101.9
    events=detect_historical_dri_events(frame)
    assert events and events[-1].direction=='BULLISH'
