"""Offline research only. No broker, network or installed strategy imports."""
from datetime import datetime,date,time,timedelta,timezone
import math
IST=timezone(timedelta(hours=5,minutes=30))
INTERVAL=3

def validate(data,require_futures=True):
    day=data['session_date'];date.fromisoformat(day)
    if require_futures:
        contract=data.get('contract',{})
        if contract.get('instrument_type')!='FUT' or not contract.get('instrument_key') or not contract.get('trading_symbol'):raise ValueError('FUTURES_CONTRACT_REQUIRED')
        if date.fromisoformat(contract['expiry'])<date.fromisoformat(day):raise ValueError('CONTRACT_EXPIRED_BEFORE_SESSION')
    rows=data['candles'];opening=datetime.combine(date.fromisoformat(day),time(9,15),IST)
    if len(rows)!=375:raise ValueError('REQUIRES_375_REGULAR_MINUTES')
    for i,row in enumerate(rows):
        at=datetime.fromisoformat(row['timestamp'])
        if at.utcoffset()!=timedelta(hours=5,minutes=30) or at!=opening+timedelta(minutes=i):raise ValueError('NONCONTIGUOUS_OR_WRONG_MINUTE:'+str(i))
        for key in ['open','high','low','close']:
            v=row[key]
            if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or v<=0:raise ValueError('INVALID_PRICE:'+key)
        o,h,l,c=[row[k] for k in ['open','high','low','close']]
        if not l<=min(o,c)<=max(o,c)<=h:raise ValueError('INVALID_OHLC')
        vol=row.get('volume',0)
        if isinstance(vol,bool) or not isinstance(vol,(float,int)) or not math.isfinite(vol) or vol<0:raise ValueError('INVALID_VOLUME')
    if require_futures and sum(r['volume'] for r in rows)<=0:raise ValueError('FUTURES_VOLUME_REQUIRED')
    return rows

def aggregate(rows):
    if len(rows)%3:raise ValueError('INCOMPLETE_THREE_MINUTE_BAR')
    out=[]
    for i in range(0,len(rows),3):
        rr=rows[i:i+3];at=datetime.fromisoformat(rr[0]['timestamp'])
        if any(datetime.fromisoformat(r['timestamp'])!=at+timedelta(minutes=j) for j,r in enumerate(rr)):raise ValueError('MISSING_AGGREGATE_MINUTE')
        out.append(dict(candle_label=at.isoformat(),available_at=(at+timedelta(minutes=3)).isoformat(),
            open=float(rr[0]['open']),high=max(float(r['high']) for r in rr),low=min(float(r['low']) for r in rr),
            close=float(rr[-1]['close']),volume=sum(float(r.get('volume',0)) for r in rr)))
    return out

def indicators(bars):
    """EMA9 seeded with first completed session close; OHLC4 of each 3m bar."""
    result=[];ema=None;pv=vol=0
    for i,b in enumerate(bars,1):
        previous=ema;ema=b['close'] if ema is None else ema+(2/10)*(b['close']-ema)
        source=sum(b[k] for k in ['open','high','low','close'])/4
        pv+=source*b['volume'];vol+=b['volume']
        result.append(dict(b,ema9=ema,previous_ema9=previous,vwap_source_ohlc4=source,
            cumulative_price_volume=pv,cumulative_volume=vol,vwap=pv/vol if vol>0 else None,session_bar_count=i))
    return result

def checks(f):
    ema=f['ema9'];vwap=f['vwap']
    if vwap is None:return dict(bullish_wick=False,bearish_wick=False,bullish_close=False,bearish_close=False,bullish_entry=False,bearish_entry=False)
    bullwick=f['low']<min(ema,vwap);bearwick=f['high']>max(ema,vwap)
    bullclose=f['close']>max(ema,vwap);bearclose=f['close']<min(ema,vwap)
    return dict(bullish_wick=bullwick,bearish_wick=bearwick,bullish_close=bullclose,bearish_close=bearclose,
        bullish_entry=bullwick and bullclose,bearish_entry=bearwick and bearclose)

def exit_condition(direction,frame):
    if direction=='BULLISH':return frame['close']<frame['ema9']
    if direction=='BEARISH':return frame['close']>frame['ema9']
    raise ValueError('INVALID_DIRECTION')

def replay(futures,index=None):
    raw=validate(futures);frames=indicators(aggregate(raw));index_raw=validate(index,False) if index else None
    if index and index['session_date']!=futures['session_date']:raise ValueError('INDEX_DATE_MISMATCH')
    index_bars=aggregate(index_raw) if index_raw else None
    active=pending=None;trades=[];audit=[]
    def close_trade(px,at,reason,reference,index_px):
        nonlocal active
        if active is None:raise ValueError('EXIT_WITHOUT_POSITION')
        sg=1 if active['direction']=='BULLISH' else -1
        t=dict(active,exit_time=at,exit_price=px,exit_reason=reason,exit_signal=reference,points=sg*(px-active['entry_price']))
        t['index_exit_price']=index_px;t['index_points']=sg*(index_px-active['index_entry_price']) if index_px is not None else None
        trades.append(t);active=None
        return t
    for i,f in enumerate(frames):
        ib=index_bars[i] if index_bars else None;exec_events=[]
        if pending:
            if pending['action']=='ENTRY':
                if active:raise ValueError('OVERLAPPING_ENTRY')
                active=dict(direction=pending['direction'],entry_time=f['candle_label'],entry_price=f['open'],
                    entry_signal=pending['signal'],index_entry_price=ib['open'] if ib else None)
                exec_events.append(dict(action='ENTRY_AT_NEXT_3M_OPEN',direction=active['direction'],time=f['candle_label'],price=f['open']))
            else:
                closed=close_trade(f['open'],f['candle_label'],'THREE_MINUTE_CLOSE_BEYOND_EMA9',pending['signal'],ib['open'] if ib else None)
                exec_events.append(dict(action='EXIT_AT_NEXT_3M_OPEN',direction=closed['direction'],time=f['candle_label'],price=f['open'],points=closed['points']))
            pending=None
        flags=checks(f);actions=[];position_at_close=active['direction'] if active else 'FLAT'
        if i==len(frames)-1:
            if active:
                closed=close_trade(f['close'],f['available_at'],'SESSION_END_MARK_CLOSE',f,ib['close'] if ib else None)
                exec_events.append(dict(action='SESSION_END_RESEARCH_CLOSE',direction=closed['direction'],time=f['available_at'],price=f['close'],points=closed['points']))
                actions.append('SESSION_END_CLOSE')
            elif flags['bullish_entry'] or flags['bearish_entry']:actions.append('ENTRY_SIGNAL_NOT_EXECUTED_NO_NEXT_SESSION_BAR')
            else:actions.append('END_SESSION_FLAT')
        elif active:
            if exit_condition(active['direction'],f):
                pending=dict(action='EXIT',signal=f);actions.append('EXIT_SCHEDULED_NEXT_3M_OPEN')
            else:actions.append('HOLD')
            if flags['bullish_entry'] or flags['bearish_entry']:actions.append('ENTRY_NOT_ADDED_WHILE_POSITION_ACTIVE')
        elif flags['bullish_entry'] or flags['bearish_entry']:
            direction='BULLISH' if flags['bullish_entry'] else 'BEARISH'
            pending=dict(action='ENTRY',direction=direction,signal=f);actions.append(direction+'_ENTRY_SCHEDULED_NEXT_3M_OPEN')
        else:actions.append('NO_ENTRY')
        audit.append(dict(time=f['available_at'],frame=f,checks=flags,position_at_close=position_at_close,actions=actions,executions=exec_events))
    if pending or active:raise ValueError('UNCLOSED_SESSION_STATE')
    # Path diagnostics: completed 1m closes plus observed entry/exit execution marks.
    for t in trades:
        sg=1 if t['direction']=='BULLISH' else -1;start=datetime.fromisoformat(t['entry_time']);end=datetime.fromisoformat(t['exit_time'])
        peak=0;peak_at=None;peak_basis=None;worst=0
        for row in raw:
            at=datetime.fromisoformat(row['timestamp']);available=at+timedelta(minutes=1)
            if start<=at and available<=end:
                pnl=sg*(row['close']-t['entry_price']);worst=min(worst,pnl)
                if pnl>peak:peak=pnl;peak_at=available.isoformat();peak_basis='COMPLETED_1M_CLOSE'
        worst=min(worst,t['points'])
        if t['points']>peak:peak=t['points'];peak_at=t['exit_time'];peak_basis='OBSERVED_EXIT_MARK'
        t.update(peak_profit=peak,peak_time=peak_at,peak_basis=peak_basis,giveback=peak-t['points'],close_mae=-worst)
    return dict(trades=trades,audit=audit,frames=frames,index_benchmark_available=index is not None)

def summarize(result):
    tt=result['trades'];equity=peak=dd=0
    for t in tt:equity+=t['points'];peak=max(peak,equity);dd=max(dd,peak-equity)
    winner=[t['points'] for t in tt if t['points']>0];loser=[t['points'] for t in tt if t['points']<0]
    return dict(trades=len(tt),winners=len(winner),losers=len(loser),flat_trades=sum(t['points']==0 for t in tt),
        futures_points=equity,index_points=sum(t['index_points'] for t in tt) if result.get('index_benchmark_available') else None,
        bullish_futures_points=sum(t['points'] for t in tt if t['direction']=='BULLISH'),bearish_futures_points=sum(t['points'] for t in tt if t['direction']=='BEARISH'),
        closed_drawdown=dd,worst_trade=min((t['points'] for t in tt),default=0),without_largest_winner=equity-max(winner,default=0),
        profit_factor=sum(winner)/(-sum(loser)) if loser else None,session_end_closes=sum(t['exit_reason']=='SESSION_END_MARK_CLOSE' for t in tt))
