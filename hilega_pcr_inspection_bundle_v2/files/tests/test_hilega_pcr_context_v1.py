from datetime import datetime,timedelta
from types import SimpleNamespace
from market_lab.hilega_pcr_context_v1 import combined,panel_context,choose_observation,summary
T=datetime.fromisoformat('2026-10-09T10:00:00+05:30')
def r(side,c,base=100,current=110,strike=22500):
 return dict(side=side,classification=c,status='AVAILABLE',baseline_oi=base,current_oi=current,observed_oi_change=current-base,strike=strike)
def test_exact_strike_combined_signs_and_conflict():
 assert combined(r('CE','LONG_BUILDUP'),r('PE','SHORT_BUILDUP'))=='BULLISH'
 assert combined(r('CE','SHORT_BUILDUP'),r('PE','LONG_BUILDUP'))=='BEARISH'
 assert combined(r('CE','LONG_BUILDUP'),r('PE','LONG_BUILDUP'))=='MIXED'
 assert combined(r('CE','NEUTRAL'),r('PE','NEUTRAL'))=='NEUTRAL'
 assert combined(None,r('PE','LONG_BUILDUP'))=='UNAVAILABLE'
def obs(i,received,recorded=None,expiry='2026-10-13',provider='upstox'):
 return SimpleNamespace(id=i,recorded_at=(recorded or received).isoformat(),snapshot=dict(received_at=received.isoformat(),expiry=expiry,provider=provider,underlying='NSE_INDEX|Nifty 50'))
def test_no_future_or_late_persisted_evidence_or_demo():
 prior=obs(1,T-timedelta(seconds=30))
 rows=[prior,obs(2,T+timedelta(seconds=1)),obs(3,T-timedelta(seconds=10),T+timedelta(seconds=2)),obs(4,T,provider='demo')]
 assert choose_observation(rows,T)[2].id==1
 assert choose_observation(rows,T,'2026-10-20') is None
 assert choose_observation([obs(1,T,expiry='2026-10-20')],T,'2026-10-13') is None
def test_total_oi_is_sum_percentage_not_average_and_pcr():
 records=[r('CE','LONG_BUILDUP',100,120),r('PE','SHORT_BUILDUP',100,120),r('CE','LONG_BUILDUP',900,990,22550),r('PE','SHORT_BUILDUP',900,990,22550)]
 snapshot=dict(catalog=[dict(key=f'{x["strike"]}{x["side"]}',strike=x['strike'],side=x['side']) for x in records],quotes=[dict(key=f'{x["strike"]}{x["side"]}',oi=x['current_oi']) for x in records])
 p=panel_context(dict(mode='moving',strikes=[22500,22550]),snapshot,records)
 assert p['ce_oi_change_pct']==11
 assert p['pcr']==1
 assert p['combined_bias']=='BULLISH'
 assert len(p['strikes'])==2
 # Same current contracts required at baseline; missing baseline never invents OI delta.
 records[0]['status']='UNAVAILABLE'
 assert panel_context(dict(mode='moving',strikes=[22500,22550]),snapshot,records)['ce_oi_change_pct'] is None
 assert panel_context(dict(mode='moving',strikes=[22500,22550]),snapshot,records)['combined_bias']=='UNAVAILABLE'
def test_conflicting_side_summary_weighted_and_empty_range():
 assert summary([r('CE','LONG_BUILDUP',100,105),r('CE','SHORT_BUILDUP',100,105)],'CE')=='MIXED'
 assert panel_context(dict(mode='fixed',strikes=[]),dict(catalog=[],quotes=[]),[])['combined_bias']=='UNAVAILABLE'
def test_context_filters_late_baseline_and_stale_current(monkeypatch):
 import market_lab.hilega_pcr_context_v1 as m
 current=obs(2,T);current.config_id=1
 current.snapshot.update(catalog=[dict(key='CE',strike=22500,side='CE'),dict(key='PE',strike=22500,side='PE')],quotes=[dict(key='CE',oi=110),dict(key='PE',oi=110)])
 current.evaluation=dict(results=[dict(mode='moving',strikes=[22500])])
 baseline=obs(1,T-timedelta(minutes=5),T+timedelta(seconds=1));baseline.config_id=1
 class DB:
  def __init__(self,*a):pass
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def scalars(self,*a):return SimpleNamespace(all=lambda:[baseline,current])
 monkeypatch.setattr(m,'Session',DB)
 def positioning(*a):return [{**r('CE','LONG_BUILDUP'),'instrument_key':'CE','baseline_received_at':baseline.snapshot['received_at']},{**r('PE','SHORT_BUILDUP'),'instrument_key':'PE','baseline_received_at':baseline.snapshot['received_at']}]
 monkeypatch.setattr(m,'strike_positioning_results',positioning)
 request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=None)))
 result=m.context(request,at=T.isoformat(),expiry=None,horizon=300,max_age=120)
 assert result['panels'][0]['combined_bias']=='UNAVAILABLE'
 assert result['observation_id']==2
 stale=m.context(request,at=(T+timedelta(minutes=3)).isoformat(),expiry=None,horizon=300,max_age=120)
 assert stale['status']=='UNAVAILABLE'
 assert stale['reason']=='STALE_PCR_OBSERVATION'
