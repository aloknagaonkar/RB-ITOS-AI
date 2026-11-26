"""Native decision routing for observation only. No broker, database or service calls."""
import math
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from native_contract import accepted,POLICY,VERSION,ContractBlocked
STRATEGY='HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT'
IST=ZoneInfo('Asia/Kolkata')
def on_row(self,row,*,current=None):
    p=row.get('payload') or {}
    if not isinstance(p,dict):raise ContractBlocked('SOURCE_PAYLOAD_INVALID')
    # The append-only journal includes older strategies. Never relabel those rows.
    if p.get('policy_id')!=POLICY and p.get('strategy_id')!=STRATEGY:return
    if p.get('policy_id')!=POLICY or p.get('strategy_version')!=VERSION or p.get('strategy_id')!=STRATEGY:
        raise ContractBlocked('SOURCE_POLICY_OR_VERSION_MISMATCH')
    stage=row.get('stage')
    if stage not in {'COMBINED_PRICE_OBSERVATION','DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF'} or row.get('status')!='PROCESSED':return
    if p.get('reconstructed') is True:return
    if stage=='COMBINED_PRICE_OBSERVATION':
        # Producer emits this only for non-recovered completed one-minute input.
        if p.get('accepted_events')!=[]:raise ContractBlocked('PRICE_OBSERVATION_CANNOT_SIGNAL')
        if 'reconstructed' in p and p['reconstructed'] is not False:raise ContractBlocked('INVALID_PRICE_RECONSTRUCTION_FLAG')
        at=minute_time(p.get('decision_timestamp'))
        checkpoint=minute_time(row.get('checkpoint'))
        if at-checkpoint!=timedelta(minutes=1):raise ContractBlocked('COMPLETED_MINUTE_AVAILABILITY_MISMATCH')
        if minute_time(row.get('event_time'))!=at:raise ContractBlocked('PRICE_EVENT_TIME_MISMATCH')
        events=[]
    else:
        events=accepted(row)
        if p.get('reconstructed') is not False and stage=='DIRECTIONAL_DECISION':raise ContractBlocked('SOURCE_RECONSTRUCTION_FLAG_REQUIRED')
        at=minute_time(p.get('decision_timestamp') or p.get('cutoff_timestamp'))
        if at.minute%3:raise ContractBlocked('COMPLETED_THREE_MINUTE_BOUNDARY_REQUIRED')
    current=current or datetime.now(timezone.utc)
    if current.tzinfo is None:raise ContractBlocked('AWARE_OBSERVER_CLOCK_REQUIRED')
    if at.astimezone(IST).date()!=current.astimezone(IST).date():return
    if at>current:raise ContractBlocked('FUTURE_NATIVE_OBSERVATION')
    entries=[e for e in events if e['role']=='ENTRY']
    close=p.get('nifty_close')
    record_price=stage in {'COMBINED_PRICE_OBSERVATION','DIRECTIONAL_DECISION'}
    if record_price and (isinstance(close,bool) or not isinstance(close,(int,float)) or not math.isfinite(close) or close<=0):
        raise ContractBlocked('CONFIRMED_SIGNAL_SPOT_MISSING')
    if record_price:
        key=at.astimezone(timezone.utc).isoformat();previous=self.state['closes'].get(key)
        if previous is not None and previous!=float(close):raise ContractBlocked('CONFLICTING_COMPLETED_MINUTE_PRICE')
        self.state['closes'][key]=float(close)
    if stage=='COMBINED_PRICE_OBSERVATION':return
    # The contract yields exits before entries. All validation above precedes mutation.
    for event in events:
        if event['role']=='EXIT':
            self.request_exit(event['direction'],event['event_at'],event.get('exit_reason') or 'STRATEGY_EXIT')
            continue
        oid='HILEGA-NATIVE-POLICY-'+event['id'][:24]
        if oid in self.state['pending'] or self.store.db.execute('SELECT 1 FROM state WHERE id=?',(oid,)).fetchone():continue
        context=dict(direction=event['direction'],signal_confirmed=True,velocity_confirmed=False,
                     signal_timestamp=event['event_at'],spot=float(close),strategy_version=VERSION,strategy_policy_id=POLICY)
        self.state['pending'][oid]=dict(context=context,audit_sequence=row['sequence'],event_type=event['source_event'])

def minute_time(value):
    try:at=datetime.fromisoformat(value)
    except (TypeError,ValueError):raise ContractBlocked('INVALID_PRICE_TIMESTAMP') from None
    if at.tzinfo is None or at.utcoffset() is None:raise ContractBlocked('AWARE_SOURCE_TIMESTAMP_REQUIRED')
    at=at.astimezone(IST)
    if at.second or at.microsecond:raise ContractBlocked('EXACT_COMPLETED_MINUTE_REQUIRED')
    if not (9*60+16<=at.hour*60+at.minute<=15*60+30):raise ContractBlocked('PRICE_OUTSIDE_SESSION_ENVELOPE')
    return at
