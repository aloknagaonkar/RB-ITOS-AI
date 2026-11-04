"""Exact outer CLI, with explicitly synthetic registration/clock/providers/transport."""
from datetime import datetime,timedelta
import hashlib,hmac,json,os,re,runpy,sys,time,traceback,uuid
from pathlib import Path
from unittest.mock import patch
import pytest
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from test_private_context import private,LiveProviders,pc,port,base
from hilega_application_preparation_fixtures import PIN
from test_hilega_application_preparation_v1 import append,BULL
from market_lab.hilega_provisioning_workflow_v1 import provision_disabled_owner,_scan
from local_admission import LocalApproval,expected as local_expected,MODEL as LOCAL_MODEL
from test_worker_files import setup_registry,write,disabled
from test_factory import binding_for
from authority_files import issue_candidate_grant
from handoff import canonical,sha

LOCAL_ROOT=b'OUTER-CLI-SYNTHETIC-HANDOFF-ROOT-0000'


def child_cli(private,result,*,admit,rotate_root=False):
    e,folder,cfg=private;bundle=Path(os.environ['HILEGA_PACKAGE_B_BUNDLE']);clock=lambda:e['clock'][0]
    import market_lab.hilega_production_foundation.core as core
    import market_lab.hilega_production_bridge_health_v1 as bh
    import worker_binding as wb
    from market_lab.hilega_preparation_runtime_v1.source import Source
    old_claim=bh.claim;original_registration=wb.registration;original_gate=port.require_live_clearance
    registration_path=[None];registration_digest=[None];registry_path=[None];factory_open=[not admit]
    statefile=folder/'CLI-ADMISSION.json'
    if not admit:
        saved=json.loads(statefile.read_text());registration_path[0]=Path(saved['registration']);registration_digest[0]=saved['registration_sha256']
        registry_path[0]=Path(saved['registry'])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            value=clock();return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    def claim(service):
        run_id=old_claim(service)
        e['s']=service;e['store']=service.store;e['source']=Source(service,run_id=run_id,provider=lambda:(_ for _ in ()).throw(AssertionError('No implicit capture')))
        return run_id
    def gate():
        if not factory_open[0]:return original_gate()
        return None
    def admit_seed():
        pin=json.loads((folder/'source-pin.json').read_text());release_sha=sha((bundle/'RELEASE-MANIFEST.json').read_bytes())
        e['key']=e['adapter_store'].requests()[0]['request_id']
        fingerprint=_scan(e['source'],e['adapter_store'],pin,e['path'],e['key'],clock)
        bind=local_expected(e['source'],e['adapter_store'],pin,e['path'],e['key'],bundle,release_sha,private_parent=folder,state_fingerprint=fingerprint)
        g=dict(model=LOCAL_MODEL,operation='ENROLL_DISABLED_OWNER',issuer_id='cli-local-root',grant_id='cli-fresh-seed',binding=bind,issued_at=clock().isoformat(),
            expires_at=(clock()+timedelta(seconds=50)).isoformat(),order_transport_permission=False,production_execution_enabled=False)
        g['signature']=hmac.new(LOCAL_ROOT,canonical(g),hashlib.sha256).hexdigest()
        approval=LocalApproval(g,bind,lambda:{'cli-local-root':LOCAL_ROOT},operation=g['operation'],clock=clock)
        out=provision_disabled_owner(e['source'],e['adapter_store'],pin,e['path'],e['key'],folder,lambda:'synthetic-cli-token',local_approval=approval,clock=clock)
        context=Path(out['private_folder'])/'context.json';newfolder=context.parent;updated=json.loads(context.read_text())
        e['authority']=json.loads((newfolder/'authority.json').read_text());bind=binding_for((e,newfolder,updated))
        rp,rs,_=setup_registry(newfolder,bind)
        grant=issue_candidate_grant(bind,registry_path=rp,registry_sha256=rs,issuer_id='synthetic-root',grant_id='outer-cli-fixture',issued_at=(clock()-timedelta(seconds=1)).isoformat(),expires_at=(clock()+timedelta(hours=1)).isoformat())
        gp=newfolder/'grant.json';gs=write(gp,grant)
        registration=disabled();registration.update(enabled=True,expected_binding=bind,private_config_file=str(context),private_config_sha256=bind['private_context_sha256'],
            trust_registry_file=str(rp),trust_registry_sha256=rs,grant_file=str(gp),grant_sha256=gs)
        registration_path[0]=newfolder/'worker-registration.json';registration_digest[0]=write(registration_path[0],registration);registry_path[0]=rp
        statefile.write_text(json.dumps(dict(registration=str(registration_path[0]),registration_sha256=registration_digest[0],registry=str(rp))))
        factory_open[0]=True
    default_path=bundle/'runtime/FACTORY-REGISTRATION.json';default_sha=sha(default_path.read_bytes())
    def registration(path,expected):
        # Only the fixture's registration-file location is substituted; the
        # original parser/hash/private-permission verification still executes.
        assert Path(path)==default_path and expected==default_sha
        if registration_path[0] is None:return original_registration(path,expected)
        return original_registration(registration_path[0],registration_digest[0])
    loops=[0];rotated=[False];warmup=[0]
    def between_polls(seconds):
        loops[0]+=1;assert loops[0]<45,'Outer loop did not complete expected scenario'
        if admit and not factory_open[0]:
            if warmup[0]==0:
                # Native reconcile/resume with a healthy observed source. The
                # next confirmed synthetic event arrives after that resume.
                control=e['store'].control()
                for action in ['reconcile','resume']:
                    control=e['store'].control();e['s'].command(action,request_id=uuid.uuid4().hex,expected_version=control['version'],session_date=control['session_date'],actor='SYNTHETIC_CLI_WINDOW')
                e['clock'][0]=e['clock'][0].replace(minute=30,second=3,microsecond=0)
                evidence=base.market(e);write(folder/'source-evidence.json',evidence)
                append(e['path'],[BULL],at=e['clock'][0].replace(second=0).isoformat())
                warmup[0]=1;return
            assert len(e['adapter_store'].requests())==1,'Fresh disabled seed missing; inspect CLI log/preparation_events'
            admit_seed();return
        state=base.read_state(e);phase=state['phase']
        if rotate_root and phase=='ENTRY_REVIEW' and not rotated[0]:
            key=Path(json.loads(registry_path[0].read_text())['key_file']);key.write_bytes(b'R'*32);rotated[0]=True;return
        if phase=='ENTRY_REVIEW':base.fill(e,'BUY')
        elif phase=='WAIT_EXIT':
            # Generate fixture journal input only; the next outer CLI iteration
            # performs the actual factory tick (no direct tick in this callback).
            with patch.object(base,'poll',return_value={'phase':'SELL_PENDING'}):base.emit_exit(e)
            bh.heartbeat(e['s'],e['source'].run_id,source_at=e['clock'][0].isoformat())
        elif phase=='EXIT_REVIEW':base.fill(e,'SELL')
        elif phase=='WAIT_NEXT':
            if state['completed_cycles']==2:raise KeyboardInterrupt()
            base.resume_and_signal(e)
    original_poll=wb.RegisteredAuthorityWorker.poll
    def diagnostic(exc):
        text=str(exc);label=text if re.fullmatch(r'[A-Z][A-Z0-9_]{0,119}',text) else 'SYNTHETIC_CLI_CALLBACK_FAILED'
        (folder/'CLI-LAST-ERROR.json').write_text(json.dumps(dict(error_type=type(exc).__name__,reason=label)))
    def observed_poll(worker,source,journal):
        try:return original_poll(worker,source,journal)
        except Exception as exc:diagnostic(exc);raise
    def observed_between(seconds):
        try:return between_polls(seconds)
        except Exception as exc:diagnostic(exc);raise
    empty=folder/'empty.env';empty.write_text('')
    settings=dict(HILEGA_PRODUCTION_EXECUTION_ROUTE='PREPARATION_ONLY',HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',
        HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='1',HILEGA_PRODUCTION_SIM_DB=str(e['store'].path.resolve()),
        HILEGA_PREPARATION_ADAPTER_DB=str(e['adapter_store'].path.resolve()),HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED='1',HILEGA_PREPARATION_CAPTURE_ON_SIGNAL='0',
        HILEGA_PREPARATION_PIN_FILE=str(folder/'source-pin.json'),HILEGA_PREPARATION_EVIDENCE_FILE=str(folder/'source-evidence.json'))
    log=folder/('CLI-ADMITTED.log' if admit else 'CLI-RESTART.log')
    wb._DEFAULT=None
    with patch.dict(os.environ,settings),patch.object(core,'datetime',Clock),patch.object(wb,'datetime',Clock),\
         patch.object(bh,'claim',side_effect=claim),patch.object(wb,'registration',side_effect=registration),\
         patch.object(port,'require_live_clearance',side_effect=gate),patch.object(port.HttpTransport,'check',return_value=None),\
         patch.object(port.HttpTransport,'send',side_effect=lambda aid,wire:e['send'](aid,wire)),\
         patch.object(LiveProviders,'account',side_effect=lambda:base.account(e)),\
         patch.object(LiveProviders,'entry_market',side_effect=lambda:base.market(e)),\
         patch.object(pc,'capture_owned',side_effect=lambda *args:base.market(e)),patch('time.sleep',side_effect=observed_between),\
         patch.object(wb.RegisteredAuthorityWorker,'poll',observed_poll),\
         patch.object(sys,'argv',[str(bundle/'closed_worker_launcher.py'),'--watch','--env-file',str(empty),'--source',str(e['path'])]):
        os.environ.pop('HILEGA_DISABLED_HANDOFF_CONFIG',None);os.environ.pop('HILEGA_DISABLED_HANDOFF_CONFIG_SHA256',None)
        with log.open('w') as stream,patch.object(sys,'stdout',stream),patch.object(sys,'stderr',stream):
            try:runpy.run_path(str(bundle/'closed_worker_launcher.py'),run_name='__main__')
            except SystemExit as exc:exit_code=exc.code
            else:raise AssertionError('Outer watch loop unexpectedly returned')
    with e['store'].db() as db:
        health=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
    record=dict(exit_code=exit_code,completed_cycles=base.read_state(e)['completed_cycles'],intercepted_sends=e['send'].call_count,
        now=clock().isoformat(),mode=e['store'].control()['mode'],bridge_phase=health['phase'],lease=health['run_id'],loops=loops[0],root_rotated=rotated[0])
    result.write_text(json.dumps(record))


def fork_cli(private,result,**options):
    pid=os.fork()
    if pid==0:
        try:child_cli(private,result,**options);os._exit(0)
        except BaseException:
            result.with_suffix('.error.txt').write_text(traceback.format_exc());os._exit(1)
    deadline=time.monotonic()+70
    while True:
        done,status=os.waitpid(pid,os.WNOHANG)
        if done:break
        if time.monotonic()>=deadline:os.kill(pid,9);os.waitpid(pid,0);pytest.fail('CLI fixture timed out')
        time.sleep(.1)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0,result.with_suffix('.error.txt').read_text() if result.with_suffix('.error.txt').exists() else 'child terminated'
    return json.loads(result.read_text())


def fresh_workspace(private):
    e,folder,cfg=private
    from market_lab.hilega_production_foundation.core import Store,SimBroker,Service
    from market_lab.hilega_preparation_runtime_v1.source import Source
    from market_lab.hilega_production_simulator_bridge_v1 import POLICY,VERSION
    e['clock'][0]=e['clock'][0].replace(minute=29,second=58,microsecond=0)
    app=Store(folder/'cli-application.sqlite');service=Service(app,SimBroker(app),lambda:e['clock'][0],worker_start=False)
    e['s']=service;e['store']=app;e['source']=Source(service,run_id='fixture-before-start')
    e['adapter_store']=port.Store(folder/'cli-adapter.sqlite',PIN['scope'],'LIVE_CLOSED')
    e['path']=folder/'cli-strategy.jsonl'
    row=dict(sequence=1,previous_hash=None,stage='COMBINED_PRICE_OBSERVATION',status='PROCESSED',payload=dict(policy_id=POLICY,strategy_version=VERSION,decision_timestamp=e['clock'][0].isoformat()))
    row['record_hash']=sha(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode())
    e['path'].write_text(json.dumps(row)+'\n');e['fills']={};e['statuses']={}
    write(folder/'source-pin.json',dict(PIN,model='HILEGA_UPSTOX_ACCOUNT_PIN_V1',broker='UPSTOX',approved_at=e['clock'][0].isoformat()))
    return e,folder,cfg


def test_exact_cli_two_cycles_then_new_process_stale_authority_blocks(private):
    private=fresh_workspace(private);e,folder,cfg=private
    first=fork_cli(private,folder/'FIRST-RESULT.json',admit=True)
    assert first['exit_code']==130 and first['completed_cycles']==2 and first['intercepted_sends']==4
    assert first['mode']=='PAUSED' and first['bridge_phase']=='STOPPED'
    before=len(e['adapter_store'].requests());e['clock'][0]=datetime.fromisoformat(first['now'])
    second=fork_cli(private,folder/'RESTART-RESULT.json',admit=False)
    assert second['exit_code']==2 and second['intercepted_sends']==0 and second['mode']=='PAUSED'
    assert second['lease']!=first['lease'] and len(e['adapter_store'].requests())==before
    with pytest.raises(port.GateClosed):port.require_live_clearance()


def test_exact_cli_cached_root_change_pauses_without_second_send(private):
    private=fresh_workspace(private);e,folder,cfg=private
    value=fork_cli(private,folder/'ROTATION-RESULT.json',admit=True,rotate_root=True)
    assert value['root_rotated'] and value['exit_code']==2 and value['mode']=='PAUSED'
    assert value['intercepted_sends']==1 and value['completed_cycles']==0
    with pytest.raises(port.GateClosed):port.require_live_clearance()
