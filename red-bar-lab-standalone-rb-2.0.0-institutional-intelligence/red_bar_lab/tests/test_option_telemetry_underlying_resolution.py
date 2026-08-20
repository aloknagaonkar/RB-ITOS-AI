from datetime import datetime

from red_bar_lab.execution.option_telemetry import (
    OBSERVATIONAL_AUTHORITY,
    OptionExecutionTelemetryService,
    _underlying_key,
)


class _Database:
    def __init__(self):
        self.telemetry = []

    def read_paper_execution_orders(self, account_id):
        assert account_id == "PAPER"
        return [
            {
                "order_id": "PAPER-V2-1",
                "signal_id": "RBV2-1",
                "execution_strategy_source": "RED_BAR_V2",
                "underlying_name": "NIFTY 50",
                "exchange": "NFO",
                "tradingsymbol": "NIFTY 24200 CE 25 AUG 26",
                "instrument_token": "NSE_FO|TEST",
                "option_type": "CE",
                "strike": 24200.0,
                "expiry": "2026-08-25",
                "status": "ACTIVE",
                "entry_price": 100.0,
                "current_price": 100.0,
            }
        ]

    def read_latest_option_execution_telemetry(self, order_id):
        assert order_id == "PAPER-V2-1"
        return None

    def insert_option_execution_telemetry(self, row):
        self.telemetry.append(dict(row))


class _MarketData:
    def __init__(self):
        self.option_chain_calls = []

    def quote(self, keys):
        assert keys == ["NFO:NIFTY 24200 CE 25 AUG 26"]
        return {
            keys[0]: {
                "last_price": 105.0,
                "volume": 1000,
                "oi": 500,
                "depth": {
                    "buy": [{"price": 104.5}],
                    "sell": [{"price": 105.5}],
                },
            }
        }

    def option_chain(self, instrument_key, expiry):
        self.option_chain_calls.append((instrument_key, expiry))
        return [
            {
                "strike_price": 24200.0,
                "call_options": {
                    "market_data": {"oi": 1000},
                    "option_greeks": {
                        "delta": 0.55,
                        "gamma": 0.01,
                        "theta": -2.0,
                        "vega": 4.0,
                        "iv": 14.0,
                    },
                },
                "put_options": {
                    "market_data": {"oi": 1250},
                    "option_greeks": {},
                },
            }
        ]


def test_explicit_underlying_key_remains_authoritative():
    assert _underlying_key(
        {
            "underlying_instrument_key": "EXPLICIT|KEY",
            "underlying_name": "NIFTY 50",
        }
    ) == "EXPLICIT|KEY"


def test_nifty_name_resolves_to_upstox_index_key():
    assert _underlying_key({"underlying_name": "NIFTY 50"}) == (
        "NSE_INDEX|Nifty 50"
    )
    assert _underlying_key({"underlying_name": " nifty   "}) == (
        "NSE_INDEX|Nifty 50"
    )


def test_v2_telemetry_uses_name_fallback_and_persists_pcr():
    database = _Database()
    market_data = _MarketData()
    service = OptionExecutionTelemetryService(
        database,
        account_id="PAPER",
    )

    result = service.capture(
        market_data=market_data,
        now=datetime.fromisoformat("2026-08-20T14:30:00+05:30"),
    )

    assert result.captured == 1
    assert result.skipped == 0
    assert result.errors == ()
    assert result.option_chain_calls == 1
    assert market_data.option_chain_calls == [
        ("NSE_INDEX|Nifty 50", "2026-08-25")
    ]

    row = database.telemetry[0]
    assert row["pcr_oi"] == 1.25
    assert row["pcr_source"] == "OPTION_CHAIN_ROW"
    assert row["call_oi_at_strike"] == 1000.0
    assert row["put_oi_at_strike"] == 1250.0
    assert row["delta"] == 0.55
    assert row["authority"] == OBSERVATIONAL_AUTHORITY
