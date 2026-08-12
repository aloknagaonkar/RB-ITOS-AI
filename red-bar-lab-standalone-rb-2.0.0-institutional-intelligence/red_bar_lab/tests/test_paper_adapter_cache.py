from datetime import date

from red_bar_lab.market.paper_adapter import UpstoxPaperMarketAdapter


class FakeIntelligence:
    def __init__(self, provider):
        self.provider = provider


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def intraday_candles(self, instrument_key, interval_minutes=1):
        self.calls += 1
        return [{"timestamp": "2026-08-10T10:00:00+05:30", "close": 100.0}]


def test_paper_adapter_reuses_short_lived_candle_cache():
    provider = FakeProvider()
    adapter = UpstoxPaperMarketAdapter(
        FakeIntelligence(provider),
        "NIFTY 50",
        "NSE_INDEX|Nifty 50",
    )
    adapter._token_to_key[123] = "NSE_FO|123"

    first = adapter.historical_candles(
        123,
        "minute",
        date.today().isoformat(),
        date.today().isoformat(),
    )
    second = adapter.historical_candles(
        123,
        "minute",
        date.today().isoformat(),
        date.today().isoformat(),
    )

    assert first == second
    assert provider.calls == 1
