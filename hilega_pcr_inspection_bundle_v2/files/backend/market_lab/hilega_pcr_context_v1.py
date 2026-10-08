"""Read-only, causal joins to persisted PCR observations. No strategy or order mutations."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Request, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .storage import Observation, strike_positioning_results
router=APIRouter(prefix='/api/live-shadow/hilega-pcr')
IST=ZoneInfo('Asia/Kolkata')
VOTES={'CE':{'LONG_BUILDUP':1,'SHORT_COVERING':1,'SHORT_BUILDUP':-1,'LONG_UNWINDING':-1},'PE':{'LONG_BUILDUP':-1,'SHORT_COVERING':-1,'SHORT_BUILDUP':1,'LONG_UNWINDING':1}}
def stamp(x):
    d=datetime.fromisoformat(x.replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('Timezone required')
    return d

def combined(ce,pe):
    if not ce or not pe or any(r.get('status')!='AVAILABLE' for r in (ce,pe)):return 'UNAVAILABLE'
    votes=[VOTES[r['side']].get(r['classification'],0) for r in (ce,pe)]
    if not any(votes):return 'NEUTRAL'
    if 1 in votes and -1 in votes:return 'MIXED'
    return 'BULLISH' if sum(votes)>0 else 'BEARISH'

def summary(records,side):
    if not records or any(r.get('status')!='AVAILABLE' for r in records):return 'UNAVAILABLE'
    weights={}
    for r in records:
        c=r['classification'];weights[c]=weights.get(c,0)+abs(r.get('observed_oi_change') or 0)
    total=sum(weights.values())
    if not total:return 'NEUTRAL'
    c,w=max(weights.items(),key=lambda p:p[1])
    return c if w/total>=.6 else 'MIXED'

def panel_context(panel,snapshot,records):
    strikes=panel.get('strikes') or [];out=[]
    quotes={q['key']:q for q in snapshot['quotes']}
    catalog={(c['strike'],c['side']):c['key'] for c in snapshot['catalog']}
    for strike in strikes:
        sides={side:next((r for r in records if r['strike']==strike and r['side']==side),None) for side in ('CE','PE')}
        oi={side:quotes.get(catalog.get((strike,side)),{}).get('oi') for side in ('CE','PE')}
        out.append(dict(strike=strike,ce=sides['CE'],pe=sides['PE'],ce_oi=oi['CE'],pe_oi=oi['PE'],pcr=oi['PE']/oi['CE'] if oi['CE'] and oi['PE'] is not None else None,combined_bias=combined(sides['CE'],sides['PE'])))
    totals={};classes={}
    for side in ('CE','PE'):
        selected=[x[side.lower()] for x in out]
        valid=bool(selected) and all(r and r.get('status')=='AVAILABLE' and r.get('baseline_oi') is not None and r.get('current_oi') is not None for r in selected)
        base=sum(r['baseline_oi'] for r in selected) if valid else 0
        totals[side]=100*(sum(r['current_oi'] for r in selected)-base)/base if base>0 else None
        classes[side]=summary(selected,side) if valid else 'UNAVAILABLE'
    valid=bool(out) and all(x['combined_bias']!='UNAVAILABLE' for x in out)
    positive=negative=0
    for x in out:
        for side in ('CE','PE'):
            r=x[side.lower()]
            if r:
                w=abs(r.get('observed_oi_change') or 0);v=VOTES[side].get(r['classification'],0)
                positive+=w if v>0 else 0;negative+=w if v<0 else 0
    total=positive+negative
    bias='UNAVAILABLE' if not valid else 'NEUTRAL' if total==0 else 'BULLISH' if positive/total>=.6 else 'BEARISH' if negative/total>=.6 else 'MIXED'
    complete=bool(out) and all(x['ce_oi'] is not None and x['pe_oi'] is not None for x in out)
    ceoi=sum(x['ce_oi'] for x in out) if complete else 0
    return dict(mode=panel['mode'],atm=panel.get('atm'),pcr=sum(x['pe_oi'] for x in out)/ceoi if ceoi>0 else None,ce_oi_change_pct=totals['CE'],pe_oi_change_pct=totals['PE'],ce_positioning=classes['CE'],pe_positioning=classes['PE'],combined_bias=bias,strikes=out,received=panel.get('received'),expected=panel.get('expected'))

def choose_observation(rows,at,expiry=None):
    eligible=[]
    for row in rows:
        s=row.snapshot
        try:available=max(stamp(row.recorded_at),stamp(s['received_at']))
        except (ValueError,KeyError,TypeError):continue
        if available<=at and s.get('provider')=='upstox' and s.get('underlying')=='NSE_INDEX|Nifty 50' and (not expiry or s.get('expiry')==expiry):eligible.append((available,row.id,row))
    return max(eligible,key=lambda x:(x[0],x[1])) if eligible else None

@router.get('/context')
def context(request:Request,at:str|None=None,expiry:str|None=None,horizon:int=Query(300),max_age:int=Query(120,ge=1,le=300)):
    if horizon not in (300,900,1800):raise HTTPException(422,'Invalid comparison horizon')
    try:boundary=stamp(at) if at else datetime.now(timezone.utc)
    except ValueError as e:raise HTTPException(422,str(e))
    day=boundary.astimezone(IST).date().isoformat()
    with Session(request.app.state.engine) as db:
        rows=db.scalars(select(Observation).where(Observation.session_date==day)).all()
        match=choose_observation(rows,boundary,expiry)
        empty=dict(status='UNAVAILABLE',decision_time=boundary.isoformat(),panels=[],strikes=[],reason='NO_CAUSAL_SAME_SESSION_UPSTOX_OBSERVATION')
        if not match:return empty
        available,_,row=match;age=(boundary-available).total_seconds()
        if age>max_age:return {**empty,'reason':'STALE_PCR_OBSERVATION','age_seconds':age,'observation_id':row.id}
        records=strike_positioning_results(db,row.config_id,horizon,row.id)
        # A baseline received earlier but persisted later was not available at decision time.
        causal_times={r.snapshot.get('received_at') for r in rows if r.config_id==row.config_id and choose_observation([r],boundary,row.snapshot['expiry'])}
        for record in records:
            if record.get('baseline_received_at') not in causal_times:
                record.update(status='UNAVAILABLE',classification='UNAVAILABLE',observed_oi_change_pct=None,observed_oi_change=None)
        panels=[panel_context(p,row.snapshot,records) for p in row.evaluation['results'] if p['mode'] in ('fixed','moving')]
        all_strikes=sorted({r['strike'] for r in records});strikes=[]
        for strike in all_strikes:
            ce=next((r for r in records if r['strike']==strike and r['side']=='CE'),None);pe=next((r for r in records if r['strike']==strike and r['side']=='PE'),None)
            strikes.append(dict(strike=strike,ce_key=ce.get('instrument_key') if ce else None,pe_key=pe.get('instrument_key') if pe else None,combined_bias=combined(ce,pe)))
        return dict(status='AVAILABLE',decision_time=boundary.isoformat(),available_at=available.isoformat(),age_seconds=age,observation_id=row.id,expiry=row.snapshot['expiry'],horizon_seconds=horizon,panels=panels,strikes=strikes,bias_method='Absolute OI-change weighted votes; 60% directional dominance. Diagnostic only.')
