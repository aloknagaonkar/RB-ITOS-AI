import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
spec=importlib.util.spec_from_file_location('bull60',Path(__file__).with_name('run.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
@pytest.mark.parametrize('w,allowed',[(59.999,True),(60,False),(60.001,False)])
def test_bullish_threshold(w,allowed):
    assert m.normal_exit_allowed('BULLISH',NS(ready=True,rsi9=30,ema3_rsi=35,wma21_rsi=w))==allowed
@pytest.mark.parametrize('r,e',[(65,35),(30,65),(65,65)])
def test_dual_exit_still_required(r,e):
    assert not m.normal_exit_allowed('BULLISH',NS(ready=True,rsi9=r,ema3_rsi=e,wma21_rsi=59))
def test_bearish_dual_unchanged():
    snap=NS(ready=True,rsi9=50,ema3_rsi=45,wma21_rsi=39)
    assert m.normal_exit_allowed('BEARISH',snap)==m.base.dual_exit('BEARISH',snap)
def test_private_policy_keeps_installed_module_unchanged():
    before=m.base.dual_exit
    study=m.Study(True)
    assert m.base.dual_exit is before
    assert study.policy is not m.base
