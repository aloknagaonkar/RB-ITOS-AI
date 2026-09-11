from datetime import date, datetime, timedelta

import pytest

from market_lab.domain import (
    Contract,
    Quote,
    Snapshot,
    StrikePositioningClassification as Classification,
    StrikePositioningConfig,
)
from market_lab.positioning import calculate_strike_positioning, select_strike_window


AT = datetime.fromisoformat("2026-09-09T09:30:00+05:30")
CONFIG = StrikePositioningConfig(
    min_price_change_pct=10,
    min_oi_change_pct=10,
)


def snapshot(
    at=AT,
    *,
    key="NSE_FO|1",
    ltp=110.0,
    oi=110,
    prev_oi=9999,
    raw_ltp=None,
    expiry=date(2026, 9, 15),
):
    market_data = {"ltp": raw_ltp} if raw_ltp is not None else {}
    raw = {"chain": {"data": [{
        "call_options": {"instrument_key": key, "market_data": market_data}
    }]}}
    return Snapshot(
        provider="upstox",
        underlying="NSE_INDEX|Nifty 50",
        expiry=expiry,
        started_at=at - timedelta(seconds=1),
        received_at=at,
        spot=25000,
        spot_feed_at=None,
        catalog=[Contract(key=key, strike=25000, side="CE")],
        quotes=[Quote(key=key, ltp=ltp, oi=oi, prev_oi=prev_oi)],
        raw=raw,
    )


def result(current, history, config=CONFIG):
    return calculate_strike_positioning(2, 7, current, history, 300, config)[0]


@pytest.mark.parametrize(
    "current_ltp,current_oi,expected",
    [
        (110, 110, Classification.LONG_BUILDUP),
        (90, 110, Classification.SHORT_BUILDUP),
        (90, 90, Classification.LONG_UNWINDING),
        (110, 90, Classification.SHORT_COVERING),
        (105, 105, Classification.NEUTRAL),
    ],
)
def test_classification_and_exact_boundaries(current_ltp, current_oi, expected):
    baseline = snapshot(AT - timedelta(minutes=5), ltp=100, oi=100)
    value = result(snapshot(ltp=current_ltp, oi=current_oi), [(1, baseline)])
    assert value.classification == expected
    assert value.status == "AVAILABLE"


@pytest.mark.parametrize(
    "current,baseline",
    [
        (snapshot(ltp=None), snapshot(AT - timedelta(minutes=5), ltp=100)),
        (snapshot(ltp=0), snapshot(AT - timedelta(minutes=5), ltp=100)),
        (snapshot(ltp=110), snapshot(AT - timedelta(minutes=5), ltp=0)),
        (snapshot(ltp=110, oi=110), snapshot(AT - timedelta(minutes=5), ltp=100, oi=0)),
    ],
)
def test_missing_or_zero_required_denominators_are_unavailable(current, baseline):
    value = result(current, [(1, baseline)])
    assert value.classification == Classification.UNAVAILABLE
    assert value.status == "UNAVAILABLE"


def test_latest_backward_baseline_is_deterministic_and_never_uses_newer_record():
    exact = snapshot(AT - timedelta(minutes=5), ltp=100, oi=100)
    older = snapshot(AT - timedelta(minutes=5, seconds=10), ltp=80, oi=80)
    newer = snapshot(AT - timedelta(minutes=4, seconds=59), ltp=109, oi=109)
    value = result(snapshot(), [(3, newer), (1, older), (2, exact)])
    assert value.baseline_received_at == exact.received_at
    assert value.baseline_ltp == 100
    assert value.actual_elapsed_seconds == 300


def test_tolerance_failure_is_unavailable():
    baseline = snapshot(AT - timedelta(minutes=5, seconds=61), ltp=100, oi=100)
    assert result(snapshot(), [(1, baseline)]).classification == Classification.UNAVAILABLE


@pytest.mark.parametrize(
    "horizon_seconds,drift_seconds",
    [(300, 52), (900, 2), (1800, 24)],
)
def test_supported_horizons_accept_runtime_backward_drift(horizon_seconds, drift_seconds):
    current = snapshot(AT + timedelta(minutes=40), ltp=110, oi=110)
    target = current.received_at - timedelta(seconds=horizon_seconds)
    baseline = snapshot(target - timedelta(seconds=drift_seconds), ltp=100, oi=100)

    value = calculate_strike_positioning(
        2, 7, current, [(1, baseline)], horizon_seconds, CONFIG
    )[0]

    assert value.status == "AVAILABLE"
    assert value.baseline_received_at == baseline.received_at
    assert value.actual_elapsed_seconds == horizon_seconds + drift_seconds

def test_does_not_cross_ist_session_date():
    current_at = datetime.fromisoformat("2026-09-10T00:04:00+05:30")
    baseline = snapshot(current_at - timedelta(minutes=5), ltp=100, oi=100)
    current = snapshot(current_at, ltp=110, oi=110)
    assert result(current, [(1, baseline)]).classification == Classification.UNAVAILABLE


def test_requires_same_instrument_key():
    baseline = snapshot(AT - timedelta(minutes=5), key="NSE_FO|OTHER", ltp=100, oi=100)
    assert result(snapshot(), [(1, baseline)]).classification == Classification.UNAVAILABLE


def test_provider_previous_oi_is_not_used_for_observed_change():
    baseline = snapshot(AT - timedelta(minutes=5), ltp=100, oi=100, prev_oi=1)
    value = result(snapshot(ltp=110, oi=120, prev_oi=10000), [(1, baseline)])
    assert value.observed_oi_change == 20
    assert value.observed_oi_change_pct == 20


def test_historical_raw_ltp_fallback_matches_instrument_key():
    baseline = snapshot(AT - timedelta(minutes=5), ltp=None, oi=100, raw_ltp=100)
    current = snapshot(ltp=None, oi=110, raw_ltp=110)
    value = result(current, [(1, baseline)])
    assert value.current_ltp == 110
    assert value.baseline_ltp == 100
    assert value.classification == Classification.LONG_BUILDUP


def test_normalized_ltp_takes_precedence_over_raw_fallback():
    baseline = snapshot(AT - timedelta(minutes=5), ltp=100, oi=100, raw_ltp=1)
    current = snapshot(ltp=110, oi=110, raw_ltp=1)
    assert result(current, [(1, baseline)]).classification == Classification.LONG_BUILDUP


@pytest.mark.parametrize("raw_ltp", [None, 0, -1, "100", True])
def test_invalid_raw_ltp_is_unavailable(raw_ltp):
    baseline = snapshot(AT - timedelta(minutes=5), ltp=None, oi=100, raw_ltp=raw_ltp)
    assert result(snapshot(ltp=None, raw_ltp=110), [(1, baseline)]).status == "UNAVAILABLE"


def test_old_snapshot_without_new_quote_fields_remains_parseable():
    value = snapshot().model_dump(mode="json")
    value["quotes"] = [{"key": "NSE_FO|1", "oi": 100, "prev_oi": 90}]
    parsed = Snapshot.model_validate(value)
    assert parsed.quotes[0].ltp is None
    assert parsed.quotes[0].quote_timestamp is None


def test_fifteen_minute_horizon_is_supported():
    baseline = snapshot(AT - timedelta(minutes=15), ltp=100, oi=100)
    value = calculate_strike_positioning(2, 7, snapshot(), [(1, baseline)], 900, CONFIG)[0]
    assert value.horizon_seconds == 900
    assert value.classification == Classification.LONG_BUILDUP


def test_thirty_minute_horizon_selects_deterministic_baseline():
    current = snapshot(AT + timedelta(minutes=30), ltp=110, oi=110)
    exact = snapshot(AT, ltp=100, oi=100)
    older = snapshot(AT - timedelta(seconds=10), ltp=90, oi=90)

    value = calculate_strike_positioning(3, 7, current, [(1, older), (2, exact)], 1800, CONFIG)[0]

    assert value.horizon_seconds == 1800
    assert value.baseline_received_at == exact.received_at
    assert value.baseline_ltp == 100
    assert value.classification == Classification.LONG_BUILDUP


def test_thirty_minute_newer_than_target_is_rejected():
    current = snapshot(AT + timedelta(minutes=30))
    newer = snapshot(AT + timedelta(seconds=1), ltp=100, oi=100)

    value = calculate_strike_positioning(2, 7, current, [(1, newer)], 1800, CONFIG)[0]

    assert value.status == "UNAVAILABLE"
    assert value.baseline_received_at is None


def test_thirty_minute_without_valid_baseline_is_unavailable():
    current = snapshot(AT + timedelta(minutes=30))

    value = calculate_strike_positioning(2, 7, current, [], 1800, CONFIG)[0]

    assert value.status == "UNAVAILABLE"
    assert value.classification == Classification.UNAVAILABLE


def catalog_at(*strikes, sides=("CE", "PE")):
    return [Contract(key=f"{strike}-{side}", strike=strike, side=side) for strike in strikes for side in sides]


def test_strike_window_uses_sorted_available_nonuniform_strikes():
    catalog = list(reversed(catalog_at(23200, 23250, 23350, 23400, 23500, 23600, 23750)))
    assert select_strike_window(catalog, 23500, 2) == (23350, 23400, 23500, 23600, 23750)


def test_strike_window_zero_wings_returns_only_center():
    assert select_strike_window(catalog_at(100, 200, 300), 200, 0) == (200,)


@pytest.mark.parametrize(
    "center,expected",
    [(100, (100, 200, 300)), (500, (300, 400, 500))],
)
def test_strike_window_keeps_available_boundary_strikes(center, expected):
    assert select_strike_window(catalog_at(100, 200, 300, 400, 500), center, 2) == expected


def test_strike_window_deduplicates_catalog_strikes_and_keeps_single_sides():
    catalog = catalog_at(100, 200, sides=("CE",)) + catalog_at(200, 300, sides=("PE",))
    assert select_strike_window(catalog, 200, 1) == (100, 200, 300)


def test_filtered_calculation_retains_ce_only_and_pe_only_strikes():
    current = snapshot()
    current = current.model_copy(update={
        "catalog": [Contract(key="CE", strike=100, side="CE"), Contract(key="PE", strike=200, side="PE")],
        "quotes": [Quote(key="CE", ltp=110, oi=110), Quote(key="PE", ltp=110, oi=110)],
    })
    baseline = current.model_copy(update={
        "received_at": AT - timedelta(minutes=5), "started_at": AT - timedelta(minutes=5, seconds=1),
        "quotes": [Quote(key="CE", ltp=100, oi=100), Quote(key="PE", ltp=100, oi=100)],
    })
    values = calculate_strike_positioning(2, 7, current, [(1, baseline)], 300, CONFIG, {100, 200})
    assert {(item.strike, item.side) for item in values} == {(100, "CE"), (200, "PE")}


def test_missing_center_and_invalid_wings_are_rejected():
    with pytest.raises(ValueError, match="center_strike"):
        select_strike_window(catalog_at(100, 200), 150, 1)
    with pytest.raises(ValueError, match="wings"):
        select_strike_window(catalog_at(100, 200), 100, -1)

