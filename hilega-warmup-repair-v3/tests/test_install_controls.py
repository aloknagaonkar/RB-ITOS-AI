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
