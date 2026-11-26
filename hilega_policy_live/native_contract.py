"""Candidate native RSI audit adapter. No database, broker or service operations."""
import hashlib
import json
from datetime import datetime, time
from zoneinfo import ZoneInfo
POLICY='RSI_TWO_ROUTE_CONFIRMED_MIDPOINT'
VERSION='rsi-two-route-1.0.0-3m-native-confirmed-midpoint'
IST=ZoneInfo('Asia/Kolkata')
ENTRIES={'ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21':'BULLISH','ENTRY_BEARISH_ROUTE_B_STRUCTURAL':'BEARISH'}
EXITS={'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21':'BULLISH','STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21':'BEARISH'}
class ContractBlocked(ValueError):pass
def need(ok,reason):
    if not ok:raise ContractBlocked(reason)
def aware(value):
    try:at=datetime.fromisoformat(value)
    except (ValueError,TypeError):raise ContractBlocked('INVALID_SOURCE_TIMESTAMP') from None
    need(at.tzinfo is not None and at.utcoffset() is not None,'AWARE_SOURCE_TIMESTAMP_REQUIRED');return at.astimezone(IST)
def key(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
def accepted(record):
    need(isinstance(record,dict),'SOURCE_RECORD_INVALID')
    if record.get('stage') not in {'DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF'} or record.get('status')!='PROCESSED':return []
    p=record.get('payload');need(isinstance(p,dict),'SOURCE_PAYLOAD_INVALID')
    names=p.get('accepted_events',[]);need(isinstance(names,list) and all(isinstance(n,str) for n in names),'ACCEPTED_EVENTS_INVALID')
    if not names or p.get('reconstructed') is True:return []
    need(p.get('policy_id')==POLICY and p.get('strategy_version')==VERSION,'SOURCE_POLICY_OR_VERSION_MISMATCH')
    if record['stage']=='DIRECTIONAL_DECISION':need(p.get('reconstructed') is False,'SOURCE_RECONSTRUCTION_FLAG_REQUIRED')
    need(len(set(names))==len(names),'DUPLICATE_EVENT_IN_BOUNDARY')
    need(all(n in ENTRIES or n in EXITS for n in names),'UNKNOWN_ACCEPTED_EVENT')
    need(len(names)<=2 and sum(n in ENTRIES for n in names)<=1 and sum(n in EXITS for n in names)<=1,'AMBIGUOUS_ACCEPTED_EXECUTION')
    if len(names)==2:
        en=next(n for n in names if n in ENTRIES);ex=next(n for n in names if n in EXITS)
        need(ENTRIES[en]!=EXITS[ex],'SAME_DIRECTION_EXIT_ENTRY_NOT_SUPPORTED')
    at=aware(p.get('decision_timestamp') or p.get('cutoff_timestamp'))
    need(at.second==0 and at.microsecond==0 and at.minute%3==0,'COMPLETED_THREE_MINUTE_BOUNDARY_REQUIRED')
    need(time(9,18)<=at.time()<=time(15,30),'SOURCE_BOUNDARY_OUTSIDE_REGULAR_SESSION_ENVELOPE')
    if record['stage']=='DIRECTIONAL_SESSION_CUTOFF':
        need(not any(n in ENTRIES for n in names),'CUTOFF_CANNOT_OPEN_ENTRY')
        need(at.time()==time(15,30),'NATIVE_CUTOFF_TIME_MISMATCH')
    details=p.get('event_details');need(isinstance(details,list),'CONFIRMED_EVENT_DETAILS_REQUIRED')
    result=[]
    for name in sorted(names,key=lambda n:0 if n in EXITS else 1):
        ds=[d for d in details if isinstance(d,dict) and d.get('event_type')==name]
        need(len(ds)==1,'EVENT_DETAIL_TIME_OR_IDENTITY_MISMATCH');d=ds[0]
        need(aware(d.get('event_time'))==at,'EVENT_DETAIL_TIME_OR_IDENTITY_MISMATCH')
        if name in ENTRIES:need(aware(d.get('entry_time'))==at,'ENTRY_CONFIRMATION_TIME_MISMATCH')
        role='ENTRY' if name in ENTRIES else 'EXIT'
        result.append(dict(id=key([POLICY,VERSION,at.isoformat(),name]),role=role,direction=(ENTRIES if role=='ENTRY' else EXITS)[name],event_at=at.isoformat(),source_event=name,qualified_at=d.get('qualified_signal_time'),entry_reference_at=d.get('entry_time') if role=='EXIT' else None,exit_reason=d.get('exit_reason'),source_record_hash=record.get('record_hash'),source_sequence=record.get('sequence')))
    return result
