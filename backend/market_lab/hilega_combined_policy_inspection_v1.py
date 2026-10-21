"""Display recorded combined-policy evidence; never recompute trade permissions."""
from .hilega_combined_policy_v1 import POLICY_ID,VERSION

def inspection(a):
    rows=[]
    def add(label,result,value,requirement,explanation=''):
        rows.append(dict(label=label,status='INFO' if result is None else 'PASS' if result else 'FAIL',
                         value=str(value),requirement=requirement,explanation=explanation))
    add('Strategy policy',None,POLICY_ID,VERSION,'Completed five-minute decisions; no persistence or time expiry.')
    ind=a.get('completed_5m_indicators') or {}
    add('Completed RSI / EMA3 / WMA21',None,ind,'RSI-based indicators; price EMA10 is separate')
    for c in a.get('checks') or []:
        side=c.get('direction');prefix=str(side)+' · '
        add(prefix+'candidate',None,c.get('signal_available_at'),'Retain until entry, fully qualified opposite, manual reset or cutoff')
        add(prefix+'WMA strength',c.get('wma_threshold_pass'),c.get('directional_wma_strength'),'>=0.75 at signal; follow-up price route may bypass fresh strength')
        add(prefix+'positive gap',c.get('gap_positive_pass'),c.get('current_gap'),'>0; bullish signal additionally >=2')
        add(prefix+'gap expansion',c.get('gap_expanding_pass'),c.get('gap_delta'),'>0 vs previous completed5m; follow-up price route is alternative')
        ev=c.get('ema10_entry') or {}
        for key,label,requirement in (
            ('price_position_pass','price EMA10 position','Bull close>EMA10; bear close<EMA10'),
            ('slope_pass','price EMA10 slope','Bull rising; bear falling'),
            ('candle_colour_pass','signal candle colour','Bull green; bear red'),
            ('rsi_continuation_pass','signal RSI continuation','Bull rising >40; bear falling <60'),
            ('fresh_signal_alignment_pass','signal alignment','Bull RSI>EMA3>WMA; bear inverse'),
            ('bullish_signal_gap_pass','bullish signal gap','>=2'),
            ('full_wma_pass','bullish full WMA magnitude','Entry WMA minus WMA BEFORE qualified signal >=2'),
            ('followup_colour_pass','follow-up colour','Bull green; bear red'),
            ('followup_rsi_direction_pass','follow-up RSI direction','Bull rising; bear falling'),
            ('followup_price_pass','follow-up price route','Close beyond signal close OR midpoint'),
            ('fresh_strength_gap_pass','follow-up fresh-check route','Strength>=0.75 AND positive expanding gap'),
            ('ema10_touch_pass','failed follow-up EMA10 touch','Low<=EMA10<=high retains original signal reference')):
            if key in ev:
                observed=ev.get('full_wma_magnitude') if key=='full_wma_pass' else ev.get('bullish_signal_gap') if key=='bullish_signal_gap_pass' else ev.get('ema10_slope') if key=='slope_pass' else ev[key]
                add(prefix+label,ev[key],observed,requirement)
        add(prefix+'decision',c.get('status')=='ENTRY',c.get('status'),'Confirmed entry only after follow-up',', '.join(c.get('reasons') or []))
    for e in a.get('policy_events') or []:
        add('Policy event · '+e.get('event',''),None,e.get('entry_confirmation_route') or e.get('followup_due') or e.get('time'),
            'Informational unless an actual confirmed entry/exit is accepted',', '.join(e.get('reasons') or []))
    v=a.get('exit_validation')
    if v:
        add('Existing dual exit',v.get('dual_exit_pass'),v,'Both RSI and EMA3 opposite WMA21; cutoff remains separate')
    return rows
