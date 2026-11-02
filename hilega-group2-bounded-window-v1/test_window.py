import pytest
from window import intent,admit,decision,save
import json

def state():return intent(version=2,session='2026-11-02',sequence=5,now=100,duration=30)
def baseline():return dict(mode='PAUSED',version=2,session='2026-11-02',empty=True,route='PREPARATION_ONLY',gate_closed=True)
def test_deadline_bounded():
    with pytest.raises(ValueError):intent(version=2,session='s',sequence=5,now=100,duration=301)
def test_guard_before_arm():
    with pytest.raises(ValueError):admit(state(),baseline(),now=101,guard_ready=False)
def test_stale_version():
    b=baseline();b['version']=3
    with pytest.raises(ValueError):admit(state(),b,now=101,guard_ready=True)
def test_wrong_route():
    b=baseline();b['route']='SIMULATOR'
    with pytest.raises(ValueError):admit(state(),b,now=101,guard_ready=True)
def test_gate_must_be_closed():
    b=baseline();b['gate_closed']=False
    with pytest.raises(ValueError):admit(state(),b,now=101,guard_ready=True)
def test_expiry_blocks_arm():
    with pytest.raises(ValueError):admit(state(),baseline(),now=130,guard_ready=True)
def test_no_reuse():
    s=admit(state(),baseline(),now=101,guard_ready=True)
    with pytest.raises(ValueError):admit(s,baseline(),now=102,guard_ready=True)
def test_deadline_pauses():assert decision(state(),now=130,mode='ARMED',preparations=0)=='PAUSE_ON_DEADLINE'
def test_preparation_pauses():assert decision(state(),now=105,mode='ARMED',preparations=1)=='PAUSE_ON_PREPARATION'
def test_clock_rewind_pauses():assert decision(state(),now=99,mode='ARMED',preparations=0)=='PAUSE_ON_CLOCK_REWIND'
def test_wait_does_not_replay():assert decision(state(),now=105,mode='ARMED',preparations=0)=='WAIT'
def test_state_is_durable(tmp_path):
    p=tmp_path/'WINDOW.json';save(p,state());assert json.loads(p.read_text())==state()
