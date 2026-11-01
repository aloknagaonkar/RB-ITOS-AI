from market_lab.hilega_milega_trade_dashboard_v1 import project_shadow_dashboard


def leg(role, *, closed=False):
    row = dict(relation_to_atm=role, strike=23400+role*50,
               instrument_key=f'CE{role}', entry_open=100.0,
               entry_timestamp='2026-09-23T10:20:00+05:30',
               latest_close=108.0, current_points=8.0,
               mfe_points=15.0, mae_points=-4.0)
    if closed:
        row.update(exit_open=110.0+role, exit_timestamp='2026-09-23T10:40:00+05:30',
                   realized_points=10.0+role, realized_return_pct=10.0+role)
    return row


def event(stage, status, signal, legs=None, **fields):
    return dict(stage=stage, status=status, payload={
        'signal_bar': signal, 'status': status,
        'legs': legs if legs is not None else [], **fields})


def test_five_independent_realized_leg_totals_and_no_rupee_pnl():
    signal='2026-09-23T10:15:00+05:30'
    rows=[event('OPTION_SHADOW_LIFECYCLE_START','ACTIVE',signal,
               [leg(i) for i in range(-2,3)], expiry='2026-09-29', atm=23400),
          event('OPTION_SHADOW_LIFECYCLE_EXIT','CLOSED',signal,
               [leg(i,closed=True) for i in range(-2,3)], exit_reason='STRUCTURAL_EXIT')]
    d=project_shadow_dashboard(rows)
    assert d['account_pnl_rupees'] is None
    assert d['complete_closed_count']==1
    assert d['by_role'][0]['total_realized_premium_points']==8
    assert d['by_role'][2]['total_realized_premium_points']==10
    assert d['trades'][0]['legs'][0]['entry_open']==100
    assert d['trades'][0]['legs'][0]['exit_open']==108
    assert d['trades'][0]['legs'][0]['realized_points']==8


def test_missing_exact_option_entry_never_counts_as_loss_or_zero_pnl():
    d=project_shadow_dashboard([event('OPTION_SHADOW_LIFECYCLE_START','INCOMPLETE',
              '2026-09-23T10:15:00+05:30',issue='MISSING_EXACT_ENTRY_MINUTE')])
    assert d['complete_closed_count']==0
    assert d['incomplete_count']==1
    assert d['by_role'][0]['closed_count']==0
    assert d['by_role'][0]['total_realized_premium_points']==0


def test_restart_restore_does_not_double_count_trade():
    signal='2026-09-23T10:15:00+05:30'
    rows=[event('OPTION_SHADOW_LIFECYCLE_START','ACTIVE',signal,[leg(i) for i in range(-2,3)]),
          event('OPTION_SHADOW_LIFECYCLE_RESTORE','ACTIVE',signal,[leg(i) for i in range(-2,3)]),
          event('OPTION_SHADOW_LIFECYCLE_EXIT','CLOSED',signal,[leg(i,closed=True) for i in range(-2,3)])]
    assert project_shadow_dashboard(rows)['complete_closed_count']==1


def test_projection_is_deterministic_for_same_historical_live_rows():
    rows=[event('OPTION_SHADOW_LIFECYCLE_START','ACTIVE','2026-09-23T10:15:00+05:30',
                [leg(i) for i in range(-2,3)])]
    assert project_shadow_dashboard(rows)==project_shadow_dashboard(rows)
    assert project_shadow_dashboard(rows)['active_count']==1
