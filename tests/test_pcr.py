from datetime import date, datetime, timedelta
import pytest
from market_lab.domain import IST, PCRConfig, Quote, Snapshot, evaluate
from market_lab.gateways import DemoGateway

AT = datetime(2026, 9, 9, 9, 20, tzinfo=IST)


@pytest.fixture
def config():
    return PCRConfig(expiry=date(2026, 9, 15), wings=1)


@pytest.fixture
def snapshot(config):
    return DemoGateway().collect_at(config, AT, 0)


def result(out, mode):
    return next(r for r in out.results if r.mode == mode)


def test_ratio_uses_sums(config, snapshot):
    quotes = [
        Quote(key=c.key, oi=(10 if c.strike == 25000 else 100) if c.side == "CE" else 50)
        for c in snapshot.catalog
    ]
    out = evaluate(snapshot.model_copy(update={"quotes": quotes}), config)
    assert result(out, "moving").pcr == pytest.approx(150 / 210)


def test_fixed_and_moving(config, snapshot):
    first = evaluate(snapshot, config)
    later = DemoGateway().collect_at(config, AT + timedelta(minutes=1), 1).model_copy(update={"spot": 25100})
    out = evaluate(later, config, first.anchor)
    assert result(out, "fixed").strikes == [24950, 25000, 25050]
    assert result(out, "moving").strikes == [25050, 25100, 25150]
    assert out.anchor.captured_at == AT


def test_midpoint_selects_lower_strike(config, snapshot):
    assert result(evaluate(snapshot.model_copy(update={"spot": 25025}), config), "moving").atm == 25000


def test_missing_oi_does_not_change_range(config, snapshot):
    key = next(c.key for c in snapshot.catalog if c.strike == 25000 and c.side == "PE")
    out = evaluate(
        snapshot.model_copy(update={"quotes": [q for q in snapshot.quotes if q.key != key]}), config
    )
    r = result(out, "moving")
    assert r.expected == 6 and r.received == 5 and r.pcr is None
    assert "missing_or_invalid_oi" in r.issues


def test_zero_calls_unavailable_zero_puts_valid(config, snapshot):
    for side, expected in [("CE", None), ("PE", 0)]:
        keys = {c.key for c in snapshot.catalog if c.side == side}
        quotes = [q.model_copy(update={"oi": 0}) if q.key in keys else q for q in snapshot.quotes]
        assert (
            result(evaluate(snapshot.model_copy(update={"quotes": quotes}), config), "moving").pcr == expected
        )


@pytest.mark.parametrize("offset,issue", [(-31, "spot_quote_stale"), (3, "spot_timestamp_in_future")])
def test_bad_quote_time_blocks_anchor(config, snapshot, offset, issue):
    out = evaluate(snapshot.model_copy(update={"spot_feed_at": AT + timedelta(seconds=offset)}), config)
    assert out.anchor is None and issue in result(out, "moving").issues


def test_unknown_timestamp_slow_collection(config, snapshot):
    out = evaluate(
        snapshot.model_copy(update={"spot_feed_at": None, "started_at": AT - timedelta(seconds=21)}), config
    )
    assert out.anchor is None
    assert {"spot_timestamp_unknown", "collection_too_slow"} <= set(result(out, "moving").issues)


def test_missed_anchor_not_replaced(config):
    out = evaluate(DemoGateway().collect_at(config, AT + timedelta(minutes=3), 0), config)
    assert out.anchor_status == "missed" and result(out, "fixed").pcr is None
    assert result(out, "moving").pcr is not None


def test_anchor_next_day(config, snapshot):
    old = evaluate(snapshot, config).anchor
    out = evaluate(DemoGateway().collect_at(config, AT + timedelta(days=1), 3), config, old)
    assert out.anchor.session != old.session


def test_anchor_window_boundaries(config):
    early = evaluate(DemoGateway().collect_at(config, AT - timedelta(minutes=1), 0), config)
    assert early.anchor_status == "waiting" and early.anchor is None
    edge = evaluate(DemoGateway().collect_at(config, AT + timedelta(seconds=120), 0), config)
    assert edge.anchor is not None


def test_insufficient_range(config, snapshot):
    out = evaluate(snapshot.model_copy(update={"spot": 24000}), config)
    assert out.anchor is None and "insufficient_strikes" in result(out, "moving").issues


def test_duplicates_rejected(snapshot):
    data = snapshot.model_dump()
    data["catalog"].append(data["catalog"][0])
    with pytest.raises(ValueError):
        Snapshot.model_validate(data)


def test_expiry_and_session(config):
    out = evaluate(DemoGateway().collect_at(config, AT + timedelta(days=7), 0), config)
    assert "expiry_passed" in result(out, "moving").issues
    out = evaluate(DemoGateway().collect_at(config, AT + timedelta(days=3), 0), config)
    assert "outside_session" in result(out, "moving").issues


def test_oi_freshness_unknown_and_no_entries(config, snapshot):
    out = evaluate(snapshot.model_copy(update={"oi_source_at": None}), config)
    assert "oi_source_timestamp_unknown" in out.warnings and not out.entry_eligible


def test_panel_change_oi_and_percent_use_summed_previous_oi(config, snapshot):
    selected = {24950, 25000, 25050}
    quotes = []
    for contract in snapshot.catalog:
        if contract.strike in selected:
            current = 120 if contract.side == "CE" else 90
            previous = 100 if contract.side == "CE" else 75
        else:
            current = previous = 10
        quotes.append(Quote(key=contract.key, oi=current, prev_oi=previous))
    panel = result(evaluate(snapshot.model_copy(update={"quotes": quotes}), config), "moving")
    assert panel.call_oi == 360 and panel.call_prev_oi == 300
    assert panel.call_change_oi == 60 and panel.call_change_pct == pytest.approx(20)
    assert panel.put_oi == 270 and panel.put_prev_oi == 225
    assert panel.put_change_oi == 45 and panel.put_change_pct == pytest.approx(20)


def test_incomplete_previous_oi_does_not_invent_change(config, snapshot):
    first = snapshot.quotes[0]
    quotes = [q.model_copy(update={"prev_oi": None}) if q.key == first.key else q for q in snapshot.quotes]
    panel = result(evaluate(snapshot.model_copy(update={"quotes": quotes}), config), "full")
    assert panel.call_change_oi is None and panel.call_change_pct is None
