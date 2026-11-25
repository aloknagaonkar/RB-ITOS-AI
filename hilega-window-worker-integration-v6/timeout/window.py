"""Durable candidate state machine. Transport and controller are injected explicitly."""
import json,os,tempfile
from pathlib import Path

def need(ok,reason):
    if not ok:raise ValueError(reason)

def save(path,state):
    path=Path(path);need(not path.is_symlink(),'REGULAR_WINDOW_STATE_REQUIRED')
    fd,name=tempfile.mkstemp(prefix='.window-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(state,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(name):os.unlink(name)

def intent(*,version,session,sequence,now,duration):
    need(type(duration) is int and 1<=duration<=300,'BOUNDED_DURATION_REQUIRED')
    need(type(version) is int and type(sequence) is int and version>=0 and sequence>=0,'EXACT_BASELINE_REQUIRED')
    return dict(model='HILEGA_BOUNDED_PREPARATION_WINDOW_CANDIDATE_V1',phase='DEADLINE_PERSISTED',
        version=version,session=session,source_sequence=sequence,created_at=now,deadline=now+duration,
        production_execution_enabled=False,live_apply_available=False)

def admit(state,current,*,now,guard_ready):
    need(state['phase']=='DEADLINE_PERSISTED','WINDOW_ALREADY_USED')
    need(guard_ready,'INDEPENDENT_GUARD_REQUIRED')
    need(state['created_at']<=now<state['deadline'],'WINDOW_EXPIRED_OR_CLOCK_REWOUND')
    need(current['mode']=='PAUSED' and current['version']==state['version'] and current['session']==state['session'],'BASELINE_CHANGED')
    need(current['empty'] is True and current['route']=='PREPARATION_ONLY' and current['gate_closed'] is True,'CLOSED_EMPTY_PREPARATION_REQUIRED')
    return dict(state,phase='ARM_REQUESTED')

def decision(state,*,now,mode,preparations):
    if mode=='PAUSED':return 'ALREADY_PAUSED'
    if preparations>0:return 'PAUSE_ON_PREPARATION'
    if now<state['created_at']:return 'PAUSE_ON_CLOCK_REWIND'
    if now>=state['deadline']:return 'PAUSE_ON_DEADLINE'
    return 'WAIT'
