"""Managed disposable windows with process-consumed synthetic evidence and restart recovery."""
import hashlib,json,os,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
from datetime import datetime
from window import need,save
from fixture_clock import now
from managed_arm import user_bus_environment

def run(bundle,workspace,*,scenario):
    workspace.mkdir(mode=0o700);workspace=workspace.resolve();here=Path(__file__).absolute().parent
    save(workspace/'DISPOSABLE-WINDOW.json',dict(model='HILEGA_DISPOSABLE_WINDOW_V1',workspace=str(workspace)))
    save(workspace/'FIXTURE-CLOCK.json',dict(market_started='2026-10-26T09:29:55+05:30',wall_started=time.time(),rate=0))
    env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(workspace),PYTHONDONTWRITEBYTECODE='1',
        HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='1',
        HILEGA_PRODUCTION_EXECUTION_ROUTE='PREPARATION_ONLY',HILEGA_PRODUCTION_SIM_DB=str(workspace/'application.sqlite'),
        HILEGA_PREPARATION_ADAPTER_DB=str(workspace/'adapter.sqlite'),HILEGA_PREPARATION_CAPTURE_ON_SIGNAL='0',
        HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED='1',HILEGA_PREPARATION_PIN_FILE=str(workspace/'synthetic-pin.json'),
        HILEGA_PREPARATION_EVIDENCE_FILE=str(workspace/'synthetic-evidence.json'),
        PYTHONPATH=os.pathsep.join(map(str,[bundle/'backend',bundle/'runtime',here])))
    logs=[];workers=[];arm=None
    def launch(command,label):
        stream=open(workspace/(label+'.log'),'w');logs.append(stream)
        return subprocess.Popen(command,cwd=workspace,env=env,stdout=stream,stderr=subprocess.STDOUT)
    def checked(command,label):
        process=launch(command,label);need(process.wait(timeout=20)==0,'DISPOSABLE_STEP_FAILED: '+label)
    def read(table,sql='SELECT data FROM {table} WHERE id=1',database='application.sqlite'):
        db=sqlite3.connect((workspace/database).as_uri()+'?mode=ro',uri=True)
        try:
            db.execute('PRAGMA query_only=ON');rows=db.execute(sql.format(table=table)).fetchall()
            return json.loads(rows[0][0]) if rows else None
        finally:db.close()
    def count(table,database='application.sqlite'):
        return read(table,'SELECT json_object(\'count\',COUNT(*)) FROM {table}',database)['count']
    def wait(predicate,timeout,reason):
        until=time.monotonic()+timeout
        while True:
            try:
                if predicate():return
            except sqlite3.Error:pass
            need(time.monotonic()<until,reason);time.sleep(.1)
    def worker(label):
        process=launch([sys.executable,'-B',str(here/'fixture_worker.py'),'--bundle',str(bundle),'--workspace',str(workspace)],label);workers.append(process);return process
    def append_record(stage,payload):
        journal=workspace/'strategy.jsonl';rows=[json.loads(x) for x in journal.read_text().splitlines() if x]
        record=dict(sequence=len(rows)+1,previous_hash=rows[-1]['record_hash'] if rows else None,stage=stage,status='PROCESSED',payload=payload)
        record['record_hash']=hashlib.sha256(json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
        with journal.open('a') as f:f.write(json.dumps(record)+'\n');f.flush();os.fsync(f.fileno())
    (workspace/'empty.env').write_text('');(workspace/'strategy.jsonl').write_text('')
    checked([sys.executable,'-B',str(here/'prepare_fixture.py'),'--bundle',str(bundle),'--workspace',str(workspace)],'fixture-setup')
    policy=dict(policy_id='BULLISH_GAP2_FULL_WMA2',strategy_version='bullish-gap2-full-wma2-2.0.0-wma40-reversal')
    append_record('COMBINED_PRICE_OBSERVATION',dict(policy,decision_timestamp=now(workspace).isoformat()))
    current_worker=None
    try:
        current_worker=worker('worker-1')
        wait(lambda:read('preparation_source') is not None and read('sim_bridge_health').get('phase')=='RUNNING',20,'DISPOSABLE_WORKER_STARTUP_FAILED')
        arm=launch([sys.executable,'-B',str(here/'managed_arm.py'),'--bundle',str(bundle),'--workspace',str(workspace)],'managed-arm')
        wait(lambda:(workspace/'ARMED.json').exists(),15,'DISPOSABLE_MANAGED_ARM_FAILED')
        need(read('control')['mode']=='ARMED','ARMED_CONTROLLER_REQUIRED')
        if scenario=='fresh-signal':
            # Keep startup deterministic, then advance only three seconds before the next boundary.
            # This retains current bridge/reconciliation evidence and produces a post-resume signal.
            save(workspace/'FIXTURE-CLOCK.json',dict(market_started='2026-10-26T09:29:58+05:30',wall_started=time.time(),rate=1))
            wait(lambda:now(workspace)>=datetime.fromisoformat('2026-10-26T09:30:00+05:30'),5,'FIXTURE_BOUNDARY_NOT_REACHED')
            checked([sys.executable,'-B',str(here/'prepare_fixture.py'),'--bundle',str(bundle),'--workspace',str(workspace),'--evidence'],'fresh-synthetic-evidence')
            from fixture_records import entry_payload
            append_record('DIRECTIONAL_DECISION',entry_payload('2026-10-26T09:30:00+05:30'))
            wait(lambda:count('preparation_plans')==1,18,'PROCESS_FRESH_PREPARATION_NOT_CREATED; inspect worker-1.log and preparation_events')
            wait(lambda:(workspace/'GUARD-RESULT.json').exists(),8,'MANAGED_PREPARATION_PAUSE_NOT_OBSERVED')
            need(arm.wait(timeout=20)==0,'MANAGED_ARM_PROCESS_FAILED')
            for table in ('preparation_plans','preparation_shadow_holds','preparation_outbox','preparation_request_bindings','preparation_cash_reservations'):need(count(table)==1,'SINGLE_ATOMIC_ROW_REQUIRED: '+table)
            request=read('requests','SELECT data FROM {table}',database='adapter.sqlite')
            binding=read('preparation_request_bindings','SELECT data FROM {table}');cash=read('preparation_cash_reservations','SELECT data FROM {table}')
            need(request['state']=='PREPARED' and request['order_id'] is None and binding['id']==cash['id']==request['reservation_reference'],'DISABLED_REQUEST_BINDING_REQUIRED')
            need(cash['broker_cash_locked'] is False and cash['state']=='RESERVED_DISABLED_REQUEST','LOCAL_DISABLED_CASH_REFERENCE_REQUIRED')
            # Verify signed cash row using the exact bundled validator in an isolated subprocess.
            checked([sys.executable,'-B',str(here/'verify_fixture.py'),'--bundle',str(bundle),'--workspace',str(workspace)],'verify-signed-reservation')
            current_worker.kill();current_worker.wait(timeout=5);current_worker=worker('worker-restart')
            wait(lambda:read('sim_bridge_health').get('phase')=='RUNNING' and read('sim_bridge_health').get('pid')==current_worker.pid,15,'WORKER_RESTART_FAILED')
            time.sleep(5.5)
            need(count('preparation_plans')==count('requests','adapter.sqlite')==1,'RESTART_DUPLICATED_PREPARATION')
            need(read('preparation_source')['sequence']==2,'SOURCE_CURSOR_REWOUND_OR_CHANGED')
            result=dict(fresh_synthetic_signal_consumed_by_worker=True,atomic_binding_and_signed_reservation_verified=True,restart_replay_idempotence_verified=True)
        else:
            # Preserve the durable window while the actual disposable worker is SIGKILLed.
            current_worker.kill();current_worker.wait(timeout=5)
            need(read('control')['mode']=='ARMED','PENDING_ARMED_STATE_NOT_PRESERVED_FOR_RESTART_TEST')
            current_worker=worker('worker-restart')
            wait(lambda:read('control')['mode']=='PAUSED',15,'NATIVE_WORKER_STARTUP_DID_NOT_PAUSE')
            registry=workspace.parent/'RECOVERY-REGISTRY.json';save(registry,dict(model='HILEGA_DISPOSABLE_RECOVERY_REGISTRY_V1',windows=[workspace.name]))
            unit='hilega-disposable-boot-recovery-'+uuid.uuid4().hex+'.service'
            r=subprocess.run(['systemd-run','--user','--wait','--collect','--unit='+unit,'--property=Type=oneshot',
                '--property=TimeoutStartSec=30',sys.executable,'-B',str(here/'recovery.py'),'--registry',str(registry),'--bundle',str(bundle)],
                capture_output=True,text=True,timeout=40,env=user_bus_environment())
            save(workspace/'RECOVERY-UNIT-RESULT.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
            need(r.returncode==0,'MANAGED_PENDING_REGISTRY_RECOVERY_FAILED')
            need(arm.wait(timeout=20)==0,'PENDING_WINDOW_CONTROLLER_PROCESS_FAILED')
            need(json.loads((workspace/'WINDOW.json').read_text())['phase']=='CLOSED','PENDING_WINDOW_NOT_CLOSED')
            need((workspace.parent/'ADMISSION-READY.json').exists(),'RECOVERY_ADMISSION_RECEIPT_MISSING')
            need(read('preparation_source')['sequence']==1 and count('preparation_plans')==0,'RESTART_CHANGED_EMPTY_BASELINE')
            result=dict(native_worker_restart_pauses_persisted_arm=True,managed_pending_registry_recovery_verified=True,actual_vm_reboot_tested=False)
        need(read('control')['mode']=='PAUSED','DISPOSABLE_CONTROLLER_LEFT_ARMED')
        for table in ('intents','sim_orders','sim_fills'):need(count(table)==0,'SIMULATOR_EXECUTION_DETECTED')
        for table in ('attempts','receipts'):need(count(table,'adapter.sqlite')==0,'BROKER_ATTEMPT_DETECTED')
        return dict(scenario=scenario,**result,disposable_databases_only=True,synthetic_clock_injected=True,production_gate_patched=False,orders_sent=False)
    finally:
        unit_path=workspace/'MANAGED-UNIT.json'
        if unit_path.is_file():
            unit=json.loads(unit_path.read_text()).get('unit','')
            if unit.startswith('hilega-disposable-window-') and unit.endswith('.service') and '/' not in unit:
                try:subprocess.run(['systemctl','--user','stop',unit],capture_output=True,timeout=15,env=user_bus_environment())
                except Exception:pass
        if arm and arm.poll() is None:arm.terminate();arm.wait(timeout=10)
        for process in workers:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
        for stream in logs:stream.close()
