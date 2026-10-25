import pytest
from quality import assess

def frame(side):
    return dict(rsi9=65 if side=='BULLISH' else 35,
                ema3_rsi=60 if side=='BULLISH' else 40,
                wma21_rsi=55 if side=='BULLISH' else 45,
                close=110 if side=='BULLISH' else 90, ema10=100,
                previous_ema10=97 if side=='BULLISH' else 103)

@pytest.mark.parametrize('side', ['BULLISH','BEARISH'])
@pytest.mark.parametrize('variant', ['RSI_EMA50','WMA50','EMA10_SLOPE3','EMA10_DISTANCE30'])
def test_symmetric_pass(side,variant):
    assert assess(side,frame(side),variant)['passed']

@pytest.mark.parametrize('side', ['BULLISH','BEARISH'])
def test_strict_alignment_and_distance(side):
    f=frame(side);f['wma21_rsi']=50
    assert not assess(side,f,'WMA50')['passed']
    f['ema3_rsi']=50
    assert not assess(side,f,'RSI_EMA50')['passed']
    f['close']=131 if side=='BULLISH' else 69
    assert not assess(side,f,'EMA10_DISTANCE30')['passed']

def test_missing_rejected():
    assert not assess('BULLISH',{},'WMA50')['passed']
