"""Bounded zero-cash PREPARATION_ONLY rejection test. Never opens broker transport."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from zoneinfo import ZoneInfo

IST=ZoneInfo('Asia/Kolkata')
CASH_REASONS={'NO_CASH_CAPACITY','HALF_CASH_CAP_EXCEEDED'}

class Blocked(RuntimeError): pass

def need(ok,reason):
    if not ok: raise Blocked(reason)

def zero(value):
    try:
        number=Decimal(str(value))
        return number.is_finite() and number==0 and not isinstance(value,bool)
    except Exception:return False

def stamp(value):
    at=datetime.fromisoformat(value.replace('Z','+00:00'))
    need(at.tzinfo is not None,'TIMEZONE_REQUIRED')
    return at

def validate_status(s,modes=('PAUSED',)):
    need(s.get('workspace_mode')=='SIMULATION_ONLY','WORKSPACE_MODE_INVALID')
    need(s.get('production_execution_enabled') is False,'PRODUCTION_FLAG_INVALID')
    need(s.get('production_orders_sent') is False,'PRODUCTION_ORDER_FLAG_INVALID')
    need(s.get('control',{}).get('mode') in modes,'CONTROLLER_MODE_INVALID')
    need(s.get('source')=='EVIDENCE_PREPARATION_ONLY','SOURCE_ROUTE_INVALID')
    p=s.get('application_preparation',{})
    need(p.get('route')=='PREPARATION_ONLY' and p.get('submission_gate')=='CLOSED_IN_CODE','SUBMISSION_GATE_INVALID')
    need(p.get('production_execution_enabled') is False,'PREPARATION_AUTHORITY_INVALID')
    need(p.get('unresolved_preparation_count')==0 and zero(p.get('shadow_held_cents')),'UNRESOLVED_PREPARATION')
    port=s.get('broker_execution_port',{})
    need(port.get('transport_gate')=='CLOSED_IN_CODE' and port.get('live_routing_implemented') is False,'TRANSPORT_NOT_CLOSED')
    need(s.get('bridge_health',{}).get('healthy') is True,'SOURCE_NOT_FRESH')
    broker=s.get('broker_observation',{})
    need(broker.get('status')=='LIVE_READ_ONLY' and broker.get('broker_connected') is True,'BROKER_READ_UNAVAILABLE')
    need(type(broker.get('age_seconds')) in (int,float) and 0<=broker['age_seconds']<=30,'BROKER_OBSERVATION_STALE')
    checks={r.get('check'):r.get('status') for r in broker.get('checks',[])}
    need(all(checks.get(k)=='PASS' for k in ('profile','orders','trades','positions','funds')),'BROKER_CHECK_INCOMPLETE')
    need(all(broker.get(k)==[] for k in ('orders','trades','positions')),'BROKER_ACTIVITY_REQUIRES_REVIEW')
    funds=broker.get('funds',{})
    need(funds.get('status')=='PASS' and zero(funds.get('cash_available_to_trade')),'ZERO_CASH_REQUIRED')
    need(funds.get('field')=='data.available_to_trade.cash_available_to_trade.total','FUNDS_FIELD_CHANGED')
    need(not s.get('durable_execution',{}).get('stop_requested',False),'DURABLE_STOP_PENDING')

def validate_window(now,seconds):
    need(type(seconds) is int and 60<=seconds<=600,'DURATION_OUT_OF_RANGE')
    local=now.astimezone(IST)
    need(local.hour*60+local.minute>=9*60+20,'BEFORE_TEST_WINDOW')
    cutoff=local.replace(hour=14,minute=55,second=0,microsecond=0)
    need(local+timedelta(seconds=seconds+60)<cutoff,'INSUFFICIENT_TIME_BEFORE_CUTOFF')

def classify(events,new_ids,journal_events,resumed_at,mode):
    relevant=[e for e in events if stamp(e['at'])>=stamp(resumed_at)]
    cash=[e for e in relevant if e.get('status')=='BLOCKED' and
          'NO_CASH_CAPACITY' in e.get('reasons',[]) and
          set(e.get('reasons',[]))<=CASH_REASONS]
    if cash:
        need(len(cash)==1 and len(new_ids)==1,'AMBIGUOUS_CASH_OUTCOME')
        matches=[e for e in journal_events if e.get('id') in new_ids]
        need(len(matches)==1 and matches[0].get('role')=='ENTRY','ENTRY_LINK_NOT_PROVEN')
        need(stamp(matches[0]['event_at'])>stamp(resumed_at),'PRE_RESUME_EVENT')
        return dict(status='ZERO_CASH_REJECTION_OBSERVED',event=matches[0],reasons=cash[0]['reasons'])
    if relevant or mode=='PAUSED':
        return dict(status='INCONCLUSIVE_OTHER_BLOCKER_OR_OPERATOR_PAUSE',
                    reasons=[r for e in relevant for r in e.get('reasons',[])])
    return None

def execute_session(io,seconds):
    """Injected IO allows tests to prove command order and cleanup behavior."""
    result=dict(status='INCONCLUSIVE_NO_ELIGIBLE_ENTRY',resume_attempted=False,
                pause_verified=False,production_ready=False,fresh_signal_admission_verified=False)
    timer_scheduled=False
    try:
        io.preflight()
        io.schedule_deadline(seconds);timer_scheduled=True
        io.reconcile_once()
        version,session=io.resume_parameters()
        result['resume_attempted']=True  # Set BEFORE sending; acknowledgement can be lost.
        resumed_at=io.resume_once(version,session)
        end=io.clock()+seconds
        while io.clock()<end:
            observed=io.observe(resumed_at)
            if observed:
                result.update(observed);break
            io.wait()
    except BaseException as exc:
        result['status']='STOPPED_FOR_REVIEW'
        result['error']=str(exc) if type(exc) is Blocked else type(exc).__name__
    finally:
        if timer_scheduled:
            try:
                io.pause_once()
                io.verify_paused()
                result['pause_verified']=True
            except BaseException as exc:
                result['status']='PAUSE_UNCONFIRMED_REQUIRES_REVIEW'
                result['pause_error']=str(exc) if type(exc) is Blocked else type(exc).__name__
                # Do NOT cancel the independent deadline after an uncertain pause.
            if result['pause_verified']:
                try: io.cancel_deadline()
                except Exception: result['deadline_cleanup_warning']='TIMER_CLEANUP_UNCONFIRMED'
    return result

def control_environment(root,home,environ):
    result={'HOME':str(home),'PATH':'/usr/bin:/bin','PYTHONPATH':str(root/'backend')+':'+str(root)}
    for key in ('XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
        if environ.get(key):result[key]=environ[key]
    return result

class IO:
    def __init__(self,root,output):
        self.root=root;self.output=output
        self.python=str(root/'.venv/bin/python')
        self.cli=root/'scripts/hilega_production_control.py'
        self.env=control_environment(root,Path.home(),os.environ)
        self.env_sha=self.sha(root/'.env')
        self.ids={k:str(uuid.uuid4()) for k in ('resume','reconcile','pause','deadline')}
        self.timer='hilega-preparation-test-'+uuid.uuid4().hex
        self.clock=time.monotonic;self.wait=lambda:time.sleep(2)
        path=root/'hilega-supervision-migration-tools-v1/migrate-persistent-supervision.py'
        spec=importlib.util.spec_from_file_location('session_existing_guards',path)
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        self.runner=self.m.load_runner(Path.home()/'hilega-persistent-supervision-stage-v1')
    def sha(self,p):
        need(p.is_file() and not p.is_symlink(),'REGULAR_FILE_REQUIRED')
        return hashlib.sha256(p.read_bytes()).hexdigest()
    def command(self,args,timeout=20):
        p=subprocess.run(args,cwd=self.root,env=self.env,capture_output=True,text=True,timeout=timeout)
        need(p.returncode==0,'COMMAND_REJECTED_OR_ACK_UNAVAILABLE')
        return p.stdout
    def control(self,action,*extra,request=None):
        args=[self.python,str(self.cli),'--env-file',str(self.root/'.env'),action,*extra]
        if request:args+=['--request-id',request]
        return json.loads(self.command(args))
    def read_state(self):
        path=self.root/'data/research/hilega-production-workspace/sim.sqlite'
        need(path.is_file() and not path.is_symlink(),'DATABASE_INVALID')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db,db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
            cursor=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0])
            events=[dict(json.loads(row[1]),audit_sequence=row[0]) for row in db.execute('SELECT seq,data FROM preparation_events WHERE seq>?',(getattr(self,'audit_seq',0),))]
            ids={r[0] for r in db.execute('SELECT id FROM preparation_consumed')}
        return control,cursor,events,ids
    def preflight(self):
        releases=(
            ('hilega-admission-wait-release-v1','781000c45ab1a6a19f92c2d36a4ea4c5ebda0233cf61f8901fb76add8767783e',False),
            ('hilega-atomic-binding-release-v1','ea563125ccf1bb8dbb02c26679cb7b254702a185679c8260a78529e6d2bde436',True),
            ('hilega-auto-limit-release-v1','13f052acf497ca10ac4b1f3a289f6ede36559b37e273a5143c5a15ebf6773665',True),
        )
        for package,pin,skip_source in releases:
            path=self.root/package/'manifest.json'
            need(self.sha(path)==pin,'RELEASE_MANIFEST_CHANGED')
            manifest=json.loads(path.read_text())
            for name in manifest['runtime_files']:
                if skip_source and name=='backend/market_lab/hilega_preparation_runtime_v1/source.py': continue
                need(self.sha(self.root/name)==manifest['files'][name],'DEPLOYED_RUNTIME_CHANGED')
        need(self.sha(self.root/'.env')==self.env_sha,'ENV_CHANGED')
        self.m.paused_check(self.root);self.m.clean_database(self.root);self.m.api_health()
        s=self.control('status');validate_status(s)
        need(s['control']['session_date']==datetime.now(IST).date().isoformat(),'SESSION_MISMATCH')
        rows=self.m.inventory(self.root)
        need(len(rows)==3,'SERVICE_INVENTORY_INVALID')
        for row in rows:
            unit='hilega-'+row['role']+'.service'
            need(self.command(['systemctl','--user','is-active',unit]).strip()=='active','SERVICE_NOT_ACTIVE')
            need(int(self.command(['systemctl','--user','show',unit,'-p','MainPID','--value']))==row['pid'],'SERVICE_PID_MISMATCH')
        config_path=Path.home()/'hilega-persistent-supervision-stage-v1/config-private.json'
        config=json.loads(self.runner.regular(config_path))
        need(config['env_sha256']==self.env_sha,'SUPERVISOR_ENV_REVALIDATION_REQUIRED')
        self.control_state,self.cursor,events,self.baseline_ids=self.read_state()
        self.audit_seq=max((e['audit_sequence'] for e in events),default=0)
    def capture(self):
        # GET-only collector; no controller writes or order transport.
        from dotenv import dotenv_values
        from market_lab.hilega_production_account_adapter_v1 import read_pin
        from market_lab.hilega_preparation_runtime_v1.collect import capture
        from market_lab.hilega_preparation_runtime_v1.evidence import validate
        settings=dotenv_values(self.root/'.env')
        def setting(k):
            shell,file=os.getenv(k),settings.get(k)
            need(not(shell and file and shell!=file),'SHELL_ENV_FILE_TOKEN_CONFLICT')
            return shell or file
        primary=setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN')
        secondary=setting('UPSTOX_ACCESS_TOKEN')
        token=(primary or secondary or '').strip();need(bool(token),'READ_TOKEN_MISSING')
        pin=read_pin(Path.home()/'hilega-private/upstox-account-pin.json')
        value=capture(token,pin)
        now=datetime.now(timezone.utc).isoformat()
        plans=validate(value,pin,as_of=now)
        need(all(value.get(k,{}).get('status')=='NORMAL_OPEN' for k in ('market_before','market_after')),'MARKET_NOT_OPEN')
        need(all(zero(value.get(k,{}).get('cash_available_to_trade')) for k in ('cash_before_market','cash_after_market')),'CAPTURE_NOT_ZERO_CASH')
        need(len(plans)==2 and all('NO_CASH_CAPACITY' in p.get('reasons',[]) and set(p['reasons'])<=CASH_REASONS for p in plans),'CAPTURE_HAS_OTHER_BLOCKERS')
        self.runner.atomic(self.output/'preflight-evidence-private.json',value)
        return dict(assessed_at=now,cash_available_to_trade='0',
                    candidates=[{k:p.get(k) for k in ('direction','instrument','quantity','reasons')} for p in plans])
    def schedule_deadline(self,seconds):
        # Private copied helper remains available if the terminal process dies.
        helper=self.output/'deadline-helper.py';shutil.copyfile(Path(__file__).resolve(),helper);os.chmod(helper,0o600)
        self.runner.atomic(self.output/'deadline-config.json',dict(root=str(self.root),request_id=self.ids['deadline']))
        self.deadline_time=self.clock()+seconds
        self.command(['systemd-run','--user','--quiet','--unit='+self.timer,
            '--on-active='+str(seconds)+'s','--timer-property=AccuracySec=1s',
            '--property=Restart=on-failure','--property=RestartSec=10s',
            '--property=StartLimitIntervalSec=300','--property=StartLimitBurst=5',
            '--working-directory='+str(self.root),'/usr/bin/env','-i',
            'HOME='+str(Path.home()),'PATH=/usr/bin:/bin','PYTHONPATH='+self.env['PYTHONPATH'],
            self.python,str(helper),'deadline-pause','--output',str(self.output)])
        # Verify it actually exists before any Resume attempt.
        need(self.command(['systemctl','--user','is-active',self.timer+'.timer']).strip()=='active','PAUSE_TIMER_NOT_ACTIVE')
        self.runner.atomic(self.output/'deadline-scheduled.json',dict(unit=self.timer,request_id=self.ids['deadline']))
    def reconcile_once(self):self.control('reconcile',request=self.ids['reconcile'])
    def resume_parameters(self):
        self.m.clean_database(self.root)
        s=self.control('status');validate_status(s)
        need(self.sha(self.root/'.env')==self.env_sha,'ENV_CHANGED')
        need(self.clock()+30<self.deadline_time,'INSUFFICIENT_PAUSE_LEASE_REMAINING')
        need(self.command(['systemctl','--user','is-active',self.timer+'.timer']).strip()=='active','PAUSE_TIMER_NO_LONGER_ACTIVE')
        return s['control']['version'],s['control']['session_date']
    def resume_once(self,version,session):
        self.runner.atomic(self.output/'resume-attempt.json',dict(request_id=self.ids['resume'],version=version,session=session,at=datetime.now(timezone.utc).isoformat()))
        response=self.control('resume','--expected-version',str(version),'--session-date',session,'--next-signal',request=self.ids['resume'])
        c=response['status']['control']
        need(c['mode']=='ARMED' and c['version']==version+1,'RESUME_ACK_STATE_INVALID')
        self.runner.atomic(self.output/'resume-ack.json',dict(request_id=self.ids['resume'],control=c))
        return c['resumed_at']
    def observe(self,resumed_at):
        need(self.sha(self.root/'.env')==self.env_sha,'ENV_CHANGED')
        self.m.clean_database(self.root)
        s=self.control('status');validate_status(s,modes=('PAUSED','ARMED'))
        c,cursor,events,ids=self.read_state()
        need(cursor['path']==self.cursor['path'],'JOURNAL_PATH_CHANGED')
        new_ids=ids-self.baseline_ids
        journal_events=[]
        if events or new_ids:
            from market_lab.hilega_production_simulator_bridge_v1 import verified_records,accepted
            records=list(verified_records(Path(cursor['path'])))
            seq=self.cursor['sequence']
            need(seq<=len(records) and (not seq or records[seq-1]['record_hash']==self.cursor['hash']),'JOURNAL_PREFIX_CHANGED')
            for row in records[seq:]:journal_events.extend(accepted(row))
        return classify(events,new_ids,journal_events,resumed_at,c['mode'])
    def pause_once(self):self.control('pause-today',request=self.ids['pause'])
    def verify_paused(self):
        self.runner.paused(self.root);self.m.clean_database(self.root)
        s=self.control('status')
        need(s['control']['mode']=='PAUSED','PAUSE_NOT_CONFIRMED')
        validate_status(s)
        need(s['production_execution_enabled'] is False,'EXECUTION_FLAG_CHANGED')
        need(s['broker_execution_port']['transport_gate']=='CLOSED_IN_CODE','TRANSPORT_CHANGED')
    def cancel_deadline(self):
        # A fired deadline may no longer have an active timer; cancellation is best effort.
        subprocess.run(['systemctl','--user','stop',self.timer+'.timer'],capture_output=True,timeout=10)

def deadline_pause(output):
    cfg=json.loads((output/'deadline-config.json').read_text())
    root=Path(cfg['root'])
    env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin','PYTHONPATH':str(root/'backend')+':'+str(root)}
    args=[str(root/'.venv/bin/python'),str(root/'scripts/hilega_production_control.py'),'--env-file',str(root/'.env')]
    # This safety-only command can be replayed with its same idempotency key.
    p=subprocess.run([*args,'pause-today','--request-id',cfg['request_id']],cwd=root,env=env,capture_output=True,text=True,timeout=20)
    need(p.returncode==0,'DEADLINE_PAUSE_ACK_UNAVAILABLE')
    p=subprocess.run([*args,'status'],cwd=root,env=env,capture_output=True,text=True,timeout=20)
    need(p.returncode==0 and json.loads(p.stdout).get('control',{}).get('mode')=='PAUSED','DEADLINE_PAUSE_UNCONFIRMED')
    (output/'deadline-result.json').write_text(json.dumps(dict(status='DEADLINE_PAUSE_CONFIRMED',at=datetime.now(timezone.utc).isoformat())))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('check','run','deadline-pause'))
    p.add_argument('--seconds',type=int,default=300)
    p.add_argument('--confirm-upstox-zero-cash',action='store_true')
    p.add_argument('--arm-preparation-only',action='store_true')
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    os.umask(0o077)
    if args.action=='deadline-pause':
        need(args.output is not None,'OUTPUT_REQUIRED');deadline_pause(args.output);return
    if args.action=='run':
        need(args.confirm_upstox_zero_cash,'UPSTOX_DISPLAY_CONFIRMATION_REQUIRED')
        need(args.arm_preparation_only,'EXPLICIT_PREPARATION_ARMING_REQUIRED')
    root=Path.home()/'RB-ITOS-AI'
    need(Path.cwd().resolve()==root.resolve(),'RUN_FROM_REPOSITORY')
    validate_window(datetime.now(IST),args.seconds)
    sys.path.insert(0,str(root/'backend'));sys.path.insert(0,str(root))
    folder=Path(tempfile.mkdtemp(prefix='hilega-preparation-session-test-',dir=root/'data/research'))
    io=IO(root,folder)
    lock=(root/'data/runtime/hilega-preparation-session-test.lock').open('a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        io.preflight();capture_summary=io.capture()
        report=dict(status='ZERO_CASH_TEST_PREFLIGHT_PASS',action=args.action,
                    funds_display_confirmed=args.confirm_upstox_zero_cash,
                    controller_armed_by_check=False,capture=capture_summary,
                    production_ready=False,broker_submission_attempted=False,report=str(folder/'report.json'))
        io.runner.atomic(folder/'report.json',report)
        if args.action=='run':
            def interrupted(signum,frame):raise InterruptedError()
            signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
            result=execute_session(io,args.seconds)
            report.update(result)
            report.pop('controller_armed_by_check',None)
            report['preparation_resume_attempted']=result['resume_attempted']
        io.runner.atomic(folder/'report.json',report)
        print(json.dumps(report,indent=2))
        if args.action=='run' and (report['status']!='ZERO_CASH_REJECTION_OBSERVED' or not report['pause_verified']):
            raise SystemExit(2)
    finally:lock.close()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(dict(status='SESSION_TEST_BLOCKED',reason=str(exc) if type(exc) is Blocked else type(exc).__name__,production_ready=False)))
        raise SystemExit(1)
