"""Rule locks for Stage 1 (the Red Bar reference) and Stage 2 (market context).

Stage 1 answers one question -- where is the line? -- from the index alone: the
first completed red 5-minute candle at or after 09:20, with the 09:15-09:20 bar
always ignored, and midpoint = (high + low) / 2, frozen for the rest of the
session. The red bar's own position against the futures VWAP is recorded for the
audit trail and gates nothing.

Stage 2 answers a different question -- is the context usable, and where does
price sit? -- and deliberately emits no direction. It compares the FUTURES close
to the FUTURES VWAP. Comparing the index close to the futures VWAP would be a
constant, not a gate: measured pre-open spot-versus-futures basis ran +76 to
+150 points across 2026-08-26 to 2026-09-02 (mean ~118), always positive, which
is 2-4x the ~40-point red bar range the rule is trying to measure. Every candle
would read BELOW, so "bearish aligned" would be true 100% of the time and
"bullish aligned" never. A fixed offset cannot repair it either -- the basis
moved 76 -> 150 inside a single week.
"""

from collections.abc import Sequence
from dataclasses import fields, replace
from datetime import datetime

import pandas as pd
import pytest

from red_bar_lab.execution.red_bar_v2_admission_policy import (
    AdmissionCode,
    evaluate_candidate_admission,
)
from red_bar_lab.execution.trade_state_observer import (
    TradeLifecycleState,
    TradeStateSnapshot,
)
from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    RedBarV2FuturesSnapshot,
    build_red_bar_v2_futures_snapshot,
)
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2Reference,
    annotate_reference_vwap_position,
    build_red_bar_v2_reference,
)
from red_bar_lab.strategy.red_bar_v2_futures import (
    evaluate_initial_direction_futures,
)

IST = "Asia/Kolkata"
TRADING_DATE = "2026-08-18"
INSTRUMENT = "NSE_INDEX|Nifty 50"
FUTURES_INSTRUMENT = "NSE_FO|58072"

def _ist(hour: int, minute: int) -> pd.Timestamp:
    return pd.Timestamp(f"{TRADING_DATE} {hour:02d}:{minute:02d}", tz=IST)


Bar = tuple[float, float, float, float]


def _index_frame(bars: Sequence[Bar]) -> pd.DataFrame:
    """Expand 5-minute (open, high, low, close) bars into 1-minute candles.

    The aggregator takes the first open, the max high, the min low and the last
    close, so carrying the high and low on every row and the close on only the
    fifth reproduces each bar exactly. Volume stays 0.0 because NIFTY 50 is a
    computed index and publishes none -- 583 rows of measured 1-minute index
    volume contained zero positive values.
    """
    rows: list[dict[str, object]] = []
    for position, (bar_open, bar_high, bar_low, bar_close) in enumerate(bars):
        for minute in range(5):
            rows.append(
                {
                    "timestamp": _ist(9, 15) + pd.Timedelta(minutes=position * 5 + minute),
                    "open": bar_open,
                    "high": bar_high,
                    "low": bar_low,
                    "close": bar_close if minute == 4 else bar_open,
                    "volume": 0.0,
                }
            )
    return pd.DataFrame(rows)


def _minute_frame(prices: Sequence[float], *, volume: float = 1000.0) -> pd.DataFrame:
    """One-minute candles from 09:15 with a flat price per minute.

    high == low == close keeps the typical price equal to the quoted price, so
    the session VWAP is a plain volume-weighted mean and every expected value
    below can be written out by hand.
    """
    timestamps = pd.date_range(
        f"{TRADING_DATE} 09:15", periods=len(prices), freq="1min", tz=IST
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": list(prices),
            "high": list(prices),
            "low": list(prices),
            "close": list(prices),
            "volume": [volume] * len(prices),
        }
    )

def _reference(
    bars: Sequence[Bar],
    *,
    at: pd.Timestamp | None = None,
) -> RedBarV2Reference | None:
    return build_red_bar_v2_reference(
        _index_frame(bars),
        instrument_key=INSTRUMENT,
        evaluation_time=at if at is not None else _ist(9, 15)
        + pd.Timedelta(minutes=5 * len(bars)),
    )


def _snapshot(
    *,
    rsi_state: str | None,
    index_close: float = 110.0,
    futures_price: float = 210.0,
    vwap: float = 205.0,
    rsi_value: float | None = None,
) -> RedBarV2FuturesSnapshot:
    stamp = _ist(10, 0).to_pydatetime()
    return RedBarV2FuturesSnapshot(
        instrument_key=INSTRUMENT,
        trading_date=TRADING_DATE,
        timeframe="1M",
        candle_timestamp=stamp,
        candle_open=index_close - 1.0,
        candle_high=index_close + 1.0,
        candle_low=index_close - 2.0,
        candle_close=index_close,
        candle_volume=0.0,
        rsi_period=14,
        rsi_value=rsi_value,
        vwap_value=vwap,
        price_vs_vwap="ABOVE" if futures_price > vwap else "BELOW",
        rsi_state=rsi_state,
        source="RED_BAR_V2_INDEX_RSI_FUTURES_VWAP_V1",
        data_quality="VALID",
        fresh=True,
        vwap_comparison_price=futures_price,
        vwap_source_instrument_key=FUTURES_INSTRUMENT,
        vwap_source_timestamp=stamp,
        vwap_source_volume=150000.0,
    )


def _flat_trade_state() -> TradeStateSnapshot:
    return TradeStateSnapshot(
        lifecycle_state=TradeLifecycleState.FLAT,
        active_trade=None,
        latest_executed_trade=None,
        previous_trade_closed=True,
        has_pending_trade=False,
        active_trade_count=0,
        pending_trade_count=0,
        conflict_reason=None,
    )

def test_the_opening_five_minute_bar_is_ignored_even_when_it_is_red() -> None:
    """09:15-09:20 never qualifies, whatever colour it prints."""
    reference = _reference(
        [
            (110.0, 111.0, 104.0, 105.0),  # 09:20 red -- opening bar, ignored
            (105.0, 112.0, 104.0, 111.0),  # 09:20 green
            (111.0, 112.0, 101.0, 103.0),  # 09:25 red -- the reference
        ]
    )

    assert reference is not None
    assert reference.reference_timestamp == _ist(9, 25).to_pydatetime()
    assert reference.reference_high == 112.0
    assert reference.reference_low == 101.0


def test_the_first_red_bar_at_or_after_0920_becomes_the_reference() -> None:
    reference = _reference(
        [
            (100.0, 106.0, 99.0, 105.0),  # 09:15 green
            (105.0, 107.0, 95.0, 96.0),  # 09:20 red -- the reference
            (96.0, 99.0, 90.0, 91.0),  # 09:25 red, arrives too late to matter
        ]
    )

    assert reference is not None
    assert reference.reference_timestamp == _ist(9, 20).to_pydatetime()
    assert reference.level_type == "NEXT_RED_CANDLE"


def test_the_midpoint_is_the_arithmetic_mean_of_the_reference_high_and_low() -> None:
    reference = _reference(
        [
            (100.0, 101.0, 99.0, 100.5),  # 09:15 green
            (104.0, 105.0, 95.0, 96.0),  # 09:20 red
        ]
    )

    assert reference is not None
    assert reference.midpoint == pytest.approx(100.0)
    assert reference.midpoint == pytest.approx(
        (reference.reference_high + reference.reference_low) / 2.0
    )
    assert reference.interval_minutes == 5

def test_the_reference_is_frozen_once_set_even_if_a_redder_bar_follows() -> None:
    """The line is drawn once. A larger, redder bar later must not move it."""
    bars = [
        (100.0, 101.0, 99.0, 100.5),  # 09:15 green
        (104.0, 105.0, 95.0, 96.0),  # 09:20 red -- the reference, midpoint 100
        (96.0, 130.0, 60.0, 61.0),  # 09:25 far redder and far wider
    ]

    early = _reference(bars, at=_ist(9, 25))
    late = _reference(bars, at=_ist(9, 40))

    assert early is not None and late is not None
    assert early.reference_timestamp == _ist(9, 20).to_pydatetime()
    assert late.reference_timestamp == early.reference_timestamp
    assert late.midpoint == pytest.approx(100.0)


def test_the_reference_is_built_from_the_index_alone() -> None:
    """No futures argument exists, so no futures outage can suppress Stage 1."""
    reference = _reference(
        [
            (100.0, 101.0, 99.0, 100.5),
            (104.0, 105.0, 95.0, 96.0),
        ]
    )

    assert reference is not None
    assert reference.reference_vwap_value is None
    assert reference.reference_vwap_comparison_price is None
    assert reference.reference_vwap_position is None
    assert reference.reference_vwap_timestamp is None


@pytest.mark.parametrize(
    "futures",
    [
        pd.DataFrame(),
        _minute_frame([200.0] * 10, volume=0.0),
    ],
    ids=["no_futures_rows", "zero_volume_futures"],
)
def test_unusable_futures_data_leaves_the_reference_untouched(futures) -> None:
    """A missing or volume-less futures feed must annotate nothing, not raise."""
    reference = _reference(
        [
            (100.0, 101.0, 99.0, 100.5),
            (104.0, 105.0, 95.0, 96.0),
        ]
    )
    assert reference is not None

    assert annotate_reference_vwap_position(reference, futures) == reference

def test_the_informational_note_describes_the_red_bar_not_the_present() -> None:
    """The VWAP is read as of the red bar's own close, so nothing leaks in.

    The 09:20 reference closes at 09:25. Futures traded flat at 200 through
    09:19 and at 206 through 09:24, so the VWAP at the red bar close is exactly
    203 and the futures price sat ABOVE it. The frame continues to 09:29 at 100
    -- had the annotation read the latest candle instead, it would report a VWAP
    near 168.7 with price BELOW.
    """
    reference = _reference(
        [
            (100.0, 101.0, 99.0, 100.5),
            (104.0, 105.0, 95.0, 96.0),
        ]
    )
    assert reference is not None

    annotated = annotate_reference_vwap_position(
        reference,
        _minute_frame([200.0] * 5 + [206.0] * 5 + [100.0] * 5),
    )

    assert annotated.reference_vwap_value == pytest.approx(203.0)
    assert annotated.reference_vwap_comparison_price == pytest.approx(206.0)
    assert annotated.reference_vwap_position == "ABOVE"
    assert annotated.reference_vwap_timestamp == _ist(9, 24).to_pydatetime()
    # The gating fields are untouched.
    assert annotated.midpoint == reference.midpoint
    assert annotated.reference_high == reference.reference_high
    assert annotated.reference_low == reference.reference_low


@pytest.mark.parametrize("position", ["ABOVE", "BELOW", "AT", None])
def test_the_informational_note_moves_no_gate(position) -> None:
    """Stage 1's VWAP note must not reach the direction decision at all."""
    reference = _reference(
        [
            (100.0, 101.0, 99.0, 100.5),
            (104.0, 105.0, 95.0, 96.0),
        ]
    )
    assert reference is not None
    snapshot = _snapshot(rsi_state=None)

    noted = replace(
        reference,
        reference_vwap_value=203.0,
        reference_vwap_comparison_price=206.0,
        reference_vwap_position=position,
        reference_vwap_timestamp=_ist(9, 24).to_pydatetime(),
    )

    assert evaluate_initial_direction_futures(
        noted, snapshot
    ) == evaluate_initial_direction_futures(reference, snapshot)

def test_the_stage_two_snapshot_exposes_no_directional_verdict() -> None:
    """Stage 2 reports where price is. Deciding direction is Stage 3's job."""
    names = {field.name for field in fields(RedBarV2FuturesSnapshot)}

    assert not names & {
        "bullish_context",
        "bearish_context",
        "bullish_aligned",
        "bearish_aligned",
        "direction",
    }
    assert "rsi_state" in names
    assert "price_vs_vwap" in names


@pytest.mark.parametrize(
    "rsi_state",
    ["BULLISH", "BEARISH", "NEUTRAL", None],
)
def test_rsi_state_is_informational_and_never_gates_admission(rsi_state) -> None:
    """Identical geometry must reach an identical verdict at any RSI reading."""
    reference = _reference(
        [
            (100.0, 101.0, 99.0, 100.5),
            (104.0, 105.0, 95.0, 96.0),
        ]
    )
    assert reference is not None

    decision = evaluate_initial_direction_futures(
        reference,
        _snapshot(rsi_state=rsi_state),
    )
    admission = evaluate_candidate_admission(decision, _flat_trade_state())

    assert decision.direction == "BULLISH"
    assert decision.redbar_vwap_aligned is True
    assert admission.candidate_allowed is True
    assert admission.admission_code == AdmissionCode.INITIAL_BULLISH_ALIGNMENT

def _built_snapshot() -> RedBarV2FuturesSnapshot:
    """A real Stage 2 snapshot with a lifelike +118 point futures basis."""
    index = _minute_frame([100.0 + step for step in range(20)], volume=0.0)
    futures = _minute_frame([218.0 + step for step in range(20)])

    snapshot, health = build_red_bar_v2_futures_snapshot(
        index,
        futures,
        instrument_key=INSTRUMENT,
        vwap_instrument_key=FUTURES_INSTRUMENT,
        timeframe="1M",
        evaluation_time=_ist(9, 35),
    )
    assert snapshot is not None
    assert health.status == "READY"
    return snapshot


def test_the_vwap_comparison_stays_futures_against_futures() -> None:
    """Only the futures side shares the basis with the futures VWAP.

    Prices rise linearly 218 -> 237, so the futures VWAP is the plain mean,
    227.5, and the last futures print sits above it. The index close for the
    same minute is 119. Both comparisons are computed below and they disagree:
    the futures reads ABOVE its own VWAP while the index reads BELOW it. The
    gate must use the futures reading -- the index one is measuring the basis,
    not the market.
    """
    snapshot = _built_snapshot()

    assert snapshot.vwap_value == pytest.approx(227.5)
    assert snapshot.vwap_comparison_price == pytest.approx(237.0)
    assert snapshot.candle_close == pytest.approx(119.0)

    assert snapshot.vwap_comparison_price > snapshot.vwap_value
    assert snapshot.candle_close < snapshot.vwap_value
    assert snapshot.price_vs_vwap == "ABOVE"
    assert snapshot.vwap_source_instrument_key == FUTURES_INSTRUMENT
    assert snapshot.instrument_key == INSTRUMENT


def test_the_index_side_of_stage_two_carries_no_volume() -> None:
    """The index contributes price and RSI only; its VWAP is not computable."""
    snapshot = _built_snapshot()

    assert snapshot.candle_volume == 0.0
    assert snapshot.vwap_source_volume > 0.0
    assert snapshot.vwap_source_type == "NIFTY_FUTURES"
    assert isinstance(snapshot.vwap_source_timestamp, datetime)
