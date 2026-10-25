def qualify(side, f):
    sign=1 if side=='BULLISH' else -1
    o,h,l,c,e=(f[k] for k in ('open','high','low','close','ema10'))
    body=abs(c-o); span=h-l
    if span<=0 or body<=0:return None
    beyond=sign*(c-e)/body
    location=(c-l)/span if sign==1 else (h-c)/span
    if not (sign*(c-o)>0 and min(o,c)<e<max(o,c)
            and body/span>.6 and location>=.75
            and sign*(e-f['previous_ema10'])>0):return None
    return dict(direction=side,high=h,low=l,midpoint=(h+l)/2,
                body_ratio=body/span,body_beyond_ema=beyond,close_location=location)

def decision(signal, close):
    if signal['direction']=='BULLISH':
        if close<signal['midpoint']:return 'CANCEL_MIDPOINT'
        if close>signal['high']:return 'ENTRY'
    else:
        if close>signal['midpoint']:return 'CANCEL_MIDPOINT'
        if close<signal['low']:return 'ENTRY'
    return 'WAIT'
