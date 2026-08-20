import sqlite3
from datetime import datetime

from red_bar_lab.execution.option_telemetry import (
    OptionExecutionTelemetryService,
    _ensure_strike_oi_columns,
)


class _Database:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE option_execution_telemetry (
                    telemetry_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    observed_timestamp TEXT NOT NULL,
                    pcr_oi REAL,
                    pcr_source TEXT
                )
                """
            )
            conn.commit()

    def initialize(self):
        return None

    def read_paper_execution_orders(self, account_id):
        assert account_id == "PAPER"
        return [
            {
                "order_id": "PAPER-V2-STRIKE-OI",
                "signal_id": "RBV2-STRIKE-OI",
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
        assert order_id == "PAPER-V2-STRIKE-OI"
        return None

    def insert_option_execution_telemetry(self, row):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO option_execution_telemetry(
                    telemetry_id, order_id, observed_timestamp,
                    pcr_oi, pcr_source
                ) VALUES(?,?,?,?,?)
                """,
                (
                    row["telemetry_id"],
                    row["order_id"],
                    row["observed_timestamp"],
                    row.get("pcr_oi"),
                    row.get("pcr_source"),
                ),
            )
            conn.commit()


class _MarketData:
    def quote(self, keys):
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
        assert instrument_key == "NSE_INDEX|Nifty 50"
        assert expiry == "2026-08-25"
        return [
            {
                "strike_price": 24200.0,
                "call_options": {
                    "market_data": {"oi": 1000},
                    "option_greeks": {"delta": 0.55},
                },
                "put_options": {
                    "market_data": {"oi": 1250},
                    "option_greeks": {},
                },
            }
        ]


def test_schema_extension_is_additive_and_idempotent(tmp_path):
    database = _Database(tmp_path / "telemetry.db")

    assert _ensure_strike_oi_columns(database) is True
    assert _ensure_strike_oi_columns(database) is False

    with sqlite3.connect(database.path) as conn:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(option_execution_telemetry)"
            )
        }

    assert "call_oi_at_strike" in columns
    assert "put_oi_at_strike" in columns


def test_capture_persists_exact_selected_strike_oi(tmp_path):
    database = _Database(tmp_path / "telemetry.db")
    service = OptionExecutionTelemetryService(
        database,
        account_id="PAPER",
    )

    result = service.capture(
        market_data=_MarketData(),
        now=datetime.fromisoformat("2026-08-20T14:30:00+05:30"),
    )

    assert result.captured == 1
    assert result.errors == ()

    with sqlite3.connect(database.path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT pcr_oi, pcr_source,
                   call_oi_at_strike, put_oi_at_strike
            FROM option_execution_telemetry
            WHERE order_id='PAPER-V2-STRIKE-OI'
            """
        ).fetchone()

    assert row["pcr_oi"] == 1.25
    assert row["pcr_source"] == "OPTION_CHAIN_ROW"
    assert row["call_oi_at_strike"] == 1000.0
    assert row["put_oi_at_strike"] == 1250.0
