from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.domain import HistoricalCandle
from market_lab.hilega_milega_live_shadow_v1 import (
    HilegaMilegaLiveShadowCoordinatorV1,
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
    assert not any(r['stage']=='INDICATOR_CALCULATION' for r in rows_audit)


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
