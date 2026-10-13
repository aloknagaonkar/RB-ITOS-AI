import sys,json,copy,tempfile
from pathlib import Path
from datetime import date,timedelta
from types import SimpleNamespace
from market_lab import hilega_v2_alignment_replay_v1 as replay
from market_lab.hilega_alignment_dual_exit_live_v1 import HilegaAlignmentDualExitLiveCoordinator
from market_lab.hilega_opening_reference_v1 import capture_opening_reference
from market_lab.hilega_milega_strategy_v1 import SessionState
from market_lab.hilega_milega_bearish_strategy_v1 import BearishSessionState
root=Path(sys.argv[1]);target=date(2026,10,8);canonical=replay.ExitFirstCanonical()
for p in sorted(root.glob('????-??-??.json')):
 if p.stem>=target.isoformat():continue
 rows=json.loads(p.read_text()).get('candles') or []
 if rows:
  for bar in replay.aggregate_exact_5m(replay.candles(rows),date.fromisoformat(p.stem)):canonical.on_bar(bar)
opening=capture_opening_reference(canonical,target)
canonical.bullish.session=SessionState(session_date=target);canonical.bearish.session=BearishSessionState(session_date=target)
for engine in (canonical.bullish,canonical.bearish):engine.previous_indicators=None;engine.previous_bar=None
canonical.trade_owner='NONE';canonical.session_date=target
rows=replay.candles(json.loads((root/(target.isoformat()+'.json')).read_text())['candles'])
bars={b.ts:b for b in replay.aggregate_exact_5m(rows,target)}
with tempfile.TemporaryDirectory() as td:
 c=HilegaAlignmentDualExitLiveCoordinator(market_sources=SimpleNamespace(),option_expiry=None,step_audit_path=Path(td)/'audit',health_path=Path(td)/'health')
 c.canonical=canonical;c._opening_reference=opening;records=[]
 c._audit=lambda at,stage,status,payload,**kwargs:records.append((at,stage,payload))
 for minute in rows[:7]:c._advance(minute,bars,recovered=True)
 checks=[x[2] for x in records if x[1]=='WMA_GAP_MINUTE_EVALUATION']
 first=next(x for x in checks if x['decision_timestamp'][11:16]=='09:20')
 assert abs(first['directional_wma_strength']-1.7946907758008095)<1e-9
 assert first['reference_crosses_session'] is True
 assert first['reference_bar_timestamp']=='2026-10-07T15:25:00+05:30'
 first_dec=next(x[2] for x in records if x[1]=='DIRECTIONAL_DECISION' and x[0].strftime('%H:%M')=='09:20')
 assert first_dec['canonical_bullish_conditions'].get('previous_rsi9') is None
 assert c.gate.owner=='BEARISH';assert c.gate.active['time'].strftime('%H:%M')=='09:22'
 print(json.dumps({'live_opening_strength':first['directional_wma_strength'],'reference_timestamp':first['reference_bar_timestamp'],'reference_crosses_session':True,'canonical_overnight_crossovers_enabled':False,'entry_time_with_existing_rules':'09:22','status':'PASS'}))
