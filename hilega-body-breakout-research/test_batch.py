from batch import stats,digest,signature

def test_drawdown_and_totals():
    trades=[dict(exit_time=str(i),points=p) for i,p in enumerate([10,-20,5])]
    assert stats(trades)==[3,15,-20,-5,2,1,20]

def test_digest_stable_key_order():
    assert digest({'a':1,'b':2})==digest({'b':2,'a':1})

def test_signature_ignores_reporting_fields():
    t=dict(direction='BULLISH',entry_time='x',exit_time='y',entry_price=1,exit_price=2,points=1,exit_reason='TEST')
    assert signature([t])==signature([dict(t,route='EXTRA')])
