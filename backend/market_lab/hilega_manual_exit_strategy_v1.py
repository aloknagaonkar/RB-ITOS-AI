"""Manual execution reset handshake for alignment coordinator, including restart replay."""
from datetime import datetime
from pathlib import Path
from .hilega_manual_exit_v1 import read,write,worker_lock
DEFAULT_ROOT=Path('data/live-observation/hilega-upstox-sandbox-v2')

def root(coordinator):return getattr(coordinator,'manual_exit_root',DEFAULT_ROOT)
def records(coordinator):return read(root(coordinator)/'manual-exit.json')['requests']

def apply_manual_control(coordinator,available,*,recovered=False):
 blocked=False
 seen=getattr(coordinator,'_manual_exit_seen',set());coordinator._manual_exit_seen=seen
 for r in records(coordinator):
  if r['strategy_id']!=coordinator.strategy_id or r['session_date']!=available.date().isoformat():continue
  if datetime.fromisoformat(r['requested_at'])>available:continue
  complete=datetime.fromisoformat(r['completed_at']) if r.get('completed_at') else None
  if complete is None or available<=complete:blocked=True
  if complete is None or available<complete or r['request_id'] in seen:continue
  from .hilega_milega_strategy_v1 import SessionState
  from .hilega_milega_bearish_strategy_v1 import BearishSessionState
  before=coordinator.gate.owner
  coordinator.gate.owner='NONE';coordinator.gate.active=None;coordinator.gate.pending.clear()
  if hasattr(coordinator,'price_frames'):
   from .hilega_combined_policy_v1 import reset_pending
   reset_pending(coordinator.gate)
  for name,cls in [('bullish',SessionState),('bearish',BearishSessionState)]:
   engine=getattr(coordinator.canonical,name);locked=engine.session.session_locked
   engine.session=cls(session_date=available.date(),session_locked=locked)
  coordinator.canonical.trade_owner='NONE'
  # Existing alignment episode remains consumed until it breaks. Indicators stay warm.
  coordinator.episode={'BULLISH':True,'BEARISH':True};coordinator.warning_time=None
  seen.add(r['request_id']);blocked=blocked or available<=complete
  if not recovered:
   release_manual_options(coordinator,r,available)
   coordinator._audit(available,'DIRECTIONAL_MANUAL_EXIT_RESET','PROCESSED',dict(request_id=r['request_id'],trade_owner_before=before,trade_owner_after='NONE',exit_reason='MANUAL_EXIT',completed_at=r['completed_at'],accepted_events=[],entry_resume='FRESH_SETUP_ONLY'))
   acknowledge(coordinator,r,available)
 if blocked:
  coordinator.gate.pending.clear()
  if hasattr(coordinator,'price_frames'):
   from .hilega_combined_policy_v1 import reset_pending
   reset_pending(coordinator.gate)
 return blocked

def acknowledge(coordinator,r,now):
 # Lock matches API and basket worker; ack has its own atomic durable file.
 from types import SimpleNamespace
 w=SimpleNamespace(store=SimpleNamespace(path=root(coordinator)/'basket-events.jsonl'))
 with worker_lock(w):
  path=root(coordinator)/'manual-reset-acks.json';data=read(path)
  data[r['request_id']]={'applied_at':now.isoformat(),'completed_at':r['completed_at']};write(path,data)

def release_manual_options(coordinator,r,now):
 from .hilega_milega_option_shadow_lifecycle_v1 import HilegaMilegaOptionShadowLifecycleV1
 from .hilega_milega_pe_option_shadow_lifecycle_v1 import HilegaMilegaPEOptionShadowLifecycleV1
 for attr,cls,side,last in [('ce_shadow',HilegaMilegaOptionShadowLifecycleV1,'BULLISH','_ce_last_update'),('pe_shadow',HilegaMilegaPEOptionShadowLifecycleV1,'BEARISH','_pe_last_update')]:
  lifecycle=getattr(coordinator,attr,None);snapshot=getattr(lifecycle,'snapshot',None)
  if snapshot is None:continue
  if datetime.fromisoformat(snapshot.signal_boundary)>datetime.fromisoformat(r['completed_at']):continue
  if snapshot.status not in {'ACTIVE','INCOMPLETE'}:continue
  # Preserve immutable observation evidence; do not fabricate exact-minute option exits.
  coordinator._audit(now,side+'_OPTION_MANUAL_RELEASE','PROCESSED',dict(request_id=r['request_id'],exit_reason='MANUAL_EXIT',actual_fills_location='sandbox-manual-exit-ledger',prior_snapshot=snapshot.payload()))
  setattr(coordinator,attr,cls());setattr(coordinator,last,None)

 # Retire stale pending entry recovery; preserve its evidence in the audit.
 for side,pending,paired in [('BULLISH','_pending_ce_entries','_pending_ce_entry_exits'),('BEARISH','_pending_pe_entries','_pending_pe_entry_exits')]:
  store=getattr(coordinator,pending,{})
  for key,lifecycle in list(store.items()):
   snapshot=getattr(lifecycle,'snapshot',None)
   if snapshot and datetime.fromisoformat(snapshot.signal_boundary)<=datetime.fromisoformat(r['completed_at']):
    coordinator._audit(now,side+'_OPTION_MANUAL_PENDING_RELEASE','PROCESSED',dict(request_id=r['request_id'],prior_snapshot=snapshot.payload()))
    store.pop(key,None);getattr(coordinator,paired,{}).pop(key,None)

def after_bootstrap(coordinator,now):
 for r in records(coordinator):
  if r['request_id'] not in getattr(coordinator,'_manual_exit_seen',set()) or not r.get('completed_at'):continue
  if r['session_date']!=now.date().isoformat():continue
  release_manual_options(coordinator,r,now);acknowledge(coordinator,r,now)
