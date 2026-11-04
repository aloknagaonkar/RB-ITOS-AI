"""Qualify the real SDK stream, then optionally start today's managed quote-only observer."""
import argparse,hashlib,json,os,subprocess,sys,tempfile,time
from datetime import datetime,time as walltime
from pathlib import Path
from zoneinfo import ZoneInfo
sys.dont_write_bytecode=True
UNIT='hilega-quote-observer.service'
def need(ok,code):
    if not ok:raise ValueError(code)
def raw(p):
    need(p.is_absolute() and p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'REGULAR_INPUT_REQUIRED');return p.read_bytes()
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--active-plan',type=Path,required=True);ap.add_argument('--active-plan-sha256',required=True);ap.add_argument('--start-observer',action='store_true');a=ap.parse_args()
    root=a.repo.absolute();here=Path(__file__).absolute().parent;path=a.active_plan.absolute()
    for n,h in json.loads(raw(here/'MANIFEST.json')).items():need(sha(raw(here/n))==h,'STREAM_BATCH_PACKAGE_CHANGED')
    for n,h in json.loads(raw(here/'BASELINE-PINS.json')).items():need(sha(raw(root/n))==h,'STREAM_BATCH_BASELINE_CHANGED')
    need(sha(raw(path))==a.active_plan_sha256,'ACTIVE_PLAN_CHANGED');plan=json.loads(raw(path));need(plan['repo']==str(root) and plan['production_execution_enabled'] is False,'CLOSED_PLAN_REQUIRED')
    out=Path(tempfile.mkdtemp(prefix='hilega-quote-stream-review-',dir=root));out.chmod(0o700)
    def save(name,value):
        fd=os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')
    def run(label,command,timeout=110):
        try:r=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
        except subprocess.TimeoutExpired:
            save(label+'.json',dict(status='TIMEOUT'));raise ValueError('CHECK_TIMEOUT_'+label) from None
        # Worker/SDK output can contain provider details: discard it. Structured status is separate.
        safe=label!='WEBSOCKET'
        save(label+'.json',dict(exit_code=r.returncode,stdout=r.stdout if safe else 'SUPPRESSED_SDK_OUTPUT',stderr=r.stderr if safe else 'SUPPRESSED_SDK_OUTPUT'))
        need(r.returncode==0,'CHECK_FAILED_'+label);return r
    def status(label):
        r=run(label,[sys.executable,'-B',str(root/'hilega-registration-rollout-v1/manage.py'),'--repo',str(root),'--action','status','--plan',str(path),'--approve-plan-sha256',a.active_plan_sha256]);need(json.loads(r.stdout)['phase']=='CLOSED_GROUP2_CANDIDATE_RUNNING','CLOSED_RUNTIME_REQUIRED')
    status('BEFORE')
    # The original observer uses this single-publisher lock too; do not start it alongside this observer.
    r=subprocess.run(['systemctl','--user','show',UNIT,'--property=MainPID','--value'],capture_output=True,text=True,timeout=10)
    need(not r.stdout.strip().isdigit() or int(r.stdout.strip())==0,'QUOTE_OBSERVER_ALREADY_RUNNING')
    r=run('TESTS',[sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',str(here/'test_stream.py')],timeout=60);print(r.stdout,flush=True)
    qualify=out/'qualification';qualify.mkdir(mode=0o700)
    base=[sys.executable,'-B',str(here/'stream_worker.py'),'--repo',str(root),'--plan',str(path),'--plan-sha256',a.active_plan_sha256]
    run('WEBSOCKET',base+['--output',str(qualify),'--seconds','35'],timeout=65)
    receipt=json.loads(raw(qualify/'RESULT.json'));need(receipt['status']=='WEBSOCKET_QUOTE_COVERAGE_PASS' and receipt['qualified'] is True,'SDK_STREAM_NOT_QUALIFIED')
    status('AFTER-QUALIFICATION')
    report=dict(status='COMBINED_WEBSOCKET_AND_BASKET_QUALIFICATION_PASS',qualification=receipt,observer_started=False,cache_publishing_verified=False,strategy_admission_or_full_production_coverage_verified=False,warmup_prevention_deployed=False,application_sources_modified=False,existing_units_modified=False,controller_resumed=False,orders_sent=False,production_execution_enabled=False,production_ready=False,audit_folder=str(out))
    if a.start_observer:
        now=datetime.now(ZoneInfo('Asia/Kolkata'));deadline=datetime.combine(now.date(),walltime(15,30),tzinfo=now.tzinfo);seconds=int((deadline-now).total_seconds())
        need(now.weekday()<5 and 60<seconds<=8*3600,'CURRENT_MARKET_SESSION_REQUIRED')
        # Copy exact package bytes into the audit: edits to the downloaded folder cannot change this run.
        runtime=out/'observer-code';runtime.mkdir(mode=0o700)
        for f in here.iterdir():
            if f.is_file():
                target=runtime/f.name;target.write_bytes(raw(f));target.chmod(0o400)
        streamout=out/'observer';streamout.mkdir(mode=0o700)
        cache=root/'data/live-observation/hilega-strike-observation-v1/active-live-quotes.json'
        if cache.exists():save('PREVIOUS-QUOTE-CACHE.json',json.loads(raw(cache)))
        command=['systemd-run','--user','--unit='+UNIT,'--collect','--property=Type=exec','--property=RuntimeMaxSec='+str(seconds+15),'--property=Restart=no','--property=KillMode=control-group','--property=NoNewPrivileges=yes','--property=StandardOutput=null','--property=StandardError=null','--working-directory='+str(root),'--',sys.executable,'-B',str(runtime/'stream_worker.py'),'--repo',str(root),'--plan',str(path),'--plan-sha256',a.active_plan_sha256,'--output',str(streamout),'--seconds',str(seconds),'--publish']
        run('START-OBSERVER',command,timeout=20)
        until=time.monotonic()+40;ready=False
        while time.monotonic()<until:
            state=streamout/'STREAM-STATUS.json'
            if state.exists():
                value=json.loads(raw(state))
                if value.get('status')=='STOPPED':break
                if value.get('stream_connected') and value.get('basket_full_coverage') and value.get('continuous_five_second_coverage_verified'):
                    ready=True;break
            time.sleep(1)
        if not ready:
            subprocess.run(['systemctl','--user','stop',UNIT],capture_output=True,timeout=20)
            save('RESULT.json',dict(report,status='OBSERVER_START_NOT_VERIFIED_STOPPED',observer_started=True,observer_stop_requested=True));raise ValueError('OBSERVER_START_NOT_VERIFIED_INSPECT_AUDIT')
        status('AFTER-OBSERVER')
        report.update(status='CURRENT_SESSION_QUOTE_ONLY_OBSERVER_RUNNING',observer_started=True,cache_publishing_verified=True,observer_unit=UNIT,session_deadline_ist=deadline.isoformat(),transient_current_session_only=True,automatic_next_session_start_installed=False,quote_status_file=str(streamout/'STREAM-STATUS.json'))
    save('RESULT.json',report);print(json.dumps(report,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        import re,traceback
        code=str(exc).split(':',1)[0];print(json.dumps(dict(status='QUOTE_STREAM_BATCH_BLOCKED',reason=code if re.fullmatch('[A-Z][A-Z0-9_]*',code) else 'QUOTE_STREAM_BATCH_REQUIRES_REVIEW',error_type=type(exc).__name__,failure_location=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(exc.__traceback__)[-3:]],automatic_retry=False)));raise SystemExit(2)
