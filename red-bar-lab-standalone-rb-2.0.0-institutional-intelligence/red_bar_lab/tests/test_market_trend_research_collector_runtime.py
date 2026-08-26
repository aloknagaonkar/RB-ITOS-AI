from datetime import date, datetime, timedelta, timezone

import pytest
import pandas as pd

from red_bar_lab.services.market_trend_research.collector import UpstoxResearchChainCollector
from red_bar_lab.services.market_trend_research.models import MorningReference
from red_bar_lab.services.market_trend_research.policy import (
    MarketTrendResearchPolicy,
    StaticExchangeSessionCalendar,
)
from red_bar_lab.services.market_trend_research.repository import MarketTrendResearchRepository
from red_bar_lab.services.market_trend_research.runtime import (
    LatestValueSlot,
    MarketTrendResearchRuntime,
    ResearchRuntimeConfig,
)

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
REFERENCE_NOW = datetime(2026, 8, 24, 3, 38, 3, tzinfo=timezone.utc)
EXPIRY = date(2026, 8, 25)


class Provider:
    def __init__(self, *, spot=24500.0):
        self.spot = spot
        self.expiry_calls = 0
        self.contract_calls = 0
        self.chain_calls = 0

    def option_expiries(self, instrument_key):
        self.expiry_calls += 1
        assert instrument_key == "NSE_INDEX|Nifty 50"
        return [EXPIRY.isoformat()]

    def option_contracts(self, instrument_key, expiry_date=None):
        self.contract_calls += 1
        assert instrument_key == "NSE_INDEX|Nifty 50"
        rows = []
        for strike in range(23800, 25001, 50):
            for side in ("CE", "PE"):
                rows.append({
                    "expiry": EXPIRY.isoformat(),
                    "instrument_type": side,
                    "instrument_key": f"{side}-{strike}",
                    "strike_price": float(strike),
                })
        return rows

    def option_chain(self, instrument_key, expiry_date):
        self.chain_calls += 1
        assert expiry_date == EXPIRY.isoformat()
        rows = []
        for strike in range(23800, 25001, 50):
            rows.append({
                "expiry": EXPIRY.isoformat(),
                "underlying_spot_price": self.spot,
                "strike_price": float(strike),
                "call_options": {
                    "instrument_key": f"CE-{strike}",
                    "market_data": {"oi": 1000 + strike, "prev_oi": 900 + strike},
                },
                "put_options": {
                    "instrument_key": f"PE-{strike}",
                    "market_data": {"oi": 1200 + strike, "prev_oi": 1100 + strike},
                },
            })
        return rows

    def intraday_candles(self, instrument_key, interval_minutes=1):
        assert instrument_key == "NSE_INDEX|Nifty 50"
        assert interval_minutes == 1
        return pd.DataFrame([{
            "timestamp": pd.Timestamp("2026-08-25T09:15:00+05:30"),
            "open": 24205.0,
            "high": 24238.0,
            "low": 24198.0,
            "close": 24226.0,
            "volume": 0.0,
        }])


class SpotProvider:
    def __init__(self, spot=24272.5, timestamp=REFERENCE_NOW):
        self.value = spot
        self.timestamp = timestamp
        self.calls = 0

    def spot(self, *, underlying, evaluated_at):
        self.calls += 1
        assert underlying == "NIFTY 50"
        return self.value, self.timestamp


def _collector(tmp_path, provider, *, spot_provider=None):
    repository = MarketTrendResearchRepository(tmp_path / "research.db")
    policy = MarketTrendResearchPolicy()
    return UpstoxResearchChainCollector(
        provider=provider,
        repository=repository,
        policy=policy,
        calendar=StaticExchangeSessionCalendar(),
        spot_provider=spot_provider,
    ), repository


def test_reference_capture_uses_spot_and_contract_metadata_not_option_chain(tmp_path):
    provider = Provider()
    spot = SpotProvider()
    collector, repository = _collector(tmp_path, provider, spot_provider=spot)
    reference = collector.capture_reference_once(evaluated_at=REFERENCE_NOW)
    assert reference is not None
    assert reference.reference_spot == 24272.5
    assert reference.reference_timestamp == REFERENCE_NOW
    assert reference.fixed_atm == 24250.0
    assert reference.window_steps == 2
    assert len(reference.fixed_strikes) == 5
    assert spot.calls == 1
    assert provider.contract_calls == 1
    assert provider.chain_calls == 0
    assert repository.load_reference(
        underlying="NIFTY 50", trading_date=REFERENCE_NOW.date()
    )["reference_spot"] == 24272.5
    assert collector.capture_reference_once(evaluated_at=REFERENCE_NOW) is None
    assert spot.calls == 1


def test_reference_recovers_from_first_completed_one_minute_candle(tmp_path):
    provider = Provider()
    collector, repository = _collector(tmp_path, provider)
    evaluated_at = datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc)

    reference = collector.capture_reference_once(evaluated_at=evaluated_at)

    assert reference is not None
    assert reference.reference_spot == 24226.0
    assert reference.fixed_atm == 24250.0
    assert reference.reference_candle_number == 1
    assert reference.reference_candle_start.isoformat() == "2026-08-25T09:15:00+05:30"
    assert reference.reference_candle_end.isoformat() == "2026-08-25T09:16:00+05:30"
    assert reference.reference_candle_close == 24226.0
    assert reference.status == "REFERENCE_FIXED_RECOVERED"
    stored = repository.load_reference(
        underlying="NIFTY 50", trading_date=evaluated_at.astimezone().date()
    )
    assert stored["reference_candle_number"] == 1
    assert provider.contract_calls == 1
    assert provider.chain_calls == 0


@pytest.mark.parametrize(
    ("timestamp", "reason"),
    [
        (REFERENCE_NOW.replace(tzinfo=None), "REFERENCE_TIMESTAMP_NAIVE"),
        (REFERENCE_NOW + timedelta(seconds=1), "REFERENCE_TIMESTAMP_FUTURE"),
        (REFERENCE_NOW - timedelta(seconds=31), "REFERENCE_SPOT_STALE"),
    ],
)
def test_reference_timestamp_validation_fails_closed(tmp_path, timestamp, reason):
    provider = Provider()
    collector, _ = _collector(
        tmp_path,
        provider,
        spot_provider=SpotProvider(timestamp=timestamp),
    )
    with pytest.raises(ValueError, match=reason):
        collector.capture_reference_once(evaluated_at=REFERENCE_NOW)
    assert provider.chain_calls == 0


def test_one_option_chain_request_per_refresh_and_expiry_is_cached(tmp_path):
    provider = Provider()
    collector, _ = _collector(tmp_path, provider)
    first = collector.collect_once(evaluated_at=NOW)
    second = collector.collect_once(evaluated_at=NOW)
    assert provider.chain_calls == 2
    assert provider.expiry_calls == 1
    assert first.retained_contracts == 22
    assert second.retained_contracts == 22


def test_union_retains_fixed_morning_contracts_and_deduplicates(tmp_path):
    provider = Provider(spot=24500.0)
    collector, repository = _collector(tmp_path, provider)
    reference = MorningReference(
        trading_date=NOW.date(),
        underlying="NIFTY 50",
        reference_spot=24000.0,
        reference_timestamp=NOW,
        expiry=EXPIRY,
        strike_interval=50.0,
        fixed_atm=24000.0,
        window_steps=2,
        fixed_strikes=(23900.0, 23950.0, 24000.0, 24050.0, 24100.0),
        source="UPSTOX",
        source_age_seconds=0.0,
        status="REFERENCE_FIXED",
    )
    repository.create_reference(reference)
    result = collector.collect_once(evaluated_at=NOW)
    keys = [cell.instrument_key for cell in result.snapshot.cells]
    assert result.retained_contracts == 32
    assert len(keys) == len(set(keys))
    assert "CE-23900" in keys
    assert "PE-24750" in keys


def test_partial_current_window_fails_closed(tmp_path):
    provider = Provider()
    original = provider.option_chain

    def partial(instrument_key, expiry_date):
        rows = original(instrument_key, expiry_date)
        return [row for row in rows if row["strike_price"] != 24750.0]

    provider.option_chain = partial
    collector, _ = _collector(tmp_path, provider)
    with pytest.raises(ValueError, match="PARTIAL_CONTRACT_WINDOW"):
        collector.collect_once(evaluated_at=NOW)


def test_latest_value_slot_is_bounded_and_replaces_obsolete_work():
    slot = LatestValueSlot[int]()
    slot.put(1)
    slot.put(2)
    slot.put(3)
    assert slot.dropped == 2
    assert slot.take() == 3
    assert slot.take() is None


def test_runtime_is_disabled_by_default_and_cadence_is_bounded():
    config = ResearchRuntimeConfig()
    assert config.enabled is False
    assert config.refresh_seconds == 5.0
    with pytest.raises(ValueError, match="refresh_seconds invalid"):
        ResearchRuntimeConfig(refresh_seconds=0.5)


def test_runtime_stop_is_idempotent(tmp_path):
    runtime = MarketTrendResearchRuntime(
        collector=None,
        service=None,
        repository=MarketTrendResearchRepository(tmp_path / "runtime.db"),
        config=ResearchRuntimeConfig(),
    )
    runtime.stop()
    runtime.stop()
    assert runtime.stop_event.is_set()
