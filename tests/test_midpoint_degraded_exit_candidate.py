from datetime import datetime, timedelta

from market_lab.midpoint_strategy.degraded_exit_candidate import CANONICAL, PREMIUM, project

DAY='2026-09-29'

def event(kind,minute,price,result=None):
    return {'event_id':kind+minute,'event_type':kind,'event_timestamp':DAY+f'T{minute}:00+05:30',
            'session_date':DAY,'family':'E','direction':'BEARISH','underlying_price':price,'result':result}

def fixture():
    entry=event('E_ENTRY','09:26',22652.4)
    minutes=[]
    t=datetime.fromisoformat(DAY+'T09:27:00+05:30')
    until=datetime.fromisoformat(DAY+'T11:14:00+05:30')
    while t<=until:
        minutes.append({'timestamp':t.isoformat(),'open':100.,'high':125.,'low':99.,'close':110.})
        t+=timedelta(minutes=1)
    tape={'entry_event_id':entry['event_id'],'entry_boundary':DAY+'T09:27:00+05:30',
          'session_date':DAY,'direction':'BEARISH',
          'legs':[{'relation_to_atm':i,'side':'PE','instrument_key':f'PE{i}','minutes':minutes}
                  for i in (-2,-1,0,1,2)]}
    rows=[entry,event('PLUS20_PROOF','09:28',22634.4),
          event('RUNNER_CLASSIFICATION','09:38',22581.55,'RUNNER_STRENGTHENING'),
          event('DEGRADED_STARTED','09:40',22594.85),
          event('STRUCTURAL_TERMINAL','11:13',22687.35)]
    return rows,tape

def test_canonical_candidate_and_independent_strict_premium_gate():
    rows,tape=fixture()
    result=project(rows,tape)
    assert result['canonical_gate']['status']=='QUALIFIED'
    assert result['DEGRADED_EXIT_TIMESTAMP']==DAY+'T09:41:00+05:30'
    assert result['DEGRADED_PREMIUMS']==[100.]*5
    assert result['legs'][0]['tracks'][CANONICAL]['exit_timestamp']==DAY+'T09:41:00+05:30'
    assert result['legs'][0]['premium_plus20_by_entry_t10'] is True
    assert result['legs'][0]['tracks'][PREMIUM]['qualified'] is False
    assert result['legs'][0]['tracks'][PREMIUM]['exit_timestamp']==DAY+'T11:14:00+05:30'
    assert round(result['legs'][0]['COMP_CAP20_TERMINAL']['delta_vs_terminal_points'],2)==92.5
    assert result['observation_only'] is True and result['quantity'] is None

def test_exact_minute_missing_and_bid_ask_are_not_invented():
    rows,tape=fixture()
    tape['legs'][0]['minutes']=[r for r in tape['legs'][0]['minutes'] if 'T09:41:' not in r['timestamp']]
    result=project(rows,tape)
    assert result['legs'][0]['tracks'][CANONICAL]['status']=='EXACT_MINUTE_UNAVAILABLE'
    assert result['DEGRADED_PREMIUMS'][0] is None
    assert result['legs'][1]['tracks'][CANONICAL]['bid_ask_net_points'] is None

def test_later_trade_cannot_supply_first_trade_exit():
    rows,tape=fixture()
    rows=[rows[0],rows[1],rows[2],rows[3],event('B_ENTRY','10:00',22500),rows[4]]
    result=project(rows,tape)
    assert result['terminal_timestamp'] is None
    assert result['legs'][0]['COMP_CAP20_TERMINAL']['delta_vs_terminal_points'] is None

def test_exact_quote_net_and_premium_comparison():
    rows,tape=fixture()
    quotes=[]
    for leg in tape['legs']:
        quotes.extend([{'instrument_key':leg['instrument_key'],'timestamp':tape['entry_boundary'],'ask':101},
                       {'instrument_key':leg['instrument_key'],'timestamp':DAY+'T09:41:00+05:30','bid':99}])
    result=project(rows,tape,quotes=quotes,entry_slippage_points=.5,
                   exit_slippage_points=.5,round_trip_charges_points=1)
    leg=result['legs'][0]
    assert leg['tracks'][CANONICAL]['bid_ask_net_points']==-4
    assert leg['COMP_CAP20_TERMINAL']['candidate_delta_vs_terminal_premium_points']==0
