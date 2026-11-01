from datetime import date, datetime, timedelta, timezone

from market_lab.hilega_directional_coordinator_v1 import DirectionalDecision, HilegaDirectionalCoordinatorV1
from market_lab.hilega_directional_live_shadow_v1 import HilegaDirectionalLiveShadowCoordinatorV1
from market_lab.hilega_milega_strategy_v1 import FiveMinuteBar, StrategyEvent

IST = timezone(timedelta(hours=5, minutes=30))
D = date(2026, 9, 24)
T = datetime(2026, 9, 24, 10, 0, tzinfo=IST)


class _NoopSources:
    pass


def _event(kind, source="ROUTE_B", exit_reason=None):
    return StrategyEvent(
        event_type=kind,
        event_time=T,
        source=source,
        state_before="X",
        state_after="Y",
        price=23400.0,
        entry_time=None,
        entry_price=None,
        exit_reason=exit_reason,
        points=None,
        details=None,
    )


def test_directional_cutoff_closes_bearish_owner_without_reversal():
    c = HilegaDirectionalCoordinatorV1()
    c.session_date = D
    c.trade_owner = "BEARISH"
    c.bearish.session.session_date = D
    c.bearish.session.active = True
    c.bearish.session.source = "ROUTE_B"
    c.bearish.session.entry_time = datetime(2026, 9, 24, 13, 5, tzinfo=IST)
    c.bearish.session.entry_price = 23450.0
    c.bullish.session.session_date = D
    c.bullish.session.armed = True
    c.bullish.session.armed_time = datetime(2026, 9, 24, 14, 50, tzinfo=IST)

    d = c.on_session_cutoff(datetime(2026, 9, 24, 14, 55, tzinfo=IST), 23420.0)

    assert d.trade_owner_before == "BEARISH"
    assert d.trade_owner_after == "NONE"
    assert "BEARISH_SESSION_CUTOFF_EXIT_1455_OPEN" in {e.event_type for e in d.accepted_events}
    assert not d.suppressed_events
    assert c.bullish.session.session_locked
    assert c.bearish.session.session_locked


def test_live_starts_only_accepted_bearish_pe_shadow(tmp_path):
    live = HilegaDirectionalLiveShadowCoordinatorV1(
        market_sources=_NoopSources(),
        option_expiry=date(2026, 9, 29),
        step_audit_path=tmp_path / "audit.jsonl",
        health_path=tmp_path / "health.jsonl",
    )
    calls = []
    live._start_option = lambda **kw: calls.append(("start", kw["direction"]))
    live._close_option = lambda **kw: calls.append(("close", kw["direction"]))

    bearish = _event("ENTRY_BEARISH_ROUTE_B_STRUCTURAL")
    suppressed_bull = _event("ENTRY_PATH1_ROUTE_B_STRUCTURAL")
    decision = DirectionalDecision(
        event_time=T.isoformat(), trade_owner_before="NONE", trade_owner_after="BEARISH",
        accepted_events=(bearish,), suppressed_events=(suppressed_bull,),
        bullish_state="BULLISH_PATH1_ARMED", bearish_state="BEARISH_ACTIVE",
        bullish_armed=True, bearish_armed=False, note=None,
    )
    bar = FiveMinuteBar(T, 23410, 23420, 23390, 23400, None)
    live._handle_decision(now=T + timedelta(minutes=5), bar=bar, decision=decision, audit=False)

    assert calls == [("start", "BEARISH")]


def test_live_exit_does_not_start_same_candle_suppressed_opposite(tmp_path):
    live = HilegaDirectionalLiveShadowCoordinatorV1(
        market_sources=_NoopSources(),
        option_expiry=date(2026, 9, 29),
        step_audit_path=tmp_path / "audit.jsonl",
        health_path=tmp_path / "health.jsonl",
    )
    calls = []
    live._start_option = lambda **kw: calls.append(("start", kw["direction"]))
    live._close_option = lambda **kw: calls.append(("close", kw["direction"]))

    exit_event = _event("BEARISH_SESSION_CUTOFF_EXIT_1455_OPEN", exit_reason="SESSION_CUTOFF_14_55_OPEN")
    suppressed_bull = _event("ENTRY_PATH1_ROUTE_B_STRUCTURAL")
    decision = DirectionalDecision(
        event_time=T.isoformat(), trade_owner_before="BEARISH", trade_owner_after="NONE",
        accepted_events=(exit_event,), suppressed_events=(suppressed_bull,),
        bullish_state="BULLISH_PATH1_ARMED", bearish_state="BEARISH_PATH1_IDLE",
        bullish_armed=True, bearish_armed=False,
        note="BEARISH_EXIT; SAME_CANDLE_BULLISH_ENTRY_BLOCKED; PRESERVE_BULLISH_ARMED",
    )
    bar = FiveMinuteBar(T, 23410, 23420, 23390, 23400, None)
    live._handle_decision(now=T + timedelta(minutes=5), bar=bar, decision=decision, audit=False)

    assert calls == [("close", "BEARISH")]
