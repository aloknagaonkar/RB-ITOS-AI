from datetime import date, datetime, timedelta

from market_lab.domain import IST
from market_lab.hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set
from market_lab.hilega_milega_option_shadow_lifecycle_v1 import (
    HilegaMilegaOptionShadowLifecycleV1,
    SELECTION_POLICY,
)
from market_lab.live_option_minute_source_v1 import CompletedOptionMinute


def _candidate_set():
    expiry = date(2026, 9, 29)
    contracts = [
        {
            "expiry": expiry.isoformat(),
            "strike_price": strike,
            "instrument_type": "CE",
            "instrument_key": f"CE-{strike}",
        }
        for strike in [23300, 23350, 23400, 23450, 23500]
    ]
    return build_bullish_ce_candidate_set(
        signal_spot=23393.25,
        expiry=expiry,
        contracts=contracts,
        strike_step=50,
        wings=2,
    )


def _minute_source(start: datetime, count: int = 10):
    rows = {}
    for strike in [23300, 23350, 23400, 23450, 23500]:
        key = f"CE-{strike}"
        base = 100.0 + (23400 - strike) / 10.0
        rows[key] = [
            CompletedOptionMinute(
                key,
                start + timedelta(minutes=i),
                base + i,
                base + i + 2,
                base + i - 1,
                base + i + 1,
                100 + i,
            )
            for i in range(count)
        ]
    return lambda key: list(rows[key])


def test_shadow_lifecycle_tracks_all_atm_plus_minus_2_and_never_orders():
    signal_bar = datetime(2026, 9, 23, 10, 15, tzinfo=IST)
    boundary = datetime(2026, 9, 23, 10, 20, tzinfo=IST)
    source = _minute_source(boundary)
    tracker = HilegaMilegaOptionShadowLifecycleV1()

    started = tracker.start(
        signal_bar_ts=signal_bar,
        signal_spot=23393.25,
        source="PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21",
        candidate_set=_candidate_set(),
        option_minutes=source,
    )
    assert started.status == "ACTIVE"
    assert started.selection_policy == SELECTION_POLICY
    assert [x.relation_to_atm for x in started.legs] == [-2, -1, 0, 1, 2]
    assert len(started.shadow_selected_instrument_keys) == 5
    payload = started.payload()
    assert payload["order_created"] is False
    assert payload["quantity"] is None
    assert payload["execution_enabled"] is False
    assert payload["paper_order_enabled"] is False

    updated = tracker.update(
        through_completed_minute=boundary + timedelta(minutes=2),
        option_minutes=source,
    )
    assert updated is not None and updated.status == "ACTIVE"
    assert updated.latest_completed_minute.endswith("10:22:00+05:30")
    for leg in updated.legs:
        assert leg.latest_close is not None
        assert leg.current_points == 3.0
        assert leg.mfe_points == 4.0
        assert leg.mae_points == -1.0

    closed = tracker.close(
        exit_boundary=boundary + timedelta(minutes=5),
        exit_reason="RSI_CROSS_BELOW_WMA21",
        option_minutes=source,
    )
    assert closed is not None and closed.status == "CLOSED"
    assert closed.active is False
    for leg in closed.legs:
        assert leg.exit_open is not None
        assert leg.realized_points == 5.0


def test_shadow_lifecycle_fails_closed_if_any_exact_entry_minute_missing():
    signal_bar = datetime(2026, 9, 23, 10, 15, tzinfo=IST)
    boundary = datetime(2026, 9, 23, 10, 20, tzinfo=IST)
    base_source = _minute_source(boundary)

    def missing_one(key):
        rows = base_source(key)
        if key == "CE-23500":
            return rows[1:]
        return rows

    tracker = HilegaMilegaOptionShadowLifecycleV1()
    started = tracker.start(
        signal_bar_ts=signal_bar,
        signal_spot=23393.25,
        source="PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21",
        candidate_set=_candidate_set(),
        option_minutes=missing_one,
    )
    assert started.status == "INCOMPLETE"
    assert started.active is False
    assert "CE-23500:MISSING_ENTRY_MINUTE" in (started.issue or "")
    assert started.payload()["order_created"] is False
