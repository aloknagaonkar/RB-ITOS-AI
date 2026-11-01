from datetime import date

from market_lab.domain import (
    HistoricalPCRObservation,
    HistoricalPCRPanelResult,
)
from market_lab.historical_cache import HistoricalSessionCache, HistoricalSessionCacheKey
from market_lab.historical_research import HistoricalResearchSession


def _panel(mode: str, atm: float | None = 24000.0):
    return HistoricalPCRPanelResult(
        mode=mode,
        atm=atm if mode != "full_reconstructed" else None,
        strikes=[23950.0, 24000.0, 24050.0],
        expected_contracts=6,
        received_oi_contracts=6,
        call_oi=100,
        put_oi=110,
        pcr=1.1,
        status="AVAILABLE",
    )


def _session():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ts = datetime(2026, 9, 8, 9, 20, tzinfo=ZoneInfo("Asia/Kolkata"))
    observation = HistoricalPCRObservation(
        timestamp=ts,
        session_date=date(2026, 9, 8),
        underlying="NSE_INDEX|Nifty 50",
        expiry=date(2026, 9, 8),
        spot=23690.5,
        moving_atm=23700.0,
        strike_results=[],
        moving_panel=_panel("moving", 23700.0),
        full_reconstructed_panel=_panel("full_reconstructed", None),
        fixed_panel=_panel("fixed", 23700.0),
    )
    return HistoricalResearchSession(
        status="AVAILABLE",
        underlying="NSE_INDEX|Nifty 50",
        session_date=date(2026, 9, 8),
        expiry=date(2026, 9, 8),
        wings=5,
        strike_interval=50,
        observations=[observation],
        issues=[],
    )


def test_cache_round_trip(tmp_path):
    cache = HistoricalSessionCache(tmp_path)
    key = HistoricalSessionCacheKey(
        underlying="NSE_INDEX|Nifty 50",
        session_date=date(2026, 9, 8),
        expiry=date(2026, 9, 8),
        wings=5,
    )
    session = _session()
    path = cache.store(key, session)
    assert path.exists()
    assert cache.load(key) == session


def test_cache_key_changes_with_semantics(tmp_path):
    cache = HistoricalSessionCache(tmp_path)
    base = HistoricalSessionCacheKey(
        underlying="NSE_INDEX|Nifty 50",
        session_date=date(2026, 9, 8),
        expiry=date(2026, 9, 8),
        wings=5,
    )
    other = HistoricalSessionCacheKey(
        underlying="NSE_INDEX|Nifty 50",
        session_date=date(2026, 9, 8),
        expiry=date(2026, 9, 8),
        wings=6,
    )
    assert cache.path_for(base) != cache.path_for(other)


def test_unavailable_session_is_not_cached(tmp_path):
    cache = HistoricalSessionCache(tmp_path)
    key = HistoricalSessionCacheKey(
        underlying="NSE_INDEX|Nifty 50",
        session_date=date(2026, 9, 8),
        expiry=date(2026, 9, 8),
        wings=5,
    )
    unavailable = HistoricalResearchSession(
        status="UNAVAILABLE",
        underlying=key.underlying,
        session_date=key.session_date,
        expiry=key.expiry,
        wings=key.wings,
        strike_interval=50,
        observations=[],
        issues=["provider_error"],
    )
    try:
        cache.store(key, unavailable)
    except ValueError:
        pass
    else:
        raise AssertionError("unavailable session must not be cached")
    assert cache.load(key) is None


def test_malformed_cache_is_treated_as_miss(tmp_path):
    cache = HistoricalSessionCache(tmp_path)
    key = HistoricalSessionCacheKey(
        underlying="NSE_INDEX|Nifty 50",
        session_date=date(2026, 9, 8),
        expiry=date(2026, 9, 8),
        wings=5,
    )
    cache.root.mkdir(parents=True, exist_ok=True)
    cache.path_for(key).write_text('{"cache_schema_version":999}', encoding="utf-8")
    assert cache.load(key) is None
