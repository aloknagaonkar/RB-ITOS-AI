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
