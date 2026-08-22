from datetime import date, datetime, timedelta, timezone

import pandas as pd

from red_bar_lab.domain.red_bar_v2 import ContextStatus
from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    build_red_bar_v2_futures_snapshot,
)
from red_bar_lab.services.red_bar_v2_canonical import (
    LegacyV2MarketMetadata,
    PersistenceOutcome,
    RedBarV2CanonicalPersistenceService,
    SQLiteRedBarV2CanonicalRepository,
    compare_legacy_to_canonical,
    resolve_red_bar_v2_canonical,
)
from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
    replay_red_bar_v2_day_with_futures_vwap,
)

IST = timezone(timedelta(hours=5, minutes=30))
TRADING_DATE = date(2026, 8, 24)
UNDERLYING = "NSE_INDEX|Nifty 50"
FUTURES = "NSE_FO|NIFTY-FUT"


def _candles(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range(
        datetime(2026, 8, 24, 9, 15, tzinfo=IST),
        periods=len(closes),
        freq="1min",
    )
    opens = [closes[0] - 0.2, *closes[:-1]]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 0.4 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 0.4 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": volumes,
        },
        index=timestamps,
    )


def _market_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    index_closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    index_closes += [103.0, 101.0, 99.0, 97.0, 95.0]
    index_closes += [96.0 + index * 0.9 for index in range(40)]

    futures_closes = [200.0 + index * 0.6 for index in range(50)]
    index_volumes = [10.0 + index for index in range(50)]
    futures_volumes = [1000.0 + index * 10.0 for index in range(50)]
    return (
        _candles(index_closes, index_volumes),
        _candles(futures_closes, futures_volumes),
    )


def _parse_timestamp(value: object) -> datetime:
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    return parsed


def test_real_futures_replay_emits_and_persists_exact_canonical_event_time_evidence(tmp_path):
    index_candles, futures_candles = _market_frames()
    replay, health = replay_red_bar_v2_day_with_futures_vwap(
        index_candles,
        futures_candles,
        instrument_key=UNDERLYING,
        vwap_instrument_key=FUTURES,
    )

    event = next(
        item
        for item in replay.events
        if item.event_type == "CANDIDATE_ADMISSION" and item.candidate_allowed is True
    )
    details = event.details

    context_timestamp = _parse_timestamp(details["index_context_timestamp"])
    source_timestamp = _parse_timestamp(details["futures_source_timestamp"])
    timeframe = str(details["evaluation_timeframe"])
    assert timeframe == "1m"

    snapshot, decision_health = build_red_bar_v2_futures_snapshot(
        index_candles,
        futures_candles,
        instrument_key=UNDERLYING,
        vwap_instrument_key=FUTURES,
        timeframe="1M",
        evaluation_time=context_timestamp + timedelta(minutes=1),
        expected_timestamp=context_timestamp,
    )
    assert snapshot is not None
    assert decision_health.status == "READY"

    assert details["underlying_instrument_key"] == UNDERLYING
    assert details["futures_instrument_key"] == FUTURES
    assert details["index_close"] == snapshot.candle_close
    assert details["futures_comparison_price"] == snapshot.vwap_comparison_price
    assert details["futures_vwap"] == snapshot.vwap_value
    assert details["futures_volume"] == snapshot.vwap_source_volume
    assert source_timestamp == snapshot.vwap_source_timestamp
    assert details["futures_volume"] != snapshot.candle_volume

    reference_timestamp = _parse_timestamp(details["reference_timestamp"])
    metadata = LegacyV2MarketMetadata(
        strategy_version="2.0.0",
        trading_date=TRADING_DATE,
        evaluated_at=event.timestamp,
        source_name="FUTURES_AWARE_REPLAY",
        source_version="1",
        context_status=ContextStatus.FRESH,
        maximum_age_seconds=120,
        latest_index_1m=context_timestamp,
        latest_index_5m=context_timestamp,
        latest_futures_1m=source_timestamp,
        latest_futures_5m=source_timestamp,
        underlying_instrument_key=UNDERLYING,
        futures_instrument_key=FUTURES,
        futures_expiry=date(2026, 8, 27),
        futures_volume_available=True,
        futures_vwap_available=True,
        reason_code="READY",
        reason="Authoritative futures replay evidence is aligned",
        reference_id=str(details["reference_id"]),
        reference_timestamp=reference_timestamp,
        reference_high=float(details["reference_high"]),
        reference_low=float(details["reference_low"]),
        reference_midpoint=float(details["reference_midpoint"]),
        reference_source=str(details["reference_source"]),
    )

    resolution = resolve_red_bar_v2_canonical(
        replay=replay,
        health=health,
        replay_event=event,
        market_metadata=metadata,
        evidence=None,
        source_replay_id="FUTURES-REPLAY-INTEGRATION",
        resolved_at=event.timestamp,
    )

    assert resolution.section_3 is not None
    assert resolution.section_3.schema_version == "1.1"
    assert resolution.section_3.instrument_key == UNDERLYING
    assert resolution.section_3.decision.futures_vwap.instrument_key == FUTURES
    assert resolution.section_3.decision.futures_vwap.comparison_price == snapshot.vwap_comparison_price
    assert resolution.section_3.decision.futures_vwap.volume == snapshot.vwap_source_volume

    parity = compare_legacy_to_canonical(
        legacy_event=event,
        canonical_decision=resolution.section_2,
        legacy_timeframe=timeframe,
    )
    assert parity.matches is True

    path = tmp_path / "red_bar.db"
    repository = SQLiteRedBarV2CanonicalRepository(path)
    persisted = RedBarV2CanonicalPersistenceService(repository).persist(
        resolution=resolution,
        parity=parity,
        instrument_key=UNDERLYING,
    )
    assert persisted.outcome is PersistenceOutcome.INSERTED

    restarted = SQLiteRedBarV2CanonicalRepository(path)
    stored = restarted.get_resolution(persisted.resolution_id)
    assert stored is not None
    assert stored.section_1 == resolution.section_1
    assert stored.section_2 == resolution.section_2
    assert stored.section_3 == resolution.section_3
    assert stored.parity == parity
