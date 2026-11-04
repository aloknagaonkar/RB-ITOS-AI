from __future__ import annotations
import argparse,json,statistics
from collections import defaultdict
from pathlib import Path
VERSION="OI_TRANSITION_OUTCOME_ANALYSIS_V1"
def q(v,p):
 x=sorted(z for z in v if z is not None)
 if not x:return None
 if len(x)==1:return x[0]
 a=(len(x)-1)*p;i=int(a);j=min(i+1,len(x)-1);f=a-i
 return x[i]*(1-f)+x[j]*f
def stats(v):
 x=[z for z in v if z is not None]
 return {"n":len(x),"q25":q(x,.25),"median":statistics.median(x) if x else None,"q75":q(x,.75)}
def outcome20(e):
 v=e.get("directional_move_20m_points")
 if v is None:return "UNKNOWN_20M"
 return "CONTINUES_20M" if v>0 else "FAILS_20M"
def signed_move(e,o):
 if not o:return None
 r=o["spot_close"]-e["spot_close"]
 return r if e["direction"]=="BULLISH" else -r
def total_oi(e):
 a=e.get("moving_ce_oi");b=e.get("moving_pe_oi")
 return None if a is None or b is None else a+b
def summarize(xs):
 def S(k,ab=False):return stats([abs(e[k]) if ab and e.get(k) is not None else e.get(k) for e in xs])
 o={"event_count":len(xs),"current_total_oi":stats([total_oi(e) for e in xs]),"activity_5m":S("activity_5m"),"abs_imbalance_5m":S("imbalance_5m",True),"session_activity":S("session_activity"),"abs_session_imbalance":S("session_imbalance",True),"ce_session_delta":S("ce_session_delta"),"pe_session_delta":S("pe_session_delta"),"pcr_change_5m":S("pcr_change_5m"),"pcr_session_change":S("pcr_session_change"),"directional_move_10m_points":S("directional_move_10m_points"),"directional_move_20m_points":S("directional_move_20m_points")}
 for n in (2,3,4):o[f"persists_{n}cp_pct"]=sum(bool(e.get(f"persists_{n}cp")) for e in xs)/len(xs)*100 if xs else None
 return o
def opp_summary(xs):
 ys=[e for e in xs if e.get("first_opposite_candidate_time")]
 return {"event_count":len(xs),"with_opposite_count":len(ys),"minutes_to_opposite":stats([e.get("minutes_to_first_opposite_candidate") for e in ys]),"directional_points_until_opposite":stats([e.get("directional_points_until_first_opposite_candidate") for e in ys]),"opposite_5m_activity":stats([e.get("opposite_activity_5m") for e in ys]),"abs_opposite_5m_imbalance":stats([abs(e["opposite_imbalance_5m"]) if e.get("opposite_imbalance_5m") is not None else None for e in ys]),"opposite_session_activity":stats([e.get("opposite_session_activity") for e in ys]),"abs_opposite_session_imbalance":stats([abs(e["opposite_session_imbalance"]) if e.get("opposite_session_imbalance") is not None else None for e in ys]),"opposite_continues_20m_pct":sum(e.get("opposite_outcome_20m")=="CONTINUES_20M" for e in ys)/len(ys)*100 if ys else None,"opposite_fails_20m_pct":sum(e.get("opposite_outcome_20m")=="FAILS_20M" for e in ys)/len(ys)*100 if ys else None}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
 src=json.loads(Path(a.input).read_text())
 if src.get('research_version')!='OI_PATTERN_CONTROL_TIMING_V1':raise RuntimeError('Expected OI_PATTERN_CONTROL_TIMING_V1')
 ev=sorted(src['events'],key=lambda e:(e['session_date'],e['timestamp'],e['direction']))
 by=defaultdict(list)
 for e in ev:by[e['session_date']].append(e)
 out=[]
 for day,xs in by.items():
  for i,e in enumerate(xs):
   opp=next((x for x in xs[i+1:] if x['direction']!=e['direction']),None)
   r=dict(e);r['outcome_20m']=outcome20(e);r['first_opposite_candidate_time']=opp['candle_time'] if opp else None
   if opp:
    t0=int(e['candle_time'][:2])*60+int(e['candle_time'][3:]);t1=int(opp['candle_time'][:2])*60+int(opp['candle_time'][3:]);r['minutes_to_first_opposite_candidate']=t1-t0
   else:r['minutes_to_first_opposite_candidate']=None
   r['directional_points_until_first_opposite_candidate']=signed_move(e,opp)
   for k in ('activity_5m','imbalance_5m','session_activity','session_imbalance','pcr_change_5m','pcr_session_change','persists_2cp','persists_3cp','persists_4cp','directional_move_20m_points'):
    r['opposite_'+k]=opp.get(k) if opp else None
   r['opposite_outcome_20m']=outcome20(opp) if opp else None
   out.append(r)
 groups={}
 for dc in ('BULLISH_TREND_DAY','BEARISH_TREND_DAY','MIXED_DAY'):
  groups[dc]={}
  for d in ('BULLISH','BEARISH'):
   groups[dc][d]={oc:summarize([e for e in out if e['day_class']==dc and e['direction']==d and e['outcome_20m']==oc]) for oc in ('CONTINUES_20M','FAILS_20M')}
 aligned=[e for e in out if (e['day_class']=='BULLISH_TREND_DAY' and e['direction']=='BULLISH') or (e['day_class']=='BEARISH_TREND_DAY' and e['direction']=='BEARISH')]
 suc=[e for e in aligned if e['outcome_20m']=='CONTINUES_20M'];fail=[e for e in aligned if e['outcome_20m']=='FAILS_20M']
 result={"research_version":VERSION,"source_research_version":src['research_version'],"definitions":{"success_label":"directional_move_20m_points > 0","failure_label":"directional_move_20m_points <= 0","first_opposite_candidate":"first later OI candidate of opposite direction; not automatically a trend change","future_price_used_only_for_label":True,"threshold_frozen":False},"overall_counts":{"events":len(out),"continues_20m":sum(e['outcome_20m']=='CONTINUES_20M' for e in out),"fails_20m":sum(e['outcome_20m']=='FAILS_20M' for e in out),"unknown_20m":sum(e['outcome_20m']=='UNKNOWN_20M' for e in out)},"group_comparison":groups,"aligned_transition_comparison":{"successful":summarize(suc),"failed":summarize(fail),"successful_first_opposite":opp_summary(suc),"failed_first_opposite":opp_summary(fail)},"events":out,"integrity":{"historical_only":True,"detection_rule_unchanged":True,"quantity_threshold_fitted":False,"strategy_rule_changed":False,"paper_or_live_action":False}}
 Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
 print(json.dumps({"research_version":VERSION,"overall_counts":result['overall_counts'],"output":a.output},indent=2))
if __name__=='__main__':main()
