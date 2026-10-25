import pytest
from rules import midpoint_exit

@pytest.mark.parametrize('side,close,expected',[
    ('BEARISH',101,True),('BEARISH',100,False),('BEARISH',99,False),
    ('BULLISH',99,True),('BULLISH',100,False),('BULLISH',101,False)])
def test_midpoint_strict_close(side,close,expected):
    assert midpoint_exit(side,close,100)==expected
