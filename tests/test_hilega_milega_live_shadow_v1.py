from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.domain import HistoricalCandle
from market_lab.hilega_milega_live_shadow_v1 import (
    HilegaMilegaLiveShadowCoordinatorV1,
    completed_intraday_1m_for_label,
    latest_completed_5m_label,
)
from market_lab.hilega_milega_strategy_v1 import FiveMinuteBar, HilegaMilegaBullishEngineV1

IST=ZoneInfo('Asia/Kolkata')
UNDERLYING='NSE_INDEX|Nifty 50'


def minute_rows(session_date:date,start_h=9,start_m=15,count=75,base=23000.0):
    start=datetime(session_date.year,session_date.month,session_date.day,start_h,start_m,tzinfo=IST)
    rows=[]
    for i in range(count):
        px=base+i*0.1
        rows.append(HistoricalCandle(provider='upstox',instrument_key=UNDERLYING,session_date=session_date,timestamp=start+timedelta(minutes=i),open=px,high=px+1,low=px-1,close=px+0.2,volume=100,open_interest=None))
    return rows


class FakeSources:
    def __init__(self, current_date:date, current_rows):
        self.current_date=current_date;self.current_rows=current_rows;self.history={}
    def historical_candles(self,instrument_key,session_date):
        return list(self.history.get(session_date,[]))
    def nifty_intraday_1m(self,*,now=None):
        return list(self.current_rows)


def test_latest_completed_label_is_previous_slot():
    now=datetime(2026,9,23,10,0,30,tzinfo=IST)
    assert latest_completed_5m_label(now).strftime('%H:%M')=='09:55'


def test_direct_cutoff_does_not_advance_indicator_state(tmp_path):
    e=HilegaMilegaBullishEngineV1()
    # warm and then force a representative active state; cutoff itself must not
    # consume a partial candle into the indicator chain.
    d=date(2026,9,23)
    t=datetime(2026,9,23,10,0,tzinfo=IST)
    for i in range(40):
        e.on_bar(FiveMinuteBar(t+timedelta(minutes=5*i),100+i,101+i,99+i,100+i))
    before=e.indicators._last_close
    e.session.active=True;e.session.source='PATH1_ROUTE_B_STRUCTURAL';e.session.entry_time=datetime(2026,9,23,14,40,tzinfo=IST);e.session.entry_price=25000
    events=e.on_session_cutoff(datetime(2026,9,23,14,55,tzinfo=IST),25010)
    assert e.indicators._last_close==before
    assert [x.event_type for x in events]==['SESSION_CUTOFF_EXIT_1455_OPEN','SESSION_LOCKED_1455']
    assert events[0].points==10
    assert e.session.session_locked


def test_live_coordinator_bootstrap_is_not_live_audited_and_processes_only_completed_bar(tmp_path):
    d=date(2026,9,23)
    # through 10:04 -> exact bars 09:15..10:00 available; at 10:05:30 target=10:00
    rows=minute_rows(d,count=50)
    src=FakeSources(d,rows)
    # one prior session is sufficient for test warmup mechanics
    prior=d-timedelta(days=1);src.history[prior]=minute_rows(prior,count=75,base=22900)
    audit=tmp_path/'step.jsonl';health=tmp_path/'health.jsonl'
    c=HilegaMilegaLiveShadowCoordinatorV1(market_sources=src,step_audit_path=audit,health_path=health,cache_root=tmp_path/'cache',warmup_calendar_days=2)
    now=datetime(2026,9,23,10,5,30,tzinfo=IST)
    out=c.process(now)
    # bootstrap reconstructed all completed bars including 10:00, so no duplicate live process
    assert out['status']=='NO_NEW_COMPLETED_BAR'
    rows_audit=c.step_audit.read_all()
    assert [r['stage'] for r in rows_audit].count('LIVE_BOOTSTRAP')==1

    recovered_indicator_rows = [
        r for r in rows_audit
        if r['stage'] == 'INDICATOR_CALCULATION'
    ]
    assert recovered_indicator_rows
    assert all(
        (r.get('payload') or {}).get('bootstrap_recovered') is True
        for r in recovered_indicator_rows
    )
    assert all(
        (r.get('payload') or {}).get('recovery_source')
        == 'CURRENT_SESSION_BOOTSTRAP_REPLAY'
        for r in recovered_indicator_rows
    )


def test_live_cutoff_uses_1455_minute_open(tmp_path):
    d=date(2026,9,23)
    rows=minute_rows(d,count=341)  # through 14:55
    src=FakeSources(d,rows)
    audit=tmp_path/'step.jsonl';health=tmp_path/'health.jsonl'
    c=HilegaMilegaLiveShadowCoordinatorV1(market_sources=src,step_audit_path=audit,health_path=health,cache_root=tmp_path/'cache',warmup_calendar_days=0)
    # seed current reconstructed engine state directly to focus on cutoff source semantics
    c._bootstrapped_date=d
    c.strategy.audit_store=c.step_audit
    c.strategy.session.session_date=d
    c.strategy.session.active=True
    c.strategy.session.source='PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'
    c.strategy.session.entry_time=datetime(2026,9,23,14,45,tzinfo=IST)
    c.strategy.session.entry_price=23000
    out=c.process_cutoff(datetime(2026,9,23,14,55,30,tzinfo=IST),intraday=rows)
    expected=[r for r in rows if r.timestamp.strftime('%H:%M')=='14:55'][0].open
    assert out[0].event_type=='SESSION_CUTOFF_EXIT_1455_OPEN'
    assert out[0].price==expected
    assert c.strategy.session.session_locked
    assert c.step_audit.verify_chain()==(True,None)


def test_live_bootstrap_ignores_current_partial_5m_tail(tmp_path):
    d=date(2026,9,23)
    # 09:15..09:37.  The 09:35 slot is still forming and must not be passed
    # into strict exact-5m aggregation. At 09:37:30 latest completed=09:30.
    rows=minute_rows(d,count=23)
    src=FakeSources(d,rows)
    audit=tmp_path/'step.jsonl';health=tmp_path/'health.jsonl'
    c=HilegaMilegaLiveShadowCoordinatorV1(
        market_sources=src,step_audit_path=audit,health_path=health,
        cache_root=tmp_path/'cache',warmup_calendar_days=0,
    )
    now=datetime(2026,9,23,9,37,30,tzinfo=IST)
    out=c.bootstrap(now)
    assert out['status']=='PASS'
    assert c._last_bar_ts.strftime('%H:%M')=='09:30'
    assert out['bars_replayed']==4


def test_live_process_ignores_partial_tail_after_bootstrap(tmp_path):
    d=date(2026,9,23)
    # Through 10:07 => complete 10:00 bar plus partial 10:05 slot.
    rows=minute_rows(d,count=53)
    src=FakeSources(d,rows)
    audit=tmp_path/'step.jsonl';health=tmp_path/'health.jsonl'
    c=HilegaMilegaLiveShadowCoordinatorV1(
        market_sources=src,step_audit_path=audit,health_path=health,
        cache_root=tmp_path/'cache',warmup_calendar_days=0,
    )
    now=datetime(2026,9,23,10,7,30,tzinfo=IST)
    out=c.process(now)
    assert out['status']=='NO_NEW_COMPLETED_BAR'
    assert c._last_bar_ts.strftime('%H:%M')=='10:00'
    assert c.step_audit.verify_chain()==(True,None)


def test_option_candidate_observation_is_audited_but_never_selects_or_orders(tmp_path):
    from datetime import date
    from market_lab.hilega_milega_live_shadow_v1 import HilegaMilegaLiveShadowCoordinatorV1
    from market_lab.hilega_milega_strategy_v1 import FiveMinuteBar, IndicatorSnapshot
    from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

    class Sources:
        def option_contracts(self, underlying, expiry):
            rows=[]
            for strike in [23250,23300,23350,23400,23450]:
                rows.append({"expiry":expiry.isoformat(),"strike_price":strike,"instrument_type":"CE","instrument_key":f"CE-{strike}"})
            return rows

    path=tmp_path/"audit.jsonl"
    c=HilegaMilegaLiveShadowCoordinatorV1(market_sources=Sources(),step_audit_path=path,health_path=tmp_path/"h.jsonl",option_expiry=date(2026,9,24))
    c.strategy.audit_store=c.step_audit
    # Drive canonical enriched strategy directly to create a Route A entry event,
    # then run only the additive option-observation hook.
    from market_lab.domain import IST
    from datetime import datetime
    prev=IndicatorSnapshot(51,52,50)
    cur=IndicatorSnapshot(55,53,51)
    c.strategy.previous_indicators=prev
    bar=FiveMinuteBar(datetime(2026,9,23,9,40,tzinfo=IST),23370,23382,23368,23355,None)
    events=c.strategy._process_enriched_bar(bar,cur)
    c._observe_option_candidates(datetime(2026,9,23,9,45,30,tzinfo=IST),bar,events)
    lines=[__import__('json').loads(x) for x in path.read_text().splitlines()]
    row=[x for x in lines if x["stage"]=="OPTION_CANDIDATE_SET"][-1]
    assert row["status"]=="PASS"
    assert row["payload"]["selected_instrument_key"] is None
    assert row["payload"]["selection_policy"]=="UNDECIDED_CANDIDATE_SET_ONLY"
    assert row["payload"]["order_created"] is False


def test_option_candidate_market_snapshot_is_exact_and_never_selects_or_orders(tmp_path):
    from datetime import date, datetime
    from market_lab.domain import IST
    from market_lab.hilega_milega_live_shadow_v1 import HilegaMilegaLiveShadowCoordinatorV1
    from market_lab.hilega_milega_strategy_v1 import FiveMinuteBar, IndicatorSnapshot
    from market_lab.live_option_minute_source_v1 import CompletedOptionMinute

    class Sources:
        def option_contracts(self, underlying, expiry):
            return [
                {"expiry":expiry.isoformat(),"strike_price":strike,"instrument_type":"CE","instrument_key":f"CE-{strike}"}
                for strike in [23250,23300,23350,23400,23450]
            ]
        def option_intraday_1m(self, instrument_key):
            return [CompletedOptionMinute(instrument_key,datetime(2026,9,23,9,44,tzinfo=IST),100,102,99,101,123)]

    path=tmp_path/'audit.jsonl'
    c=HilegaMilegaLiveShadowCoordinatorV1(
        market_sources=Sources(), step_audit_path=path, health_path=tmp_path/'h.jsonl',
        option_expiry=date(2026,9,24),
    )
    c.strategy.audit_store=c.step_audit
    c.strategy.previous_indicators=IndicatorSnapshot(51,52,50)
    bar=FiveMinuteBar(datetime(2026,9,23,9,40,tzinfo=IST),23370,23382,23368,23355,None)
    events=c.strategy._process_enriched_bar(bar,IndicatorSnapshot(55,53,51))
    c._observe_option_candidates(datetime(2026,9,23,9,45,30,tzinfo=IST),bar,events)
    rows=c.step_audit.read_all()
    snap=[x for x in rows if x['stage']=='OPTION_CANDIDATE_MARKET_SNAPSHOT'][-1]
    assert snap['status']=='PASS'
    assert snap['payload']['expected_option_minute'].endswith('09:44:00+05:30')
    assert len(snap['payload']['snapshots'])==5
    assert snap['payload']['selected_instrument_key'] is None
    assert snap['payload']['order_created'] is False


def test_option_shadow_lifecycle_starts_all_five_and_updates_without_orders(tmp_path):
    from datetime import date, datetime, timedelta
    from market_lab.domain import IST
    from market_lab.hilega_milega_live_shadow_v1 import HilegaMilegaLiveShadowCoordinatorV1
    from market_lab.hilega_milega_strategy_v1 import FiveMinuteBar, IndicatorSnapshot
    from market_lab.live_option_minute_source_v1 import CompletedOptionMinute

    boundary = datetime(2026, 9, 23, 9, 45, tzinfo=IST)

    class Sources:
        def option_contracts(self, underlying, expiry):
            return [
                {"expiry": expiry.isoformat(), "strike_price": strike, "instrument_type": "CE", "instrument_key": f"CE-{strike}"}
                for strike in [23250, 23300, 23350, 23400, 23450]
            ]

        def option_intraday_1m(self, instrument_key):
            return [
                CompletedOptionMinute(
                    instrument_key,
                    boundary + timedelta(minutes=i),
                    100 + i,
                    102 + i,
                    99 + i,
                    101 + i,
                    1000 + i,
                )
                for i in range(10)
            ]

    path = tmp_path / "audit.jsonl"
    c = HilegaMilegaLiveShadowCoordinatorV1(
        market_sources=Sources(),
        step_audit_path=path,
        health_path=tmp_path / "h.jsonl",
        option_expiry=date(2026, 9, 29),
    )
    c.strategy.audit_store = c.step_audit
    c.strategy.previous_indicators = IndicatorSnapshot(51, 52, 50)
    bar = FiveMinuteBar(datetime(2026, 9, 23, 9, 40, tzinfo=IST), 23370, 23382, 23368, 23355, None)
    events = c.strategy._process_enriched_bar(bar, IndicatorSnapshot(55, 53, 51))
    c._observe_option_candidates(datetime(2026, 9, 23, 9, 45, 30, tzinfo=IST), bar, events)

    rows = c.step_audit.read_all()
    start = [x for x in rows if x["stage"] == "OPTION_SHADOW_LIFECYCLE_START"][-1]
    assert start["status"] == "PASS"
    assert start["payload"]["selection_policy"] == "ALL_ATM_PLUS_MINUS_2_CE_SHADOW"
    assert len(start["payload"]["shadow_selected_instrument_keys"]) == 5
    assert start["payload"]["order_created"] is False
    assert start["payload"]["quantity"] is None

    c._update_option_shadow(datetime(2026, 9, 23, 9, 48, 30, tzinfo=IST))
    rows = c.step_audit.read_all()
    update = [x for x in rows if x["stage"] == "OPTION_SHADOW_LIFECYCLE_UPDATE"][-1]
    assert update["status"] == "PASS"
    assert update["payload"]["latest_completed_minute"].endswith("09:47:00+05:30")
    assert len(update["payload"]["legs"]) == 5
    assert update["payload"]["execution_enabled"] is False
    assert update["payload"]["paper_order_enabled"] is False
