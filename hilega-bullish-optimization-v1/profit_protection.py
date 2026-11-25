"""Bullish independent-trade profit candidates, observed completed closes only."""
from datetime import datetime
PROFILES={'MIDPOINT_ONLY':None,'TRAIL20_10':(20,10),'TRAIL40_20':(40,20)}
def profit_check(active,at,close,cutoff,profile):
    if profile not in PROFILES:raise ValueError('UNKNOWN_PROFIT_PROFILE')
    rule=PROFILES[profile]
    if rule is None or active is None or active.get('direction')!='BULLISH' or active.get('route')!='INDEPENDENT_BODY60_1M_BREAKOUT':return None
    if at<=datetime.fromisoformat(active['entry_time']) or at>=cutoff:return None
    previous_peak=max(0,float(active.get('profit_peak_points',0)))
    pnl=float(close)-float(active['entry_price']);updated_peak=max(previous_peak,pnl)
    activation,giveback=rule
    # Only a peak known at a previous completed 1m close can trigger this exit.
    passed=previous_peak>=activation and previous_peak-pnl>=giveback
    return dict(time=at.isoformat(),action='BULLISH_PROFIT_CHECK',profile=profile,
        direction='BULLISH',entry_time=active['entry_time'],close=float(close),
        pnl=pnl,previous_peak_points=previous_peak,updated_peak_points=updated_peak,
        activation_points=activation,giveback_points=giveback,
        observed_giveback=previous_peak-pnl,passed=passed)
