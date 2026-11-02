"""Durable candidate coordinator. CLI always closed; Python-only session injection."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import time

STATE='preparation_candidate_coordinator_state_v1'
AUDIT='preparation_candidate_coordinator_audit_v1'
MODEL='HILEGA_DURABLE_CLOSED_APPLICATION_COORDINATOR_V1'
PHASES={'BUY_PENDING','ENTRY_REVIEW','ENTRY_UNKNOWN','WAIT_EXIT','SELL_PENDING',
        'EXIT_REVIEW','EXIT_UNKNOWN','CLOSEOUT_PENDING','RETIRE_PENDING','WAIT_NEXT','PREPARE_PENDING'}
FALSE_FLAGS=('entry_permission','orders_sent_to_upstox','reservation_release_permission','production_execution_enabled')


def need(ok,reason):
    if not ok:raise ValueError(reason)


def result(status,*,phase=None,entry_id=None,candidate=False,db_open=False,**kwargs):
    return dict(status=status,phase=phase,entry_id=entry_id,candidate_session_used=candidate,
        application_database_opened=db_open,token_loaded=False,
        **{k:False for k in FALSE_FLAGS},**kwargs)


def worker_tick(session=None):
    if session is None:return result('EXECUTION_COORDINATOR_CLOSED_IN_CODE')
    need(type(session) is CandidateSession,'EXACT_CANDIDATE_SESSION_REQUIRED')
    return session.tick()


class CandidateSession:
    def __init__(self,app,adapter,source,pin,authority,*,journal,seed_request_id,
                 bridge_run_id,providers,clock,fee_buffer_cents=10000,checkpoint=lambda at:None):
        need(set(providers)=={'entry','account','exit','next'} and all(callable(p) for p in providers.values()),
             'EXACT_COORDINATOR_EVIDENCE_PROVIDERS_REQUIRED')
        need(type(fee_buffer_cents) is int and fee_buffer_cents>0,'POSITIVE_COORDINATOR_FEE_BUFFER_REQUIRED')
        self.app,self.adapter,self.source,self.pin,self.authority=app,adapter,source,pin,authority
        self.journal=Path(journal);self.seed=seed_request_id;self.bridge=bridge_run_id
        self.providers,self.clock,self.buffer,self.checkpoint=providers,clock,fee_buffer_cents,checkpoint
        from market_lab.hilega_exclusive_closed_route_v1 import exclusive_coordinator_guard
        self.tick=exclusive_coordinator_guard(type(self).tick).__get__(self,type(self))

    def _runtime(self):
        from market_lab.hilega_execution_port_v1 import adapter as port
        from market_lab.hilega_preparation_runtime_v1.source import Source
        from application_lifecycle_candidate_v1 import exact
        exact(self.app,self.adapter,self.pin,self.authority)
        need(type(self.source) is Source and self.source.s.store.path.resolve()==self.app.path.resolve()
             and self.source.run_id==self.bridge,'EXACT_COORDINATOR_SOURCE_REQUIRED')
        need(all(p.is_file() and not p.is_symlink() for p in (self.app.path,self.adapter.store.path,self.journal)),
             'REGULAR_COORDINATOR_SOURCES_REQUIRED')
        return port

    def _binding(self):
        return dict(account_scope=self.pin['scope'],application=str(self.app.path.resolve()),
            adapter=str(self.adapter.store.path.resolve()),journal=str(self.journal.resolve()),
            seed_request_id=self.seed,bridge_run_id=self.bridge,authority_id=self.authority['authority_id'],
            coordinator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    def _seal(self,row):
        from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
        value=deepcopy(row);value.pop('signature',None);value['signature']=sign(value,self.pin)
        need(len(json.dumps(value))<=4_000_000,'COORDINATOR_STATE_TOO_LARGE');return value

    def _verify(self,row):
        from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
        value=dict(row);signature=value.pop('signature',None)
        need(isinstance(signature,str) and hmac.compare_digest(sign(value,self.pin),signature),
             'COORDINATOR_STATE_SIGNATURE_INVALID')
        need(row['model']==MODEL and row['binding']==self._binding() and row['phase'] in PHASES
             and type(row['version']) is int and row['version']>=1
             and all(row.get(k) is False for k in FALSE_FLAGS),'COORDINATOR_STATE_BINDING_CHANGED')
        return row

    @contextmanager
    def _lock(self):
        path=Path(str(self.app.path)+'.candidate-coordinator.lock')
        fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(fd)
            need(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)&0o077==0,
                 'PRIVATE_COORDINATOR_LOCK_REQUIRED')
            fcntl.flock(fd,fcntl.LOCK_EX);yield
        finally:os.close(fd)

    def _journal(self,state):
        from market_lab.hilega_production_simulator_bridge_v1 import verified_records
        records=verified_records(self.journal);seq=state['scan_sequence']
        need(type(seq) is int and 0<=seq<=len(records)
             and (seq==0 or records[seq-1]['record_hash']==state['scan_hash']),
             'COORDINATOR_JOURNAL_PREFIX_CHANGED')
        if state.get('exit_sequence'):
            n=state['exit_sequence'];need(n<=len(records) and records[n-1]['record_hash']==state['exit_hash'],
                                       'COORDINATOR_EXIT_RECORD_CHANGED')
        if state.get('pending_sequence'):
            n=state['pending_sequence'];need(n<=len(records) and records[n-1]['record_hash']==state['pending_hash'],
                                          'COORDINATOR_PENDING_RECORD_CHANGED')
        return records

    def _load(self):
        from market_lab.hilega_production_simulator_bridge_v1 import verified_records,accepted
        with self.app.lock(),self.app.db() as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(STATE,)).fetchone()
            if exists:
                raw=db.execute('SELECT data FROM '+STATE+' WHERE id=1').fetchone()
                need(raw is not None,'COORDINATOR_STATE_MISSING_NO_REBASELINE')
                return self._verify(json.loads(raw[0]))
            need(not db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(AUDIT,)).fetchone(),
                 'COORDINATOR_STATE_MISSING_NO_REBASELINE')
            plan_raw=db.execute('SELECT data FROM preparation_plans WHERE id=?',(self.seed,)).fetchone()
            binding_raw=db.execute('SELECT data FROM preparation_request_bindings WHERE id=?',(self.seed,)).fetchone()
            need(plan_raw is not None and binding_raw is not None,'EXPLICIT_PREPARED_SEED_REQUIRED')
            plan=json.loads(plan_raw[0]);binding=json.loads(binding_raw[0])
            kinds={'HILEGA_ATOMIC_DISABLED_REQUEST_BINDING_V1':'first',
                   'HILEGA_HISTORY_AWARE_DISABLED_REQUEST_BINDING_V1':'history'}
            need(binding['model'] in kinds and plan['account_scope']==self.pin['scope'],
                 'SUPPORTED_COORDINATOR_PREPARATION_REQUIRED')
            records=verified_records(self.journal);seq=plan['source_sequence']
            need(1<=seq<=len(records) and records[seq-1]['record_hash']==plan['source_record_hash'],
                 'COORDINATOR_SEED_JOURNAL_CHANGED')
            events=accepted(records[seq-1]);need(len(events)==1 and events[0]['id']==self.seed and events[0]['role']=='ENTRY',
                                              'SINGLE_COORDINATOR_SEED_ENTRY_REQUIRED')
            archived=db.execute("SELECT 1 FROM sqlite_master WHERE name='preparation_candidate_closed_cycle_archives_v1'").fetchone()
            completed=db.execute('SELECT COUNT(*) FROM preparation_candidate_closed_cycle_archives_v1').fetchone()[0] if archived else 0
            row=self._seal(dict(model=MODEL,binding=self._binding(),phase='BUY_PENDING',entry_id=self.seed,
                entry_event=events[0],kind=kinds[binding['model']],scan_sequence=seq,scan_hash=records[seq-1]['record_hash'],
                exit_sequence=None,exit_hash=None,pending_sequence=None,pending_hash=None,preparation_inputs=None,
                completed_cycles=completed,version=1,**{k:False for k in FALSE_FLAGS}))
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE '+STATE+'(id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
            db.execute('CREATE TABLE '+AUDIT+'(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL)')
            db.execute('INSERT INTO '+STATE+' VALUES(1,?)',(json.dumps(row,sort_keys=True),))
            return row

    def _write(self,db,old,new,status):
        raw=db.execute('SELECT data FROM '+STATE+' WHERE id=1').fetchone()
        need(raw is not None and self._verify(json.loads(raw[0]))==old,'COORDINATOR_STATE_CHANGED')
        new=deepcopy(new);new['version']=old['version']+1;new=self._seal(new)
        db.execute('UPDATE '+STATE+' SET data=? WHERE id=1',(json.dumps(new,sort_keys=True),))
        audit=self._seal(dict(model='HILEGA_CLOSED_COORDINATOR_TRANSITION_V1',account_scope=self.pin['scope'],
            status=status,from_phase=old['phase'],to_phase=new['phase'],version=new['version'],entry_id=new['entry_id'],
            at=self.clock().isoformat(),**{k:False for k in FALSE_FLAGS}))
        db.execute('INSERT INTO '+AUDIT+'(data) VALUES(?)',(json.dumps(audit,sort_keys=True),))
        return new

    def _save(self,old,new,status):
        with self.app.lock(),self.app.db() as db:
            db.execute('BEGIN IMMEDIATE');return self._write(db,old,new,status)

    def _answer(self,state,status):
        return result(status,phase=state['phase'],entry_id=state['entry_id'],candidate=True,db_open=True,
                      completed_cycles=state['completed_cycles'])

    def _consume_flat_record(self,state,row,events,status):
        from application_cycle_close_v1 import ACTIVE
        from market_lab.hilega_preparation_runtime_v1.source import event_digest
        new=deepcopy(state);new.update(scan_sequence=row['sequence'],scan_hash=row['record_hash'])
        records=self._journal(state)
        with self.app.lock(),self.app.db() as db:
            db.execute('BEGIN IMMEDIATE')
            need(not any(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone() for t in ACTIVE),
                 'COORDINATOR_UNEXPECTED_ACTIVE_PREPARATION')
            raw=db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone();need(raw is not None,'APPLICATION_SOURCE_CURSOR_REQUIRED')
            cursor=json.loads(raw[0]);seq=cursor['sequence']
            need(cursor['path']==str(self.journal.resolve()) and 0<=seq<=len(records)
                 and (seq==0 or records[seq-1]['record_hash']==cursor['hash']), 'APPLICATION_SOURCE_CURSOR_CHANGED')
            need(seq>=state['scan_sequence'],'APPLICATION_SOURCE_BEHIND_COORDINATOR')
            for event in events:
                fp=event_digest(event);old=db.execute('SELECT fingerprint FROM preparation_consumed WHERE id=?',(event['id'],)).fetchone()
                need(old is None or old[0]==fp,'COORDINATOR_CONSUMED_EVENT_CONFLICT')
                db.execute('INSERT OR IGNORE INTO preparation_consumed VALUES(?,?)',(event['id'],fp))
            if seq<row['sequence']:
                need(seq+1==row['sequence'],'APPLICATION_SOURCE_CURSOR_GAP')
                cursor=dict(path=str(self.journal.resolve()),sequence=row['sequence'],hash=row['record_hash'])
                db.execute('UPDATE preparation_source SET data=? WHERE id=1',(json.dumps(cursor,sort_keys=True),))
            new=self._write(db,state,new,status)
        return self._answer(new,status)

    def tick(self):
        port=self._runtime()
        try:self.adapter.transport.check()
        except port.GateClosed:return result('EXECUTION_COORDINATOR_CLOSED_IN_CODE',candidate=True)
        with self._lock():
            state=self._load();records=self._journal(state);phase=state['phase'];new=deepcopy(state)
            if state['kind']=='first':
                import existing_request_attempt_v1 as attempt
                import application_lifecycle_candidate_v1 as life
                import application_cycle_close_v1 as closure
            else:
                import history_aware_attempt_v1 as attempt
                import history_aware_lifecycle_v1 as life
                import history_aware_cycle_close_v1 as closure
            if phase in {'BUY_PENDING','ENTRY_UNKNOWN'}:
                version=self.app.control()['version']
                output=attempt.submit_existing_candidate(self.app,self.adapter,self.pin,self.authority,journal=self.journal,
                    request_id=state['entry_id'],capture_provider=lambda:self.providers['entry'](state['kind']),
                    clock=self.clock,expected_version=version,bridge_run_id=self.bridge)
                if output.get('status')=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE':
                    return self._answer(state,'WORKER_GATE_CLOSED_BEFORE_BUY')
                self.checkpoint('AFTER_BUY_ACTION_BEFORE_STATE')
                request=next(r for r in self.adapter.store.requests() if r['request_id']==state['entry_id'])
                new['phase']='ENTRY_REVIEW' if request.get('order_id') and request['state'] not in {'UNKNOWN','IN_FLIGHT'} else 'ENTRY_UNKNOWN'
                status='WORKER_BUY_ACKNOWLEDGED' if new['phase']=='ENTRY_REVIEW' else 'WORKER_ENTRY_UNKNOWN_HELD'
                return self._answer(self._save(state,new,status),status)
            if phase in {'ENTRY_REVIEW','EXIT_REVIEW'}:
                try:
                    report=life.record_position(self.app,self.adapter,self.pin,self.authority,entry_id=state['entry_id'],
                        capture_provider=self.providers['account'],clock=self.clock)['report']
                except ValueError as exc:
                    if str(exc)=='FULL_TERMINAL_BUY_REQUIRED':return self._answer(state,'WORKER_ENTRY_FILL_PENDING')
                    raise
                if phase=='ENTRY_REVIEW':new['phase']='WAIT_EXIT';status='WORKER_ENTRY_QUANTITY_RECONCILED'
                elif report['status']=='FLAT_CONFIRMED_REFERENCE':new['phase']='CLOSEOUT_PENDING';status='WORKER_FLAT_RECONCILED'
                else:return self._answer(state,'WORKER_'+report['status'])
                self.checkpoint('AFTER_POSITION_ACTION_BEFORE_STATE')
                return self._answer(self._save(state,new,status),status)
            if phase=='WAIT_EXIT':
                self.source.run_source_once(self.journal)
                from market_lab.hilega_production_simulator_bridge_v1 import verified_records,accepted
                from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import aware
                records=verified_records(self.journal)
                if len(records)==state['scan_sequence']:return self._answer(state,'WORKER_WAITING_FOR_EXIT')
                row=records[state['scan_sequence']];events=accepted(row);exits=[e for e in events if e['role']=='EXIT']
                if exits:
                    event=exits[0]
                    need(event['direction']==state['entry_event']['direction'] and event.get('entry_reference_at')
                         and aware(event['entry_reference_at'])==aware(state['entry_event']['event_at']),
                         'WORKER_EXIT_PARENT_CHANGED')
                    new.update(phase='SELL_PENDING',exit_sequence=row['sequence'],exit_hash=row['record_hash'])
                    return self._answer(self._save(state,new,'WORKER_EXIT_BOUNDARY_LINKED'),'WORKER_EXIT_BOUNDARY_LINKED')
                new.update(scan_sequence=row['sequence'],scan_hash=row['record_hash'])
                return self._answer(self._save(state,new,'WORKER_ACTIVE_CYCLE_RECORD_OBSERVED'),'WORKER_ACTIVE_CYCLE_RECORD_OBSERVED')
            if phase in {'SELL_PENDING','EXIT_UNKNOWN'}:
                output=life.submit_source_exit(self.app,self.adapter,self.pin,self.authority,entry_id=state['entry_id'],
                    journal=self.journal,exit_sequence=state['exit_sequence'],capture_provider=self.providers['exit'],
                    clock=self.clock,expected_version=self.app.control()['version'])
                if output.get('status')=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE':
                    return self._answer(state,'WORKER_GATE_CLOSED_BEFORE_SELL')
                self.checkpoint('AFTER_SELL_ACTION_BEFORE_STATE')
                request=next(r for r in self.adapter.store.requests() if r['request_id']==output['exit_id'])
                new['phase']='EXIT_REVIEW' if request.get('order_id') and request['state'] not in {'UNKNOWN','IN_FLIGHT'} else 'EXIT_UNKNOWN'
                status='WORKER_SELL_ACKNOWLEDGED' if new['phase']=='EXIT_REVIEW' else 'WORKER_EXIT_UNKNOWN_HELD'
                return self._answer(self._save(state,new,status),status)
            if phase=='CLOSEOUT_PENDING':
                closure.record_closeout(self.app,self.adapter,self.pin,self.authority,entry_id=state['entry_id'],
                    journal=self.journal,exit_sequence=state['exit_sequence'],capture_provider=self.providers['account'],clock=self.clock)
                self.checkpoint('AFTER_CLOSEOUT_ACTION_BEFORE_STATE');new['phase']='RETIRE_PENDING'
                return self._answer(self._save(state,new,'WORKER_CLOSEOUT_RECORDED'),'WORKER_CLOSEOUT_RECORDED')
            if phase=='RETIRE_PENDING':
                closure.retire_references(self.app,self.adapter,self.pin,self.authority,entry_id=state['entry_id'],
                    capture_provider=self.providers['account'],clock=self.clock)
                self.checkpoint('AFTER_RETIREMENT_ACTION_BEFORE_STATE')
                new.update(phase='WAIT_NEXT',scan_sequence=state['exit_sequence'],scan_hash=state['exit_hash'],
                    entry_id=None,entry_event=None,exit_sequence=None,exit_hash=None,completed_cycles=state['completed_cycles']+1)
                return self._answer(self._save(state,new,'WORKER_CYCLE_RETIRED'),'WORKER_CYCLE_RETIRED')
            if phase=='PREPARE_PENDING':
                from worker_history_preparation_v1 import prepare_next_disabled
                options=deepcopy(state['preparation_inputs'])
                output=prepare_next_disabled(self.app,self.adapter,self.pin,self.authority,journal=self.journal,
                    sequence=state['pending_sequence'],clock=self.clock,**options)
                self.checkpoint('AFTER_NEXT_PREPARATION_ACTION_BEFORE_STATE')
                from market_lab.hilega_production_simulator_bridge_v1 import accepted
                event=accepted(records[state['pending_sequence']-1])[0]
                new.update(phase='BUY_PENDING',entry_id=output['request_id'],entry_event=event,kind='history',
                    scan_sequence=state['pending_sequence'],scan_hash=state['pending_hash'],
                    pending_sequence=None,pending_hash=None,preparation_inputs=None)
                return self._answer(self._save(state,new,'WORKER_NEXT_PREPARATION_COMMITTED'),'WORKER_NEXT_PREPARATION_COMMITTED')
            if phase=='WAIT_NEXT':
                from market_lab.hilega_production_simulator_bridge_v1 import accepted
                from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import aware,day
                if len(records)==state['scan_sequence']:return self._answer(state,'WORKER_WAITING_FOR_FRESH_SIGNAL')
                row=records[state['scan_sequence']];events=accepted(row)
                if len(events)!=1 or events[0]['role']!='ENTRY':
                    return self._consume_flat_record(state,row,events,'WORKER_FLAT_RECORD_OBSERVED')
                event=events[0]
                with self.app.db() as db:
                    consumed=db.execute('SELECT 1 FROM preparation_consumed WHERE id=?',(event['id'],)).fetchone()
                if consumed:return self._consume_flat_record(state,row,events,'WORKER_ALREADY_CONSUMED_NO_REPLAY')
                control=self.app.control();now=self.clock()
                if control['mode']!='ARMED':return self._answer(state,'WORKER_WAITING_FOR_EXPLICIT_RESUME')
                if control['session_date']!=day(now):return self._answer(state,'WORKER_WAITING_FOR_CURRENT_SESSION')
                if not control.get('resumed_at') or aware(event['event_at'])<=aware(control['resumed_at']) or day(aware(event['event_at']))!=day(now) or not 0<=(now-aware(event['event_at'])).total_seconds()<=60:
                    return self._consume_flat_record(state,row,events,'WORKER_OLD_SIGNAL_NOT_ELIGIBLE')
                supplied=deepcopy(self.providers['next'](event))
                need(isinstance(supplied,dict) and set(supplied)=={'account','market'},'EXACT_WORKER_NEXT_CAPTURES_REQUIRED')
                from history_aware_cycle_close_v1 import review_next_entry
                review_next_entry(self.app,self.adapter,self.pin,self.authority,journal=self.journal,sequence=row['sequence'],
                    account_capture=supplied['account'],market_bundle=supplied['market'],fee_buffer_cents=self.buffer,
                    clock=self.clock,expected_version=control['version'],bridge_run_id=self.bridge)
                new.update(phase='PREPARE_PENDING',pending_sequence=row['sequence'],pending_hash=row['record_hash'],
                    preparation_inputs=dict(account_capture=supplied['account'],market_bundle=supplied['market'],
                        fee_buffer_cents=self.buffer,expected_version=control['version'],bridge_run_id=self.bridge))
                return self._answer(self._save(state,new,'WORKER_NEXT_INPUTS_COMMITTED'),'WORKER_NEXT_INPUTS_COMMITTED')
            raise ValueError('COORDINATOR_PHASE_UNSUPPORTED')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--once',action='store_true');mode.add_argument('--watch',action='store_true')
    parser.add_argument('--interval',type=float,default=5);parser.add_argument('--max-ticks',type=int)
    args=parser.parse_args()
    if not 1<=args.interval<=60 or args.max_ticks is not None and args.max_ticks<1:parser.error('invalid polling bounds')
    ticks=0
    while True:
        print(json.dumps(worker_tick()),flush=True);ticks+=1
        if args.once or args.max_ticks is not None and ticks>=args.max_ticks:return 0
        time.sleep(args.interval)

if __name__=='__main__':raise SystemExit(main())
