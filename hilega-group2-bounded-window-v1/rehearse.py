"""Actual deployed candidate worker and native controller in disposable state only."""
import hashlib,json,os,subprocess,sys,time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import sqlite3
from window import need,save

def run(bundle,workspace,*,kill_initiator):
    workspace.mkdir(mode=0o700);save(workspace/'DISPOSABLE-WINDOW.json',dict(model='HILEGA_DISPOSABLE_WINDOW_V1',workspace=str(workspace.resolve())))
    journal=workspace/'observation-fixture.jsonl'
    record=dict(sequence=1,previous_hash=None,stage='COMBINED_PRICE_OBSERVATION',status='PROCESSED',payload=dict(
        policy_id='BULLISH_GAP2_FULL_WMA2',strategy_version='bullish-gap2-full-wma2-2.0.0-wma40-reversal',
        decision_timestamp=datetime.now(ZoneInfo('Asia/Kolkata')).isoformat()))
    record['record_hash']=hashlib.sha256(json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
    journal.write_text(json.dumps(record)+'\n');envfile=workspace/'empty.env';envfile.write_text('')
    env=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(workspace),PYTHONDONTWRITEBYTECODE='1',
        HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='1',
        HILEGA_PRODUCTION_EXECUTION_ROUTE='PREPARATION_ONLY',HILEGA_PRODUCTION_SIM_DB=str(workspace/'application.sqlite'),
        HILEGA_PREPARATION_ADAPTER_DB=str(workspace/'adapter.sqlite'),HILEGA_PREPARATION_CAPTURE_ON_SIGNAL='0',
        PYTHONPATH=os.pathsep.join(map(str,[bundle/'backend',bundle/'runtime'])))
    logs=[];worker=None;arm=None
    def launch(command,name):
        out=open(workspace/(name+'.log'),'w');logs.append(out)
        return subprocess.Popen(command,cwd=workspace,env=env,stdout=out,stderr=subprocess.STDOUT)
    def control():
        db=sqlite3.connect((workspace/'application.sqlite').as_uri()+'?mode=ro',uri=True)
        try:return json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        finally:db.close()
    try:
        worker=launch([sys.executable,'-B',str(bundle/'closed_worker_launcher.py'),'--watch','--env-file',str(envfile),'--source',str(journal)],'worker')
        until=time.monotonic()+20
        while True:
            need(worker.poll() is None and time.monotonic()<until,'DISPOSABLE_WORKER_STARTUP_FAILED')
            try:
                db=sqlite3.connect((workspace/'application.sqlite').as_uri()+'?mode=ro',uri=True)
                try:ready=db.execute('SELECT COUNT(*) FROM preparation_source').fetchone()[0]==1
                finally:db.close()
                if ready:break
            except sqlite3.Error:pass
            time.sleep(.2)
        arm=launch([sys.executable,'-B',str(Path(__file__).with_name('arm.py')),'--bundle',str(bundle),'--workspace',str(workspace)],'arm')
        until=time.monotonic()+15
        while not (workspace/'ARMED.json').exists():
            need(arm.poll() is None and time.monotonic()<until,'DISPOSABLE_NATIVE_ARM_FAILED');time.sleep(.1)
        need(control()['mode']=='ARMED','REHEARSAL_DID_NOT_ARM')
        if kill_initiator:arm.kill();arm.wait(timeout=5)
        until=time.monotonic()+20
        while not (workspace/'GUARD-RESULT.json').exists():
            need(worker.poll() is None and time.monotonic()<until,'INDEPENDENT_PAUSE_RECOVERY_FAILED');time.sleep(.2)
        need(json.loads((workspace/'GUARD-RESULT.json').read_text())['trigger']=='PAUSE_ON_DEADLINE','WINDOW_PAUSED_BEFORE_INDEPENDENT_DEADLINE_TEST')
        need(control()['mode']=='PAUSED','DISPOSABLE_WINDOW_LEFT_ARMED')
        if not kill_initiator:need(arm.wait(timeout=5)==0,'ARM_PROCESS_FAILED')
        db=sqlite3.connect((workspace/'application.sqlite').as_uri()+'?mode=ro',uri=True)
        try:
            for table in ('intents','sim_orders','sim_fills','preparation_plans','preparation_outbox','preparation_shadow_holds'):
                need(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0,'UNEXPECTED_DISPOSABLE_ACTIVITY')
            cursor=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0]);need(cursor['sequence']==1,'CURSOR_REPLAY_DETECTED')
        finally:db.close()
        need(not (workspace/'adapter.sqlite').exists(),'ADAPTER_OPENED_UNEXPECTEDLY')
        return dict(actual_candidate_worker_executed=True,native_resume_and_pause_used=True,
            initiator_sigkill_tested=kill_initiator,independent_deadline_pause_verified=True,
            disposable_databases_only=True,non_signal_observation_fixture_only=True,fresh_signal_preparation_verified=False)
    finally:
        if arm and arm.poll() is None:arm.terminate();arm.wait(timeout=5)
        if worker and worker.poll() is None:worker.terminate();worker.wait(timeout=10)
        # Any remaining guard is confined to this disposable workspace and has a 12-second deadline.
        for f in logs:f.close()
