from datetime import datetime,timedelta

def replay_frames(module,source):
    """Use only known next-bar opens; extrema use held completed bars, no invented 1m OHLC."""
    audits=source['audit'];frames=[a['frame'] for a in audits]
    bars=[{k:f[k] for k in ('start','open','high','low','close')} for f in frames]
    # Engine only looks up each signal boundary's next open or exact final close.
    # These are sparse fill references, explicitly not raw or synthetic minute candles.
    references=[dict(timestamp=f['start'],open=f['open']) for f in frames[1:]]
    final=datetime.fromisoformat(audits[-1]['decision_time'])-timedelta(minutes=1)
    references.append(dict(timestamp=final.isoformat(),close=frames[-1]['close']))
    class SuppliedIndicators:
        def __init__(self):self.i=0
        def update(self,bar):
            f=frames[self.i];self.i+=1
            return {k:v for k,v in f.items() if k not in ('start','open','high','low','close')}
    def extrema(trade,unused):
        first=datetime.fromisoformat(trade['entry_time']);last=datetime.fromisoformat(trade['exit_time']);sign=1 if trade['side']=='CE' else -1
        held=[f for f in frames if first<=datetime.fromisoformat(f['start'])<last]
        peak=max([0.]+[sign*(f['high' if sign==1 else 'low']-trade['entry_price']) for f in held])
        adverse=min([0.]+[sign*(f['low' if sign==1 else 'high']-trade['entry_price']) for f in held])
        return dict(peak_positive_points=peak,giveback_points=peak-trade['points'],worst_unrealized_points=adverse)
    old=module.excursion;module.excursion=extrema
    try:r=module.replay(source['session_date'],bars,references,[],indicator_factory=SuppliedIndicators)
    finally:module.excursion=old
    for k in ('session_kind','session_open','session_close','market_trend'):r[k]=source[k]
    r['validation_basis']='SUPPLIED_COMPLETED_3M_FRAMES; NO_INDEPENDENT_INDICATOR_RESEED'
    return r


def assert_parity(actual,source):
    assert len(actual['trades'])==len(source['trades']),'TRADE_COUNT_MISMATCH'
    for a,b in zip(actual['trades'],source['trades']):
        for k in ('side','route_name','entry_time','exit_time','exit_reasons'):assert a[k]==b[k],k
        for k in ('entry_price','exit_price','points','peak_positive_points','giveback_points','worst_unrealized_points'):assert abs(a[k]-b[k])<1e-7,k
    assert [a['events'] for a in actual['audit']]==[a['events'] for a in source['audit']],'EVENT_PARITY_FAILED'
    for a,b in zip(actual['audit'],source['audit']):assert (a['owner_before'],a['owner_after'])==(b['owner_before'],b['owner_after'])

