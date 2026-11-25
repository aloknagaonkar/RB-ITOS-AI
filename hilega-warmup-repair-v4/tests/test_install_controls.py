from datetime import datetime
from io import BytesIO
from types import SimpleNamespace as Obj
import json
import pytest
import repair


def clock(monkeypatch,hour,minute):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,11,23,hour,minute,tzinfo=repair.IST)
    monkeypatch.setattr(repair,'datetime',Clock)


def setup_flat(monkeypatch,tmp_path,trades=()):
    clock(monkeypatch,16,0)
    monkeypatch.setattr(repair.safety,'api_status',lambda base:dict(
        current=dict(session_date='2026-11-23',trade_owner='NONE'),
        worker_component_health=dict(timestamp='2026-11-23T15:30:30+05:30')))
    monkeypatch.setattr(repair,'cutoff_record',lambda *a,**kw:{'verified':True})
    monkeypatch.setattr(repair,'urlopen',lambda *a,**kw:BytesIO(json.dumps(dict(trades=list(trades))).encode()))
    monkeypatch.setattr(repair.safety,'sandbox_clear',lambda repo:{})
    monkeypatch.setattr(repair.safety,'no_execution_workers',lambda repo:None)
    return Obj(api_url='http://127.0.0.1:8123'),dict(repo=tmp_path)


def test_install_is_refused_intraday_before_any_api_call(monkeypatch,tmp_path):
    clock(monkeypatch,11,30)
    monkeypatch.setattr(repair.safety,'api_status',lambda base:pytest.fail('Must stop before API calls'))
    with pytest.raises(ValueError,match='AFTER_1535'):
        repair.require_flat_after_close(Obj(api_url='unused'),dict(repo=tmp_path),'old')


def test_install_requires_recorded_cutoff(monkeypatch,tmp_path):
    args,context=setup_flat(monkeypatch,tmp_path)
    monkeypatch.setattr(repair,'cutoff_record',lambda *a,**kw:None)
    with pytest.raises(ValueError,match='CUTOFF_NOT_CONFIRMED'):
        repair.require_flat_after_close(args,context,'old')


@pytest.mark.parametrize('status',['ACTIVE','PENDING_EXACT_EXIT','NO_EXACT_ENTRY','UNRESOLVED_HISTORICAL'])
def test_today_unsettled_option_record_blocks_install(monkeypatch,tmp_path,status):
    args,context=setup_flat(monkeypatch,tmp_path,[dict(
        signal_boundary='2026-11-23T10:57:00+05:30',status=status)])
    with pytest.raises(ValueError,match='LIFECYCLE_REQUIRES_RECONCILIATION'):
        repair.require_flat_after_close(args,context,'old')


def test_old_ce_record_is_retained_without_blocking_afterclose_source_repair(monkeypatch,tmp_path):
    args,context=setup_flat(monkeypatch,tmp_path,[dict(
        signal_boundary='2026-11-19T14:10:00+05:30',status='ACTIVE')])
    repair.require_flat_after_close(args,context,'old')


def test_underlying_must_be_flat(monkeypatch,tmp_path):
    args,context=setup_flat(monkeypatch,tmp_path)
    monkeypatch.setattr(repair.safety,'api_status',lambda base:dict(
        current=dict(session_date='2026-11-23',trade_owner='BEARISH')))
    with pytest.raises(ValueError,match='NOT_VERIFIED_FLAT'):
        repair.require_flat_after_close(args,context,'old')


def preflight_setup(monkeypatch,tmp_path,prepare):
    (tmp_path/'.env').write_text('LIVE_SHADOW_STRATEGY=HILEGA_V2_ALIGNMENT_DUAL_EXIT\n'
        'HILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY\n')
    monkeypatch.setattr(repair.safety,'api_status',lambda base:dict(strategy_version='old'))
    def state(unit):
        return dict(ActiveState='active',SubState='running',WorkingDirectory=str(tmp_path),MainPID='974')
    monkeypatch.setattr(repair.safety,'service_state',state)
    monkeypatch.setattr(repair,'service_roles',lambda states:{'test':'active worker retained'})
    monkeypatch.setattr(repair.bindings,'prepare',lambda repo,updates:dict(files={}))
    def unknown_collector(repo,state):raise ValueError('UNREVIEWED_TEST_PROCESS')
    monkeypatch.setattr(repair,'collector_identity',unknown_collector)
    args=Obj(repo=tmp_path,api_url='http://127.0.0.1:8123',prepare=prepare)
    manifest=dict(candidate_sha256={},source_before={},old_version='old')
    return args,manifest


def test_read_only_preparation_accepts_active_worker_and_open_ledger(monkeypatch,tmp_path):
    args,manifest=preflight_setup(monkeypatch,tmp_path,True)
    calls=[]
    def ledger(repo,*,allow_open=False):
        calls.append(allow_open)
        return dict(open_legs=2,pending_orders=1,uncertain_requests=1)
    monkeypatch.setattr(repair.safety,'sandbox_clear',ledger)
    monkeypatch.setattr(repair.safety,'no_execution_workers',lambda repo:pytest.fail('Read-only preparation must not require a worker stop'))
    context=repair.preflight(args,manifest)
    assert calls==[True] and context['ledger']['open_legs']==2
    assert context['protected']['hilega-worker.service']['ActiveState']=='active'


def test_installation_still_blocks_the_same_active_worker(monkeypatch,tmp_path):
    args,manifest=preflight_setup(monkeypatch,tmp_path,False)
    monkeypatch.setattr(repair.safety,'sandbox_clear',lambda repo:pytest.fail('Must reject active service first'))
    with pytest.raises(ValueError,match='EXECUTION_SERVICE_NOT_INACTIVE'):
        repair.preflight(args,manifest)


def test_ledger_default_remains_strict(monkeypatch,tmp_path):
    monkeypatch.setattr(repair.safety.subprocess,'run',lambda *a,**kw:Obj(
        returncode=0,stdout='{"open_legs": 1, "pending_orders": 0, "uncertain_requests": 0}'))
    with pytest.raises(ValueError,match='OPEN_OR_UNCERTAIN'):
        repair.safety.sandbox_clear(tmp_path)
    assert repair.safety.sandbox_clear(tmp_path,allow_open=True)['open_legs']==1


def test_service_identity_never_prints_full_arguments(monkeypatch):
    original=repair.Path
    def path(*parts):
        if parts[0]=='/proc':
            return Obj(read_bytes=lambda:b'python\0-m\0market_lab.worker\0--token\0PRIVATE_SENTINEL\0')
        return original(*parts)
    monkeypatch.setattr(repair,'Path',path)
    result=repair.service_roles({'worker':dict(ActiveState='active',MainPID='974')})
    assert result['worker']['module']=='market_lab.worker'
    assert 'PRIVATE_SENTINEL' not in json.dumps(result)


@pytest.fixture
def collector(monkeypatch,tmp_path):
    pins={}
    for name in ('runtime.py','worker.py','storage.py'):
        relative='backend/market_lab/'+name
        path=tmp_path/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('# reviewed collector fixture\n')
        pins[relative]=repair.digest(path.read_bytes())
    monkeypatch.setattr(repair,'COLLECTOR_SOURCES',pins)
    snapshot=dict(args=['/venv/bin/python','-u','-m','market_lab.runtime','worker'],
                  cwd=str(tmp_path),executable='python3.14')
    monkeypatch.setattr(repair,'process_snapshot',lambda pid:snapshot)
    states={'hilega-worker.service':dict(ActiveState='active',SubState='running',MainPID='974'),
            'hilega-production-source-worker.service':dict(ActiveState='failed',SubState='failed',MainPID='0')}
    return tmp_path,snapshot,states


def test_exact_reviewed_collector_is_retained_without_restart(collector,monkeypatch):
    repo,snapshot,states=collector
    leases=repair.protected_identities(repo,states)
    assert leases['hilega-worker.service']['purpose']=='REVIEWED_DATA_COLLECTOR'
    assert leases['hilega-worker.service']['subcommand']=='worker'
    assert 'hilega-worker.service' not in repair.safety.RESTART_ORDER
    monkeypatch.setattr(repair.safety,'service_state',lambda unit:states[unit])
    repair.recheck_protected(dict(repo=repo,protected=states,collector_leases=leases))


@pytest.mark.parametrize('tail',[
    ['market_lab.runtime','api'],
    ['market_lab.runtime','worker','--enable'],
    ['market_lab.runtime','historical-validate'],
    ['market_lab.worker'],
    ['market_lab.hilega_upstox_sandbox_live_worker'],
])
def test_other_runtime_commands_and_execution_modules_are_not_approved_collectors(collector,tail):
    repo,snapshot,states=collector
    snapshot['args']=['/venv/bin/python','-m']+tail
    with pytest.raises(ValueError,match='EXECUTION_SERVICE_NOT_INACTIVE'):
        repair.protected_identities(repo,states)


@pytest.mark.parametrize('name',['runtime.py','worker.py','storage.py'])
def test_unreviewed_collector_source_is_rejected(collector,name):
    repo,snapshot,states=collector
    (repo/'backend/market_lab'/name).write_text('# changed\n')
    with pytest.raises(ValueError,match='COLLECTOR_SOURCE_NOT_REVIEWED'):
        repair.protected_identities(repo,states)


def test_other_working_directory_is_rejected(collector):
    repo,snapshot,states=collector;snapshot['cwd']='/other/repo'
    with pytest.raises(ValueError,match='ENTRYPOINT_NOT_REVIEWED'):
        repair.protected_identities(repo,states)


def test_active_production_source_service_remains_blocked(collector):
    repo,snapshot,states=collector
    states['hilega-production-source-worker.service']=dict(ActiveState='active',SubState='running',MainPID='975')
    with pytest.raises(ValueError,match='hilega-production-source-worker.service'):
        repair.protected_identities(repo,states)


def test_collector_pid_change_during_rollout_is_rejected(collector,monkeypatch):
    repo,snapshot,states=collector
    leases=repair.protected_identities(repo,states)
    before={u:dict(s) for u,s in states.items()}
    states['hilega-worker.service']['MainPID']='975'
    monkeypatch.setattr(repair.safety,'service_state',lambda unit:states[unit])
    with pytest.raises(ValueError,match='COLLECTOR_PROCESS_CHANGED'):
        repair.recheck_protected(dict(repo=repo,protected=before,collector_leases=leases))
