from market_lab.midpoint_strategy.live_shadow_ui import _presentation_for_replay, _timeline_projection, _with_nifty_points


def event(kind, minute, price, *, direction='BEARISH', family='E'):
    return {'event_id':kind+minute, 'event_type':kind,
            'event_timestamp':f'2026-09-29T{minute}:00+05:30',
            'session_date':'2026-09-29', 'direction':direction,
            'family':family, 'underlying_price':price,
            'directional_points':None}


def test_each_signal_has_close_based_nifty_points_and_reset():
    originals=[event('E_ENTRY','09:26',22652.4),
               event('PLUS20_PROOF','09:28',22634.4),
               event('RUNNER_CLASSIFICATION','09:38',22581.55),
               event('DEGRADED_STARTED','09:40',22594.85),
               event('STRUCTURAL_TERMINAL','11:13',22687.35),
               event('MIDPOINT_CLOSE_BREAK','11:14',22690)]
    projected=_with_nifty_points(originals)
    assert [round(x['nifty_points_from_entry'],2) if x['nifty_points_from_entry'] is not None else None for x in projected]==[0,18,70.85,57.55,-34.95,None]
    assert all('nifty_points_from_entry' not in x for x in originals)
    timeline=_timeline_projection(projected)
    assert timeline[3]['nifty_points_from_entry']==57.55


def test_replay_minutes_show_points_only_after_entry_and_through_exit():
    audit=_timeline_projection(_with_nifty_points([
        event('E_ENTRY','09:26',22652.4),event('STRUCTURAL_TERMINAL','09:28',22687.35)]))
    minutes=[{'timestamp':f'2026-09-29T09:{minute}:00+05:30',
              'underlying_close':close,'futures_close':None,'futures_vwap':None}
             for minute,close in [('25',22653),('26',22652.4),('27',22640),('28',22687.35),('29',22690)]]
    rendered=_presentation_for_replay(minutes,audit)
    assert [x.get('nifty_points_from_entry') for x in rendered]==[None,0,12.4,-34.95,None]
    assert rendered[3]['presentation']['status']=='EXIT'
