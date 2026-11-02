import json
from pathlib import Path
import pytest
from window import save
from recovery import recover_all,assert_admission,registry_windows

def setup(tmp_path):
    w=tmp_path/'window';w.mkdir();save(w/'DISPOSABLE-WINDOW.json',dict(model='HILEGA_DISPOSABLE_WINDOW_V1',workspace=str(w.resolve())))
    save(w/'WINDOW.json',dict(phase='ARM_REQUESTED'))
    r=tmp_path/'REGISTRY.json';save(r,dict(model='HILEGA_DISPOSABLE_RECOVERY_REGISTRY_V1',windows=['window']));return r,w

def test_pending_registry_blocks_admission(tmp_path):
    r,w=setup(tmp_path)
    with pytest.raises(ValueError,match='PENDING_WINDOW_BLOCKS_ADMISSION'):assert_admission(r)

def test_recovery_closes_only_after_pause(tmp_path):
    r,w=setup(tmp_path);calls=[]
    assert recover_all(r,lambda p:calls.append(p))==['window'];assert calls==[w];assert_admission(r)

def test_failed_pause_keeps_pending_state(tmp_path):
    r,w=setup(tmp_path)
    def fail(p):raise RuntimeError('interruption')
    with pytest.raises(RuntimeError):recover_all(r,fail)
    assert json.loads((w/'WINDOW.json').read_text())['phase']=='ARM_REQUESTED'

def test_closed_recovery_is_idempotent(tmp_path):
    r,w=setup(tmp_path);recover_all(r,lambda p:None)
    assert recover_all(r,lambda p:pytest.fail('Closed window must not be paused again'))==[]

def test_registry_path_escape_rejected(tmp_path):
    r,w=setup(tmp_path);save(r,dict(model='HILEGA_DISPOSABLE_RECOVERY_REGISTRY_V1',windows=['../elsewhere']))
    with pytest.raises(ValueError,match='REGISTRY_WINDOW_ESCAPE'):registry_windows(r)

def test_symlink_window_rejected(tmp_path):
    r,w=setup(tmp_path);(tmp_path/'link').symlink_to(w,target_is_directory=True)
    save(r,dict(model='HILEGA_DISPOSABLE_RECOVERY_REGISTRY_V1',windows=['link']))
    with pytest.raises(ValueError,match='REGULAR_REGISTERED_WINDOW_REQUIRED'):registry_windows(r)
