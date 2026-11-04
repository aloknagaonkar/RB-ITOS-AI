from datetime import timedelta
import hashlib,hmac,json,os,signal,subprocess,sys,time,uuid
from pathlib import Path
import pytest
from test_bootstrap import approve,run,folder
from test_provisioning import setup
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from test_handoff import approval,execute,unchanged,ROOT
from handoff import propose,sha,canonical,atomic
from bootstrap_worker import configured_poll


def wait(fn,child,log,seconds=18):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        if fn():return
        assert child.poll() is None, log.read_text()[-6000:]
        time.sleep(.1)
    raise AssertionError('Worker deadline exceeded; inspect '+str(log)+'\n'+log.read_text()[-6000:])


def outcomes(log):
    values=[]
    for line in log.read_text().splitlines():
        try:values.append(json.loads(line))
        except ValueError:pass
    return values


def health(e):
    with e['store'].db() as db:return json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])


def initialise(setup,tmp_path):
    e,parent,pin,secret=setup;run(setup,approve(setup));context=folder(parent)/'context.json';release=Path(os.environ['HILEGA_PACKAGE_B_BUNDLE'])
    w=tmp_path/'worker-process';w.mkdir(mode=0o700)
    rootfile=parent/'synthetic-worker-root';rootfile.write_bytes(ROOT);rootfile.chmod(0o600)
    cfg=json.loads(context.read_text());mailbox=parent/'WORKER-HANDOFF.json'
    configuration=dict(model='HILEGA_DISABLED_WORKER_CONFIG_V1',release_sha256=sha((release/'RELEASE-MANIFEST.json').read_bytes()),
        application_db=str(e['store'].path.resolve()),adapter_db=str(e['adapter_store'].path.resolve()),journal=str(e['path'].resolve()),
        pin_file=cfg['pin_file'],pin_sha256=cfg['pin_sha256'],trust_key_file=str(rootfile),trust_key_sha256=sha(ROOT),issuer_id='synthetic',mailbox=str(mailbox),production_execution_enabled=False)
    configfile=parent/'worker-config.json';atomic(configfile,(json.dumps(configuration)+'\n').encode())
    (w/'empty.env').write_text('')
    (w/'WORKER-FIXTURE.json').write_text(json.dumps(dict(workspace=str(w.resolve()),synthetic_only=True,now=e['clock'][0].isoformat(),application_db=str(e['store'].path.resolve()),journal=str(e['path'].resolve()))))
    clean=dict(PATH=os.defpath,LANG='C.UTF-8',HOME=str(w),PYTHONDONTWRITEBYTECODE='1',
        HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='1',HILEGA_PRODUCTION_EXECUTION_ROUTE='PREPARATION_ONLY',
        HILEGA_PRODUCTION_SIM_DB=str(e['store'].path.resolve()),HILEGA_PREPARATION_ADAPTER_DB=str(e['adapter_store'].path.resolve()),
        HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED='1',HILEGA_PREPARATION_CAPTURE_ON_SIGNAL='0',
        HILEGA_DISABLED_HANDOFF_CONFIG=str(configfile),HILEGA_DISABLED_HANDOFF_CONFIG_SHA256=sha(configfile.read_bytes()))
    return e,w,context,release,configuration,clean


def launch(values,label):
    e,w,context,release,cfg,clean=values;log=w/(label+'.log');stream=log.open('w')
    helper=Path(os.environ['HILEGA_WORKER_FIXTURE_HELPER'])
    p=subprocess.Popen([sys.executable,'-B',str(helper),'--bundle',str(release),'--workspace',str(w)],cwd=w,env=clean,stdout=stream,stderr=subprocess.STDOUT)
    stream.close()
    wait(lambda:health(e).get('pid')==p.pid and health(e).get('phase')=='RUNNING',p,log)
    return p,log


def admit(setup,values,p,log):
    e,w,context,release,cfg,clean=values;e['source'].run_id=health(e)['run_id']
    proposal=propose(e['source'],e['adapter_store'],setup[2],e['path'],context,sha(context.read_bytes()),release,cfg['release_sha256'],uuid.uuid4().hex,lambda:e['clock'][0])
    result=execute(setup,proposal,approval(setup,proposal))
    slot=dict(model='HILEGA_DISABLED_WORKER_MAILBOX_V1',receipt_file=result['receipt'],receipt_sha256=result['receipt_sha256'],
        source_lease=e['source'].run_id,issued_at=e['clock'][0].isoformat(),expires_at=(e['clock'][0]+timedelta(seconds=50)).isoformat(),issuer_id='synthetic',production_execution_enabled=False)
    slot.update({k:cfg[k] for k in ['release_sha256','application_db','adapter_db','journal']})
    slot['signature']=hmac.new(ROOT,canonical(slot),hashlib.sha256).hexdigest();atomic(Path(cfg['mailbox']),(json.dumps(slot)+'\n').encode())
    wait(lambda:any(v.get('status')=='DISABLED_BOOTSTRAP_HANDOFF_WORKER_VERIFIED' for v in outcomes(log)),p,log)
    unchanged(setup,proposal);return proposal,slot


def stop(p):
    if p is not None and p.poll() is None:p.kill();p.wait(timeout=10)


def test_exact_cli_handoff_then_restart_requires_explicit_rebind(setup,tmp_path):
    values=initialise(setup,tmp_path);p=None
    try:
        p,log=launch(values,'first-worker');first,_=admit(setup,values,p,log)
        firstlease=health(values[0])['run_id'];stop(p)
        p,log=launch(values,'restarted-worker')
        assert health(values[0])['run_id']!=firstlease
        wait(lambda:any(v.get('status')=='DISABLED_HANDOFF_REVIEW_REQUIRED' for v in outcomes(log)),p,log)
        assert values[0]['store'].control()['mode']=='PAUSED'
        second,_=admit(setup,values,p,log)
        assert first['protected']==second['protected'] and first['cursor']==second['cursor']
    finally:stop(p)


def test_exact_cli_tampered_mailbox_stays_paused(setup,tmp_path):
    values=initialise(setup,tmp_path);p=None
    try:
        p,log=launch(values,'tamper-worker');proposal,slot=admit(setup,values,p,log)
        before=len(outcomes(log));slot['receipt_sha256']='0'*64
        atomic(Path(values[4]['mailbox']),(json.dumps(slot)+'\n').encode())
        wait(lambda:any(v.get('status')=='DISABLED_HANDOFF_REVIEW_REQUIRED' for v in outcomes(log)[before:]),p,log)
        unchanged(setup,proposal)
    finally:stop(p)


def test_no_configuration_selects_unchanged_default(monkeypatch):
    monkeypatch.delenv('HILEGA_DISABLED_HANDOFF_CONFIG',raising=False);monkeypatch.delenv('HILEGA_DISABLED_HANDOFF_CONFIG_SHA256',raising=False)
    assert configured_poll(None,None) is None
