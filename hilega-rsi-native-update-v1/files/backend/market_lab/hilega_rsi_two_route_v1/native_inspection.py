"""Recorded RSI gates for the existing Hilega decision/audit table."""
def inspection(a):
    out=[]
    def add(label,result,value,requirement,explanation=''):
        out.append(dict(label=label,status='INFO' if result is None else 'PASS' if result else 'FAIL',value=str(value),requirement=requirement,explanation=explanation))
    add('Active strategy',None,'RSI Two Route — Confirmed Midpoint','Completed 3m; original Hilega trade/exit pipeline')
    for c in a.get('checks') or []:
        side=c['direction'];bull=side=='BULLISH';f=c['frame'];prefix=side+' · '
        for k,passed in c['checks'].items():
            if k.startswith('rsi'):
                actual=f[k.replace('_threshold','')];required='>55' if bull else '<45'
            elif k=='wma21_rsi9_threshold':actual=f['wma21_rsi9'];required='>50 CE / <50 PE; Normal Route'
            elif k=='signal_candle_colour':actual=f"open {f['open']}; close {f['close']}";required='Green: close>open' if bull else 'Red: close<open'
            else:actual=f"close {f['close']}; EMA {f['ema30_high' if bull else 'ema30_low']}";required='close > EMA30 High' if bull else 'close < EMA30 Low'
            add(prefix+k,passed,actual,required)
        for route,eligible in c['eligible_routes'].items():
            add(prefix+route,eligible,str(c['rsi_pass_count'])+'/5 RSI pass','At least2 RSI + WMA50' if route=='Normal Route' else 'All5 RSI; WMA threshold bypassed',', '.join(c['route_blockers'][route]))
        add(prefix+'decision',c['status']=='ENTRY',c['status'],'Single owner; opposite qualified entry exits then reverses','; '.join(c['reasons']))
    v=a.get('exit_validation')
    if v:
        for k in ('signal_midpoint_price_breach','rsi5_opposite50','rsi9_opposite50','signal_midpoint_rsi_confirmed_exit','wma50_exit','opposite_ema_boundary_exit','all_three_exit','opposite_entry_exit'):
            add('Exit · '+k,v.get(k),v.get(k),'Same completed candle; strict inequalities')
        add('Fixed original signal midpoint',None,v.get('signal_midpoint'),'(Original signal High+Low)/2; never trailed')
        add('Exit decision',None,v.get('action'),'Session close15:30 OR qualified opposite OR confirmed midpoint OR all-three')
    return out
