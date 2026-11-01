from datetime import datetime, timedelta
from math import inf, nan
from types import SimpleNamespace

from market_lab.domain import IST
from market_lab.hilega_milega_strategy_v1 import IndicatorSnapshot, HilegaMilegaIndicatorEngineV1
from market_lab.live_option_minute_source_v1 import CompletedOptionMinute, validate_option_minute
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1
from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1


def test_nonfinite_market_inputs_are_unhealthy():
    ts = datetime(2026, 9, 29, 10, 0, tzinfo=IST)
    for invalid in (nan, inf, -inf):
        bar = CompletedOptionMinute('X', ts, 100, 101, 99, invalid)
        assert validate_option_minute(bar, expected_instrument_key='X', previous_timestamp=None).reason == 'OPTION_NONFINITE_OHLC'
        assert not IndicatorSnapshot(invalid, 50, 50).ready
    engine = HilegaMilegaIndicatorEngineV1()
    engine.update(100)
    import pytest
    with pytest.raises(ValueError, match='finite'):
        engine.update(nan)
    assert engine._last_close == 100


def test_audit_append_preserves_sequence_and_rejects_partial_tail(tmp_path):
    path = tmp_path / 'audit.jsonl'
    store = ShadowStepAuditStoreV1(path)
    ts = datetime(2026, 9, 29, 10, 0, tzinfo=IST)
    for sequence in range(1, 51):
        assert store.append(event_time=ts, checkpoint=ts, stage='TEST', status='OK').sequence == sequence
    assert store.verify_chain() == (True, None)
    with path.open('ab') as handle:
        handle.write(b'{"partial":')
    import pytest
    with pytest.raises(ValueError, match='incomplete final record'):
        store.append(event_time=ts, checkpoint=ts, stage='TEST', status='OK')


def test_late_midpoint_minute_is_quarantined(tmp_path):
    start = datetime(2026, 9, 29, 10, 0, tzinfo=IST)
    def bar(offset):
        return SimpleNamespace(timestamp=start + timedelta(minutes=offset), open=100, high=101, low=99, close=100, volume=100)
    class Source:
        offsets = [0, 2]
        def nifty_intraday_1m(self, *, now):
            return [bar(i) for i in self.offsets]
        def nifty_futures_intraday_1m(self, *, now):
            return [bar(i) for i in self.offsets]
    source = Source()
    coordinator = MidpointLiveShadowCoordinatorV1(market_sources=source, audit_path=tmp_path / 'midpoint.jsonl')
    coordinator.process(start + timedelta(minutes=4))
    source.offsets = [0, 1, 2]
    result = coordinator.process(start + timedelta(minutes=5))
    assert result['quarantined_late_minutes'] == 1
    assert [x.timestamp for x in coordinator.state.observations] == [start.isoformat(), (start + timedelta(minutes=2)).isoformat()]


def test_incremental_futures_vwap_matches_batch_and_quarantines_revision(tmp_path):
    start = datetime(2026, 9, 29, 10, 0, tzinfo=IST)
    def bar(offset, close):
        return SimpleNamespace(timestamp=start + timedelta(minutes=offset), close=close, volume=100)
    coordinator = MidpointLiveShadowCoordinatorV1(market_sources=None, audit_path=tmp_path / 'audit.jsonl')
    coordinator._reset_session(start.date())
    rows = [bar(0, 100), bar(1, 110), bar(2, 120)]
    first = coordinator._futures_vwap_map(rows[:2], start + timedelta(minutes=1))
    second = coordinator._futures_vwap_map(rows, start + timedelta(minutes=2))
    assert first[start + timedelta(minutes=1)][1] == 105
    assert second[start + timedelta(minutes=2)][1] == 110
    revised = [bar(0, 100), bar(1, 999), bar(2, 120)]
    assert coordinator._futures_vwap_map(revised, start + timedelta(minutes=2)) == second
    assert len(coordinator.state.quarantined_revised_futures_minutes) == 1


def test_midpoint_session_reset_records_unresolved_active_position(tmp_path):
    from market_lab.midpoint_strategy.structure import ReferenceStructure
    from market_lab.midpoint_strategy.runtime import MidpointFamilyBRuntime
    from market_lab.midpoint_strategy.live_shadow_v1 import _ReferenceRuntime
    from market_lab.midpoint_strategy.family_b_shadow import FamilyBShadowRuntime
    from market_lab.midpoint_strategy.models import MidpointFamily, MidpointShadowState
    from market_lab.midpoint_strategy.family_b_detector import FamilyBObservation
    from datetime import date
    start = datetime(2026, 9, 29, 9, 26, tzinfo=IST)
    path = tmp_path / 'audit.jsonl'
    c = MidpointLiveShadowCoordinatorV1(market_sources=None, audit_path=path)
    c._reset_session(start.date())
    ref = ReferenceStructure(start.date().isoformat(), 'RED', (start-timedelta(minutes=6)).isoformat(),
                             (start-timedelta(minutes=2)).isoformat(), 22685, 22656)
    runtime = MidpointFamilyBRuntime(reference=ref)
    runtime.family = MidpointFamily.E
    runtime.lifecycle = FamilyBShadowRuntime(direction='BEARISH', entry_timestamp=start,
                                            entry_underlying_close=22652, family=MidpointFamily.E,
                                            state=MidpointShadowState.ACTIVE)
    c.state.references['RED'] = _ReferenceRuntime(reference=ref, runtime=runtime)
    c.state.active_reference_type = 'RED'
    c.state.observations.append(FamilyBObservation(start.isoformat(),22640,22650,22690))
    c._reset_session(date(2026, 9, 30))
    assert 'SESSION_END_UNRESOLVED' in path.read_text()
    import json
    assert json.loads(path.read_text().splitlines()[-1])['evidence']['order_sent'] is False


def test_future_candle_does_not_change_earlier_midpoint_audit(tmp_path):
    start = datetime(2026, 9, 29, 9, 20, tzinfo=IST)
    def bar(i):
        ts = start + timedelta(minutes=i)
        price = 100 - i
        return SimpleNamespace(timestamp=ts, open=price+1, high=price+2,
                               low=price-2, close=price, volume=100)
    class Source:
        def __init__(self, count): self.count = count
        def nifty_intraday_1m(self, *, now): return [bar(i) for i in range(self.count)]
        def nifty_futures_intraday_1m(self, *, now): return [bar(i) for i in range(self.count)]
    now = start + timedelta(minutes=8)
    first = tmp_path / 'first.jsonl'; second = tmp_path / 'second.jsonl'
    MidpointLiveShadowCoordinatorV1(market_sources=Source(8), audit_path=first).process(now)
    MidpointLiveShadowCoordinatorV1(market_sources=Source(12), audit_path=second).process(now)
    assert first.read_bytes() == second.read_bytes()
