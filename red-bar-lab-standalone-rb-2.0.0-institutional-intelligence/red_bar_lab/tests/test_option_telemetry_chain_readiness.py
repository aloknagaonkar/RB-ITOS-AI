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
                "order_id": "PAPER-V2-CHAIN",
                "signal_id": "RBV2-CHAIN",
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
        assert order_id == "PAPER-V2-CHAIN"
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
    def __init__(self, rows):
        self.rows = rows

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
        return self.rows


def _capture(database, rows):
    service = OptionExecutionTelemetryService(database, account_id="PAPER")
    return service.capture(
        market_data=_MarketData(rows),
        now=datetime.fromisoformat("2026-08-20T14:30:00+05:30"),
    )


def _read(database):
    with sqlite3.connect(database.path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT pcr_oi, pcr_source,
                   call_oi_at_strike, put_oi_at_strike,
                   chain_readiness_status, chain_readiness_reason
            FROM option_execution_telemetry
            WHERE order_id='PAPER-V2-CHAIN'
            """
        ).fetchone()


def test_schema_extension_adds_chain_readiness_columns(tmp_path):
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

    assert "chain_readiness_status" in columns
    assert "chain_readiness_reason" in columns


def test_ready_chain_persists_readiness_and_pcr(tmp_path):
    database = _Database(tmp_path / "telemetry.db")
    rows = [
        {
            "strike_price": 24200.0,
            "call_options": {"market_data": {"oi": 1000}},
            "put_options": {"market_data": {"oi": 1250}},
        }
    ]

    result = _capture(database, rows)
    row = _read(database)

    assert result.captured == 1
    assert result.errors == ()
    assert row["chain_readiness_status"] == "READY"
    assert "complete CE/PE OI data" in row["chain_readiness_reason"]
    assert row["pcr_oi"] == 1.25
    assert row["pcr_source"] == "OPTION_CHAIN_ROW"
    assert row["call_oi_at_strike"] == 1000.0
    assert row["put_oi_at_strike"] == 1250.0


def test_degraded_chain_persists_reason_and_suppresses_pcr(tmp_path):
    database = _Database(tmp_path / "telemetry.db")
    rows = [
        {
            "strike_price": 24200.0,
            "pcr": 1.75,
            "call_options": {"market_data": {"oi": 1000}},
        }
    ]

    result = _capture(database, rows)
    row = _read(database)

    assert result.captured == 1
    assert result.errors == ()
    assert row["chain_readiness_status"] == "MISSING_PUT_LEG"
    assert "Put leg is absent" in row["chain_readiness_reason"]
    assert row["pcr_oi"] is None
    assert row["pcr_source"] == "NOT_AVAILABLE"
    assert row["call_oi_at_strike"] == 1000.0
    assert row["put_oi_at_strike"] is None
