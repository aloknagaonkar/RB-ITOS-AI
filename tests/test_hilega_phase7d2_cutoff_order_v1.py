"""Cutoff chronology regression: event-time ordering, not broker arrival ordering."""
from datetime import date, datetime, timedelta

from market_lab.domain import HistoricalCandle, IST
from market_lab.hilega_milega_live_shadow_v1 import HilegaMilegaLiveShadowCoordinatorV1
from market_lab.hilega_milega_strategy_v1 import (
    FiveMinuteBar, HilegaMilegaBullishEngineV1, IndicatorSnapshot,
)

D = date(2026, 9, 23)

def ts(h, m, s=0):
    return datetime(2026, 9, 23, h, m, s, tzinfo=IST)

def candles(include_cutoff=True):
    out = []
    for i in range(5 + int(include_cutoff)):
        stamp = ts(14, 50) + timedelta(minutes=i)
        out.append(HistoricalCandle(provider='upstox', instrument_key='NSE_INDEX|Nifty 50',
                     session_date=D, timestamp=stamp, open=23432.1 if i == 5 else 23400+i,
                     high=23436, low=23395, close=23401+i, volume=100, open_interest=None))
    return out

class Sources:
    def __init__(self, with_cutoff=True):
        self.rows = candles(with_cutoff)
    def nifty_intraday_1m(self, *, now=None):
        return list(self.rows)

def coordinator(tmp_path, *, with_cutoff=True):
    c = HilegaMilegaLiveShadowCoordinatorV1(
        market_sources=Sources(with_cutoff), step_audit_path=tmp_path/'a.jsonl',
        health_path=tmp_path/'h.jsonl', cache_root=tmp_path/'cache', warmup_calendar_days=0)
    c._bootstrapped_date = D
    c._last_bar_ts = ts(14,45)
    c.strategy.session.session_date = D
    c.strategy.audit_store = c.step_audit
    return c

def test_bar_1450_precedes_available_cutoff_and_cancellation(tmp_path):
    c = coordinator(tmp_path)
    order = []
    def on_bar(bar):
        order.append(('bar',bar.ts))
        c.strategy.session.armed = True
        return []
    original_cutoff = c.strategy.on_session_cutoff
    def cutoff(boundary, price):
        order.append(('cutoff',boundary))
        return original_cutoff(boundary,price)
    c.strategy.on_bar = on_bar
    c.strategy.on_session_cutoff = cutoff
    result = c.process(ts(14,55,30))
    assert [x[0] for x in order] == ['bar','cutoff']
    assert order[0][1] == ts(14,50)
    assert result['cutoff_events'] == ['SESSION_CUTOFF_ARM_CANCELLED', 'SESSION_LOCKED_1455']
    assert result['bar_timestamp'] == ts(14,50).isoformat()
    assert c.step_audit.verify_chain() == (True, None)

def test_missing_cutoff_waits_after_processing_completed_bar_then_cancels(tmp_path):
    c = coordinator(tmp_path, with_cutoff=False)
    seen = []
    def on_bar(bar):
        seen.append(bar.ts)
        c.strategy.session.armed = True
        return []
    c.strategy.on_bar = on_bar
    first = c.process(ts(14,55,30))
    assert seen == [ts(14,50)]
    assert first['cutoff_events'] == []
    assert c.strategy.session.armed
    c.sources.rows = candles(True)
    second = c.process(ts(14,56,30))
    assert seen == [ts(14,50)]
    assert second['cutoff_events'] == ['SESSION_CUTOFF_ARM_CANCELLED', 'SESSION_LOCKED_1455']
    assert c.step_audit.verify_chain() == (True, None)

def test_cutoff_not_held_hostage_by_missing_completed_bar(tmp_path):
    c = coordinator(tmp_path)
    c.sources.rows = [candles(True)[-1]]  # only exact cutoff minute
    c.strategy.session.armed = True
    result = c.process(ts(14,55,30))
    assert result['cutoff_events'] == ['SESSION_CUTOFF_ARM_CANCELLED', 'SESSION_LOCKED_1455']
    assert c.strategy.session.session_locked
    assert c._last_bar_ts == ts(14,45)

def test_1450_route_a_setup_must_not_create_trade_at_1455():
    e = HilegaMilegaBullishEngineV1()
    e.process_enriched_bar_for_test(FiveMinuteBar(ts(14,45),100,101,99,100),IndicatorSnapshot(48,50,45))
    out=e.process_enriched_bar_for_test(FiveMinuteBar(ts(14,50),101,102,100,101),IndicatorSnapshot(55,52,49))
    assert [x.event_type for x in out] == ['PATH1_ARMED_RSI_CROSS_EMA3_UP']
    assert not e.session.active
    assert [x.event_type for x in e.on_session_cutoff(ts(14,55),101)] == [
        'SESSION_CUTOFF_ARM_CANCELLED','SESSION_LOCKED_1455']

def test_1450_route_b_cannot_enter_at_1455():
    e=HilegaMilegaBullishEngineV1()
    e.process_enriched_bar_for_test(FiveMinuteBar(ts(14,45),100,101,99,100), IndicatorSnapshot(30,32,29))
    out=e.process_enriched_bar_for_test(FiveMinuteBar(ts(14,50),101,102,100,101), IndicatorSnapshot(35,33,34))
    assert [x.event_type for x in out] == ['PATH1_ARMED_RSI_CROSS_EMA3_UP']
    assert not e.session.active

def test_delayed_cutoff_clamps_option_updates_to_1454(tmp_path):
    c=coordinator(tmp_path,with_cutoff=False)
    through=[]
    from types import SimpleNamespace
    c.sources.option_intraday_1m = lambda instrument: []
    c.option_shadow = SimpleNamespace(
        active=True, snapshot=None,
        update=lambda *, through_completed_minute, option_minutes: (through.append(through_completed_minute) or None),
    )
    c._update_option_shadow(ts(14,57,30))
    assert through == [ts(14,54)]

def test_real_coordinator_processes_1450_cross_then_cancels_without_trade(tmp_path):
    c = coordinator(tmp_path)
    c.strategy.previous_indicators = IndicatorSnapshot(41.3575, 43.2858, 48.3362)
    c.strategy.previous_bar = FiveMinuteBar(ts(14,45),23420,23422,23419,23420)
    c.strategy.indicators.update = lambda close: IndicatorSnapshot(43.6971, 43.4914, 47.9814)
    out = c.process(ts(14,55,30))
    assert out['events'] == ['PATH1_ARMED_RSI_CROSS_EMA3_UP']
    assert out['cutoff_events'] == ['SESSION_CUTOFF_ARM_CANCELLED', 'SESSION_LOCKED_1455']
    assert c.strategy.session.session_locked
    assert not c.strategy.session.active
    rows=c.step_audit.read_all()
    names=[(r['stage'], r['status']) for r in rows]
    arm=names.index(('STRATEGY_TRANSITION', 'PATH1_ARMED_RSI_CROSS_EMA3_UP'))
    cancel=names.index(('STRATEGY_TRANSITION', 'SESSION_CUTOFF_ARM_CANCELLED'))
    lock=names.index(('STRATEGY_TRANSITION', 'SESSION_LOCKED_1455'))
    assert arm < cancel < lock
    assert not any(r['stage']=='OPTION_CANDIDATE_SET' for r in rows)
    assert c.step_audit.verify_chain() == (True, None)
