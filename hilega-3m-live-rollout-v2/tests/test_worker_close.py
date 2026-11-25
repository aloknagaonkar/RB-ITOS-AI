from datetime import datetime,timedelta,date
from types import SimpleNamespace as Obj
import pytest
from market_lab.domain import IST
from market_lab.hilega_three_minute_v1.worker_close import process_after_close

@pytest.mark.parametrize('clock,expected',[
    ('09:15',False),('14:55',False),('15:29',False),('15:30',True),
    ('15:31',True),('15:35',True),('16:10',True),('23:59',True)])
def test_finalization_outside_market_session(clock,expected):
    now=datetime.fromisoformat('2026-11-19T'+clock+':00+05:30')
    seen=[];coordinator=Obj(decision_interval_minutes=3,_cutoff_done_date=None,process=lambda at:seen.append(at))
    def tick(at,tasks):
        assert len(tasks)==1 and tasks[0][0]=='hilega'
        tasks[0][1](at)
    assert process_after_close(now,'ALIGNMENT','ALIGNMENT',coordinator,tick) is expected
    assert len(seen)==int(expected)

def test_retries_missing_evidence_but_stops_after_confirmed_close():
    now=datetime(2026,11,19,15,30,tzinfo=IST);calls=[]
    coordinator=Obj(decision_interval_minutes=3,_cutoff_done_date=None)
    def process(at):
        calls.append(at)
        if len(calls)==2:coordinator._cutoff_done_date=at.date()
    coordinator.process=process
    tick=lambda at,tasks:tasks[0][1](at)
    assert process_after_close(now,'A','A',coordinator,tick)
    assert process_after_close(now+timedelta(seconds=5),'A','A',coordinator,tick)
    assert not process_after_close(now+timedelta(seconds=10),'A','A',coordinator,tick)
    assert len(calls)==2

@pytest.mark.parametrize('selected,interval,day',[
    ('OTHER',3,date(2026,11,19)),('A',5,date(2026,11,19)),
    ('A',3,date(2026,11,21)),('A',3,date(2026,11,22))])
def test_other_policies_and_weekends_unchanged(selected,interval,day):
    now=datetime(day.year,day.month,day.day,15,31,tzinfo=IST)
    coordinator=Obj(decision_interval_minutes=interval,_cutoff_done_date=None,
        process=lambda at:pytest.fail('Unexpected strategy call'))
    assert not process_after_close(now,selected,'A',coordinator,lambda *args:pytest.fail('Unexpected task'))

def test_last_session_marker_does_not_block_next_session():
    now=datetime(2026,11,20,15,30,tzinfo=IST);seen=[]
    coordinator=Obj(decision_interval_minutes=3,_cutoff_done_date=date(2026,11,19),process=lambda at:seen.append(at))
    assert process_after_close(now,'A','A',coordinator,lambda at,tasks:tasks[0][1](at))
    assert seen==[now]
