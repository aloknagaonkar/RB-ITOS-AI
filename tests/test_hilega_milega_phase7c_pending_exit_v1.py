"""Regression for Sep23 late 11:50 exact CE exit and next-signal safety."""
from datetime import date, datetime, timedelta

from market_lab.domain import IST
from market_lab.hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set
from market_lab.hilega_milega_option_shadow_lifecycle_v1 import HilegaMilegaOptionShadowLifecycleV1
from market_lab.hilega_milega_live_shadow_v1 import HilegaMilegaLiveShadowCoordinatorV1
from market_lab.hilega_milega_trade_dashboard_v1 import project_shadow_dashboard
from market_lab.live_option_minute_source_v1 import CompletedOptionMinute

D = date(2026, 9, 23)
SIGNAL = datetime(2026, 9, 23, 11, 30, tzinfo=IST)
ENTRY = SIGNAL + timedelta(minutes=5)
EXIT = datetime(2026, 9, 23, 11, 50, tzinfo=IST)
KEYS = [f"CE-{x}" for x in (23350, 23400, 23450, 23500, 23550)]


def setup():
    cs = build_bullish_ce_candidate_set(signal_spot=23440.4, expiry=date(2026, 9, 29),
        contracts=[dict(instrument_key=k, strike_price=float(k[3:]), instrument_type='CE', expiry='2026-09-29') for k in KEYS])
    assert cs.status == 'AVAILABLE'
    rows = {k: [CompletedOptionMinute(k, ENTRY+timedelta(minutes=i), 100+i, 101+i,
                99+i, 100+i, 10) for i in range(30)] for k in KEYS}
    return cs, rows


def test_late_exact_exit_freezes_at_original_boundary_and_never_tracks_past_it():
    cs, rows = setup()
    tracker = HilegaMilegaOptionShadowLifecycleV1()
    tracker.start(signal_bar_ts=SIGNAL, signal_spot=23440.4, source='PATH1_ROUTE_A',
                  candidate_set=cs, option_minutes=lambda k: rows[k][:15])
    tracker.update(through_completed_minute=EXIT-timedelta(minutes=1),
                   option_minutes=lambda k: rows[k][:15])
    prior_mfe = tracker.snapshot.legs[0].mfe_points
    # Simulate exactly the real 11:50 poll, when data only exists through 11:49.
    pending = tracker.close(exit_boundary=EXIT, exit_reason='RSI_CROSS_BELOW_WMA21',
                    option_minutes=lambda k: rows[k][:15])
    assert pending.status == 'PENDING_EXACT_EXIT'
    assert not pending.active and not tracker.active
    assert pending.pending_exit_boundary == EXIT.isoformat()
    assert tracker.update(through_completed_minute=EXIT+timedelta(minutes=10),
        option_minutes=lambda k: rows[k]) is pending
    assert tracker.snapshot.legs[0].mfe_points == prior_mfe
    # At 11:51 the exact 11:50 option OPEN is available. No alternative minute.
    closed = tracker.retry_pending_exit(option_minutes=lambda k: rows[k][:16])
    assert closed.status == 'CLOSED' and not closed.active
    assert all(leg.exit_timestamp == EXIT.isoformat() and leg.exit_open == 115 for leg in closed.legs)
    assert closed.legs[0].mfe_points == prior_mfe
    assert closed.legs[0].realized_points == 15
    assert closed.payload()['order_created'] is False


def test_restart_recovers_frozen_audited_identity_and_exact_pending_exit():
    cs, rows = setup()
    first = HilegaMilegaOptionShadowLifecycleV1()
    first.start(signal_bar_ts=SIGNAL, signal_spot=23440.4, source='PATH1_ROUTE_A',
                candidate_set=cs, option_minutes=lambda k: rows[k][:15])
    first.close(exit_boundary=EXIT, exit_reason='RSI_CROSS_BELOW_WMA21',
                option_minutes=lambda k: rows[k][:15])
    reconstructed = HilegaMilegaOptionShadowLifecycleV1.from_audited_active_snapshot(first.snapshot.payload())
    assert reconstructed.pending_exit and not reconstructed.active
    assert reconstructed.snapshot.shadow_selected_instrument_keys == first.snapshot.shadow_selected_instrument_keys
    closed = reconstructed.retry_pending_exit(option_minutes=lambda k: rows[k][:16])
    assert closed.status == 'CLOSED' and all(leg.exit_timestamp == EXIT.isoformat() for leg in closed.legs)


def test_missing_exact_minute_never_uses_nearest_or_synthetic():
    cs, rows = setup()
    tracker = HilegaMilegaOptionShadowLifecycleV1()
    tracker.start(signal_bar_ts=SIGNAL, signal_spot=23440.4, source='PATH1_ROUTE_A',
                  candidate_set=cs, option_minutes=lambda k: rows[k])
    src = lambda k: [x for x in rows[k] if x.timestamp != EXIT]
    pending = tracker.close(exit_boundary=EXIT, exit_reason='RSI_CROSS_BELOW_WMA21', option_minutes=src)
    assert pending.status == 'PENDING_EXACT_EXIT'
    pending_again = tracker.retry_pending_exit(option_minutes=src)
    assert pending_again.status == 'PENDING_EXACT_EXIT'
    assert all(leg.exit_open is None for leg in pending_again.legs)


def test_entry_retry_requires_original_completed_minute():
    cs, rows = setup()
    tracker = HilegaMilegaOptionShadowLifecycleV1()
    attempted = tracker.start(signal_bar_ts=SIGNAL, signal_spot=23440.4, source='PATH1_ROUTE_A',
                candidate_set=cs, option_minutes=lambda k: [])
    assert attempted.status == 'INCOMPLETE'
    restarted = tracker.retry_missing_entry(option_minutes=lambda k: rows[k][:1])
    assert restarted.status == 'ACTIVE'
    assert all(x.entry_timestamp == ENTRY.isoformat() for x in restarted.legs)


def test_dashboard_legacy_post_exit_updates_are_excluded_and_pending_not_realized():
    cs, rows = setup()
    tracker = HilegaMilegaOptionShadowLifecycleV1()
    start = tracker.start(signal_bar_ts=SIGNAL, signal_spot=23440.4, source='PATH1_ROUTE_A',
                  candidate_set=cs, option_minutes=lambda k: rows[k]).payload()
    valid_update = tracker.update(through_completed_minute=EXIT-timedelta(minutes=1),
                                  option_minutes=lambda k: rows[k]).payload()
    pending = tracker.close(exit_boundary=EXIT, exit_reason='RSI_CROSS_BELOW_WMA21',
                  option_minutes=lambda k: rows[k][:15]).payload()
    legacy_bad_update = {**valid_update, 'legs': [{**leg, 'mfe_points': 9999} for leg in valid_update['legs']]}
    def event(stage, p):
        return dict(stage=stage, status=p['status'], payload=p)
    audit = [event('OPTION_SHADOW_LIFECYCLE_START', start),
             event('OPTION_SHADOW_LIFECYCLE_UPDATE', valid_update),
             event('OPTION_SHADOW_LIFECYCLE_EXIT', pending),
             event('OPTION_SHADOW_LIFECYCLE_UPDATE', legacy_bad_update)]
    projection = project_shadow_dashboard(audit)
    trade = projection['trades'][0]
    assert trade['status'] == 'PENDING_EXACT_EXIT'
    assert projection['pending_exit_count'] == 1
    assert projection['complete_closed_count'] == 0
    assert trade['legs'][0]['mfe_points'] != 9999
    closed = tracker.retry_pending_exit(option_minutes=lambda k: rows[k]).payload()
    audit.append(event('OPTION_SHADOW_LIFECYCLE_EXIT_RETRY', closed))
    projection = project_shadow_dashboard(audit)
    assert projection['complete_closed_count'] == 1
    assert projection['pending_exit_count'] == 0
    assert projection['trades'][0]['legs'][0]['exit_open'] == 115


def test_coordinator_pending_exit_is_independent_of_new_signal(tmp_path):
    class Source:
        def __init__(self, rows): self.rows=rows
        def option_intraday_1m(self, key): return self.rows[key][:15]
    cs, rows=setup()
    src=Source(rows)
    coordinator=HilegaMilegaLiveShadowCoordinatorV1(
        market_sources=src, step_audit_path=tmp_path/'a.jsonl',
        health_path=tmp_path/'h.jsonl', cache_root=tmp_path/'cache',
        warmup_calendar_days=0, option_expiry=date(2026,9,29))
    coordinator.option_shadow.start(signal_bar_ts=SIGNAL,signal_spot=23440.4,
        source='PATH1_ROUTE_A',candidate_set=cs,option_minutes=src.option_intraday_1m)
    coordinator._close_option_shadow(EXIT+timedelta(seconds=30),
        exit_boundary=EXIT,exit_reason='RSI_CROSS_BELOW_WMA21')
    assert SIGNAL.isoformat() in coordinator._pending_option_exits
    assert coordinator.option_shadow.snapshot is None
    # Simulate next entry using same valid candidate universe.
    coordinator.option_shadow.start(signal_bar_ts=SIGNAL+timedelta(minutes=20),
        signal_spot=23440.4,source='PATH1_ROUTE_A',candidate_set=cs,
        option_minutes=lambda k: rows[k][20:])
    next_signal = coordinator.option_shadow.snapshot.signal_bar
    src.option_intraday_1m=lambda k: rows[k][:16]
    coordinator._retry_pending_option_exits(EXIT+timedelta(minutes=1))
    assert coordinator.option_shadow.snapshot.signal_bar==next_signal
    assert SIGNAL.isoformat() not in coordinator._pending_option_exits
    assert coordinator.step_audit.verify_chain()==(True,None)


def test_restart_coordinator_uses_only_hash_verified_audited_pending_record(tmp_path):
    cs, rows = setup()
    class Source:
        def option_intraday_1m(self, key): return rows[key][:15]
    src=Source()
    path=tmp_path/'chain.jsonl'
    first=HilegaMilegaLiveShadowCoordinatorV1(market_sources=src,
        step_audit_path=path,health_path=tmp_path/'health1.jsonl',
        cache_root=tmp_path/'cache',warmup_calendar_days=0,
        option_expiry=date(2026,9,29))
    first.option_shadow.start(signal_bar_ts=SIGNAL,signal_spot=23440.4,
        source='PATH1_ROUTE_A',candidate_set=cs,option_minutes=src.option_intraday_1m)
    first._audit_runtime(ENTRY+timedelta(minutes=1),'OPTION_SHADOW_LIFECYCLE_START',
        'ACTIVE',first.option_shadow.snapshot.payload())
    first._close_option_shadow(EXIT+timedelta(seconds=30),
        exit_boundary=EXIT,exit_reason='RSI_CROSS_BELOW_WMA21')
    assert first.step_audit.verify_chain()==(True,None)
    restarted=HilegaMilegaLiveShadowCoordinatorV1(market_sources=src,
        step_audit_path=path,health_path=tmp_path/'health2.jsonl',
        cache_root=tmp_path/'cache',warmup_calendar_days=0,
        option_expiry=date(2026,9,29))
    restarted._restore_pending_option_exits(EXIT+timedelta(minutes=1))
    assert SIGNAL.isoformat() in restarted._pending_option_exits
    assert restarted.step_audit.verify_chain()==(True,None)
    # No repeat transition when option minute is still absent.
    previous_count=len(restarted.step_audit.read_all())
    restarted._retry_pending_option_exits(EXIT+timedelta(minutes=1))
    assert len(restarted.step_audit.read_all())==previous_count
    src.option_intraday_1m=lambda k: rows[k][:16]
    restarted._retry_pending_option_exits(EXIT+timedelta(minutes=2))
    assert SIGNAL.isoformat() not in restarted._pending_option_exits
    assert restarted.step_audit.verify_chain()==(True,None)
    d=project_shadow_dashboard(restarted.step_audit.read_all())
    assert d['complete_closed_count']==1 and d['pending_exit_count']==0


def test_historical_parity_source_does_not_expose_future_option_minutes():
    from market_lab.hilega_milega_functional_parity_replay_v1 import HistoricalParityMarketSourcesV1
    from market_lab.domain import HistoricalCandle
    class Gateway:
        def historical_candles(self, instrument_key, session_date): return []
        def historical_option_candles(self, instrument_key, session_date):
            return [HistoricalCandle(provider='upstox',instrument_key=instrument_key,
                session_date=session_date,timestamp=ENTRY+timedelta(minutes=i),
                open=100+i,high=102+i,low=99+i,close=101+i,
                volume=10,open_interest=None) for i in range(3)]
    g=Gateway()
    source=HistoricalParityMarketSourcesV1(g, D)
    assert source.option_intraday_1m('CE-23450')==[]
    source.nifty_intraday_1m(now=ENTRY+timedelta(seconds=30))
    assert source.option_intraday_1m('CE-23450')==[]
    source.nifty_intraday_1m(now=ENTRY+timedelta(minutes=1, seconds=30))
    got=source.option_intraday_1m('CE-23450')
    assert len(got)==1 and got[0].timestamp==ENTRY
