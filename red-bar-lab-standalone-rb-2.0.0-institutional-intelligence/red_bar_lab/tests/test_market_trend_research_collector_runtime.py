from datetime import date, datetime, timezone

import pytest

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
EXPIRY = date(2026, 8, 25)


class Provider:
    def __init__(self, *, spot=24500.0):
        self.spot = spot
        self.expiry_calls = 0
        self.chain_calls = 0

    def option_expiries(self, instrument_key):
        self.expiry_calls += 1
        assert instrument_key == "NSE_INDEX|Nifty 50"
        return [EXPIRY.isoformat()]

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


def _collector(tmp_path, provider):
    repository = MarketTrendResearchRepository(tmp_path / "research.db")
    policy = MarketTrendResearchPolicy()
    return UpstoxResearchChainCollector(
        provider=provider,
        repository=repository,
        policy=policy,
        calendar=StaticExchangeSessionCalendar(),
    ), repository


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
