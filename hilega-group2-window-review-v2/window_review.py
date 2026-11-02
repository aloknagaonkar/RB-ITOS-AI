"""Preparation-window proposal only; never arms the controller."""
from datetime import datetime

def assess(control,counts,allocation,*,now,bridge_healthy,route="PREPARATION_ONLY"):
    blockers=[]
    if control.get('mode')!='PAUSED':blockers.append('PAUSED_CONTROLLER_REQUIRED')
    if control.get('session_date')!=now.date().isoformat():blockers.append('CURRENT_CONTROLLER_SESSION_REQUIRED')
    if not bridge_healthy:blockers.append('CURRENT_HEALTHY_BRIDGE_REQUIRED')
    if any(v not in (0,None) for v in counts.values()):blockers.append('NONEMPTY_LIFECYCLE_REQUIRES_REVIEW')
    if route not in {'SIMULATOR','PREPARATION_ONLY'}:blockers.append('VERIFIED_EXECUTION_ROUTE_REQUIRED')
    if route=='SIMULATOR' and allocation is None:blockers.append('SIM_ALLOCATION_CONFIG_UNAVAILABLE')
    elif route=='SIMULATOR' and allocation.get('required') is not True:blockers.append('SIM_ALLOCATION_CONTRACT_REVIEW_REQUIRED')
    elif route=='SIMULATOR':
        funds=allocation.get('funds')
        if not funds:blockers.append('NATIVE_RESUME_REQUIRES_SYNTHETIC_FUNDS')
        else:
            try:
                stamp=datetime.fromisoformat(funds['at'])
                if stamp.tzinfo is None or stamp.date()!=now.date() or not 0<=(now-stamp).total_seconds()<=30:
                    blockers.append('NATIVE_RESUME_SYNTHETIC_FUNDS_STALE')
            except (KeyError,TypeError,ValueError):blockers.append('NATIVE_RESUME_FUNDS_TIMESTAMP_INVALID')
    return dict(blockers=blockers,live_apply_available=False,controller_resumed=False,
        note='Do not inject synthetic funds to satisfy a real-evidence preparation review.',
        remaining_engineering=['PREPARATION_ARM_ASSEMBLY_AND_PROCESS_ROUTE_BINDING',
            'INDEPENDENT_DURABLE_DEADLINE_AND_PAUSE_RECOVERY',
            'DISPOSABLE_WORKER_WINDOW_AND_CRASH_REHEARSAL',
            'EXACT_STATE_BOUND_MAINTENANCE_PLAN'],production_execution_enabled=False)
