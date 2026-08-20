from datetime import datetime
from zoneinfo import ZoneInfo

from red_bar_lab.execution.option_telemetry import OptionExecutionTelemetryService


IST = ZoneInfo("Asia/Kolkata")


class FakeDatabase:
    def __init__(self, orders):
        self.orders = orders
        self.rows = []

    def read_paper_execution_orders(self, account_id):
        assert account_id == "PAPER"
        return list(self.orders)

    def read_latest_option_execution_telemetry(self, order_id):
        return None

    def insert_option_execution_telemetry(self, row):
        self.rows.append(dict(row))


class FakeMarketData:
    def __init__(self):
        self.quote_calls = 0
        self.chain_calls = 0

    def quote(self, keys):
        self.quote_calls += 1
        return {
            key: {
                "last_price": 125.0,
                "oi": 500000,
                "volume": 250000,
                "iv": 14.0,
                "delta": -0.40,
                "depth": {
                    "buy": [{"price": 124.5}],
                    "sell": [{"price": 125.5}],
                },
            }
            for key in keys
        }

    def option_chain(self, underlying_key, expiry):
        self.chain_calls += 1
        assert underlying_key == "NSE_INDEX|Nifty 50"
        assert expiry == "2026-08-27"
        return [
            {
                "strike_price": 25000,
                "call_options": {
                    "market_data": {"oi": 1000000},
                    "option_greeks": {"delta": 0.44, "iv": 13.1},
                },
                "put_options": {
                    "market_data": {"oi": 1500000},
                    "option_greeks": {
                        "delta": -0.56,
                        "gamma": 0.001,
                        "theta": -8.0,
                        "vega": 4.2,
                        "iv": 15.2,
                    },
                },
            }
        ]


def _order(order_id):
    return {
        "order_id": order_id,
        "execution_strategy_source": "RED_BAR_V2",
        "status": "ACTIVE",
        "exchange": "NFO",
        "tradingsymbol": f"NIFTY26AUG25000PE-{order_id}",
        "underlying_instrument_key": "NSE_INDEX|Nifty 50",
        "option_type": "PE",
        "strike": 25000,
        "expiry": "2026-08-27",
        "entry_price": 100.0,
    }


def test_red_bar_v2_captures_selected_strike_pcr_and_delta():
    database = FakeDatabase([_order("O1")])
    market_data = FakeMarketData()
    service = OptionExecutionTelemetryService(database, account_id="PAPER")

    result = service.capture(
        market_data=market_data,
        now=datetime(2026, 8, 20, 10, 30, tzinfo=IST),
    )

    assert result.captured == 1
    assert result.option_chain_calls == 1
    assert market_data.quote_calls == 1
    assert market_data.chain_calls == 1
    row = database.rows[0]
    assert row["execution_strategy_source"] == "RED_BAR_V2"
    assert row["call_oi_at_strike"] == 1000000
    assert row["put_oi_at_strike"] == 1500000
    assert row["pcr_oi"] == 1.5
    assert row["pcr_source"] == "OPTION_CHAIN_ROW"
    assert row["delta"] == -0.56
    assert row["iv"] == 15.2
    assert row["authority"] == "OBSERVATIONAL_ONLY"


def test_positions_sharing_expiry_reuse_one_chain_fetch():
    database = FakeDatabase([_order("O1"), _order("O2")])
    market_data = FakeMarketData()
    service = OptionExecutionTelemetryService(database, account_id="PAPER")

    result = service.capture(
        market_data=market_data,
        now=datetime(2026, 8, 20, 10, 30, tzinfo=IST),
    )

    assert result.captured == 2
    assert result.option_chain_calls == 1
    assert market_data.chain_calls == 1
    assert market_data.quote_calls == 1


def test_recent_chain_snapshot_is_reused_across_monitor_cycles():
    database = FakeDatabase([_order("O1")])
    market_data = FakeMarketData()
    service = OptionExecutionTelemetryService(
        database, account_id="PAPER", chain_cache_seconds=60
    )

    first = service.capture(
        market_data=market_data,
        now=datetime(2026, 8, 20, 10, 30, 0, tzinfo=IST),
    )
    second = service.capture(
        market_data=market_data,
        now=datetime(2026, 8, 20, 10, 30, 30, tzinfo=IST),
    )

    assert first.option_chain_calls == 1
    assert second.option_chain_calls == 0
    assert second.option_chain_cache_hits == 1
    assert market_data.chain_calls == 1
    assert len(database.rows) == 2
