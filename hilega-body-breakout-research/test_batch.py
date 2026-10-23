from batch import stats,digest,signature

def test_drawdown_and_totals():
    trades=[dict(exit_time=str(i),points=p) for i,p in enumerate([10,-20,5])]
    assert stats(trades)==[3,15,-20,-5,2,1,20]

def test_digest_stable_key_order():
    assert digest({'a':1,'b':2})==digest({'b':2,'a':1})

def test_signature_ignores_reporting_fields():
    t=dict(direction='BULLISH',entry_time='x',exit_time='y',entry_price=1,exit_price=2,points=1,exit_reason='TEST')
    assert signature([t])==signature([dict(t,route='EXTRA')])

def test_daily_reports_include_unexecuted_waits(tmp_path):
    from daily_reports import write_daily
    row=dict(session_date='2026-10-22',policies={
        'DEPLOYED_5M':dict(trades=[],audit=[]),
        'BODY50_1M_WAIT':dict(trades=[],audit=[dict(time='2026-10-22T10:17:00+05:30',action='WAIT',close=100,signal=dict(direction='BULLISH',high=101,low=95,midpoint=98))])})
    write_daily(tmp_path,row)
    text=(tmp_path/'daily-reports/2026-10-22.md').read_text()
    assert '10:17' in text and 'WAIT' in text and 'BULLISH' in text
