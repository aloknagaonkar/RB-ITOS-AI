from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


RED_BAR_V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_indicator_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    candle_timestamp TEXT NOT NULL,
    candle_open REAL,
    candle_high REAL,
    candle_low REAL,
    candle_close REAL NOT NULL,
    candle_volume REAL,
    rsi_period INTEGER NOT NULL,
    rsi_value REAL,
    vwap_value REAL,
    price_vs_vwap TEXT,
    rsi_state TEXT,
    source TEXT NOT NULL,
    data_quality TEXT NOT NULL DEFAULT 'VALID',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(instrument_key, timeframe, candle_timestamp, rsi_period)
);

CREATE INDEX IF NOT EXISTS idx_market_indicator_lookup
ON market_indicator_snapshots(instrument_key, timeframe, candle_timestamp);

CREATE TABLE IF NOT EXISTS red_bar_v2_direction_events (
    event_id TEXT PRIMARY KEY,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    event_type TEXT NOT NULL,
    direction TEXT,
    trend_strength TEXT,
    reference_timestamp TEXT,
    midpoint REAL,
    context_timeframe TEXT NOT NULL,
    context_timestamp TEXT NOT NULL,
    close_price REAL,
    rsi_value REAL,
    vwap_value REAL,
    rsi_aligned INTEGER NOT NULL DEFAULT 0,
    vwap_aligned INTEGER NOT NULL DEFAULT 0,
    midpoint_aligned INTEGER NOT NULL DEFAULT 0,
    related_trade_id TEXT,
    related_signal_id TEXT,
    reversal_event_id TEXT,
    consumed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(
        instrument_key,
        strategy_version,
        event_type,
        direction,
        context_timestamp,
        reference_timestamp
    )
);

CREATE INDEX IF NOT EXISTS idx_red_bar_v2_event_lookup
ON red_bar_v2_direction_events(
    instrument_key,
    trading_date,
    event_type,
    context_timestamp
);

CREATE TABLE IF NOT EXISTS candidate_admission_decisions (
    decision_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    signal_id TEXT,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    candidate_allowed INTEGER NOT NULL,
    admission_code TEXT NOT NULL,
    admission_reason TEXT NOT NULL,
    direction TEXT,
    option_side TEXT,
    entry_type TEXT,
    trend_strength TEXT,
    active_trade_count INTEGER NOT NULL DEFAULT 0,
    previous_trade_id TEXT,
    previous_trade_status TEXT,
    rsi_aligned INTEGER NOT NULL DEFAULT 0,
    vwap_aligned INTEGER NOT NULL DEFAULT 0,
    midpoint_aligned INTEGER NOT NULL DEFAULT 0,
    context_fresh INTEGER NOT NULL DEFAULT 0,
    duplicate_signal INTEGER NOT NULL DEFAULT 0,
    reversal_consumed INTEGER NOT NULL DEFAULT 0,
    conditions_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES red_bar_v2_direction_events(event_id)
);

CREATE INDEX IF NOT EXISTS idx_admission_event
ON candidate_admission_decisions(event_id);

CREATE INDEX IF NOT EXISTS idx_admission_signal
ON candidate_admission_decisions(signal_id);
"""


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join("" if item is None else str(item) for item in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def indicator_snapshot_id(
    instrument_key: str,
    timeframe: str,
    candle_timestamp: str,
    rsi_period: int,
) -> str:
    return _stable_id("RBV2CTX", instrument_key, timeframe, candle_timestamp, rsi_period)


def direction_event_id(
    instrument_key: str,
    strategy_version: str,
    event_type: str,
    direction: str | None,
    context_timestamp: str,
    reference_timestamp: str | None,
) -> str:
    return _stable_id(
        "RBV2EVT",
        instrument_key,
        strategy_version,
        event_type,
        direction,
        context_timestamp,
        reference_timestamp,
    )


def admission_decision_id(event_id: str, admission_code: str) -> str:
    return _stable_id("RBV2ADM", event_id, admission_code)


@dataclass(frozen=True)
class IndicatorSnapshot:
    instrument_key: str
    trading_date: str
    timeframe: str
    candle_timestamp: str
    candle_close: float
    rsi_period: int
    source: str
    candle_open: float | None = None
    candle_high: float | None = None
    candle_low: float | None = None
    candle_volume: float | None = None
    rsi_value: float | None = None
    vwap_value: float | None = None
    price_vs_vwap: str | None = None
    rsi_state: str | None = None
    data_quality: str = "VALID"


@dataclass(frozen=True)
class DirectionEvent:
    instrument_key: str
    trading_date: str
    strategy_version: str
    event_type: str
    context_timeframe: str
    context_timestamp: str
    direction: str | None = None
    trend_strength: str | None = None
    reference_timestamp: str | None = None
    midpoint: float | None = None
    close_price: float | None = None
    rsi_value: float | None = None
    vwap_value: float | None = None
    rsi_aligned: bool = False
    vwap_aligned: bool = False
    midpoint_aligned: bool = False
    related_trade_id: str | None = None
    related_signal_id: str | None = None
    reversal_event_id: str | None = None
    consumed: bool = False


@dataclass(frozen=True)
class AdmissionDecision:
    event_id: str
    instrument_key: str
    trading_date: str
    strategy_version: str
    candidate_allowed: bool
    admission_code: str
    admission_reason: str
    signal_id: str | None = None
    direction: str | None = None
    option_side: str | None = None
    entry_type: str | None = None
    trend_strength: str | None = None
    active_trade_count: int = 0
    previous_trade_id: str | None = None
    previous_trade_status: str | None = None
    rsi_aligned: bool = False
    vwap_aligned: bool = False
    midpoint_aligned: bool = False
    context_fresh: bool = False
    duplicate_signal: bool = False
    reversal_consumed: bool = False
    conditions: Mapping[str, Any] | None = None


class RedBarV2Storage:
    """Additive Red Bar V2 persistence using the existing SQLite database file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(RED_BAR_V2_SCHEMA)
            self._migrate_indicator_snapshots(conn)
            conn.commit()

    @staticmethod
    def _migrate_indicator_snapshots(conn: sqlite3.Connection) -> None:
        """Add `rsi_state` to databases created before it existed.

        The schema above runs as CREATE TABLE IF NOT EXISTS, so an existing
        deployment keeps whatever columns it was created with. The retired
        `bullish_context`/`bearish_context` columns are left in place -- they are
        NOT NULL DEFAULT 0, so an INSERT that omits them still succeeds, and
        dropping them would mean rebuilding a live table for no gain.
        """
        existing = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(market_indicator_snapshots)")
        }
        if existing and "rsi_state" not in existing:
            conn.execute(
                "ALTER TABLE market_indicator_snapshots ADD COLUMN rsi_state TEXT"
            )

    def upsert_indicator_snapshot(self, snapshot: IndicatorSnapshot) -> str:
        self.initialize()
        snapshot_id = indicator_snapshot_id(
            snapshot.instrument_key,
            snapshot.timeframe,
            snapshot.candle_timestamp,
            snapshot.rsi_period,
        )
        now = datetime.now().astimezone().isoformat()
        row = asdict(snapshot)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO market_indicator_snapshots(
                    snapshot_id,instrument_key,trading_date,timeframe,candle_timestamp,
                    candle_open,candle_high,candle_low,candle_close,candle_volume,
                    rsi_period,rsi_value,vwap_value,price_vs_vwap,rsi_state,
                    source,data_quality,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    candle_open=excluded.candle_open,
                    candle_high=excluded.candle_high,
                    candle_low=excluded.candle_low,
                    candle_close=excluded.candle_close,
                    candle_volume=excluded.candle_volume,
                    rsi_value=excluded.rsi_value,
                    vwap_value=excluded.vwap_value,
                    price_vs_vwap=excluded.price_vs_vwap,
                    rsi_state=excluded.rsi_state,
                    source=excluded.source,
                    data_quality=excluded.data_quality,
                    updated_at=excluded.updated_at
                """,
                (
                    snapshot_id,
                    row["instrument_key"],
                    row["trading_date"],
                    row["timeframe"],
                    row["candle_timestamp"],
                    row["candle_open"],
                    row["candle_high"],
                    row["candle_low"],
                    row["candle_close"],
                    row["candle_volume"],
                    row["rsi_period"],
                    row["rsi_value"],
                    row["vwap_value"],
                    row["price_vs_vwap"],
                    row["rsi_state"],
                    row["source"],
                    row["data_quality"],
                    now,
                    now,
                ),
            )
            conn.commit()
        return snapshot_id

    def read_indicator_snapshot(self, snapshot_id: str) -> dict[str, object] | None:
        return self._read_one("market_indicator_snapshots", "snapshot_id", snapshot_id)

    def upsert_direction_event(self, event: DirectionEvent) -> str:
        self.initialize()
        event_id = direction_event_id(
            event.instrument_key,
            event.strategy_version,
            event.event_type,
            event.direction,
            event.context_timestamp,
            event.reference_timestamp,
        )
        now = datetime.now().astimezone().isoformat()
        row = asdict(event)
        columns = [
            "event_id","instrument_key","trading_date","strategy_version",
            "event_type","direction","trend_strength","reference_timestamp",
            "midpoint","context_timeframe","context_timestamp","close_price",
            "rsi_value","vwap_value","rsi_aligned","vwap_aligned",
            "midpoint_aligned","related_trade_id","related_signal_id",
            "reversal_event_id","consumed","created_at","updated_at",
        ]
        values = [
            event_id,row["instrument_key"],row["trading_date"],row["strategy_version"],
            row["event_type"],row["direction"],row["trend_strength"],
            row["reference_timestamp"],row["midpoint"],row["context_timeframe"],
            row["context_timestamp"],row["close_price"],row["rsi_value"],
            row["vwap_value"],int(row["rsi_aligned"]),int(row["vwap_aligned"]),
            int(row["midpoint_aligned"]),row["related_trade_id"],
            row["related_signal_id"],row["reversal_event_id"],int(row["consumed"]),
            now,now,
        ]
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO red_bar_v2_direction_events({','.join(columns)}) "
                f"VALUES({','.join('?' for _ in columns)})",
                values,
            )
            conn.commit()
        return event_id

    def read_direction_event(self, event_id: str) -> dict[str, object] | None:
        return self._read_one("red_bar_v2_direction_events", "event_id", event_id)

    def mark_reversal_consumed(self, event_id: str) -> None:
        self.initialize()
        now = datetime.now().astimezone().isoformat()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE red_bar_v2_direction_events SET consumed=1,updated_at=? WHERE event_id=?",
                (now, event_id),
            )
            conn.commit()

    def upsert_admission_decision(self, decision: AdmissionDecision) -> str:
        self.initialize()
        decision_id = admission_decision_id(decision.event_id, decision.admission_code)
        now = datetime.now().astimezone().isoformat()
        row = asdict(decision)
        conditions_json = json.dumps(row.pop("conditions") or {}, sort_keys=True)
        columns = [
            "decision_id","event_id","signal_id","instrument_key","trading_date",
            "strategy_version","candidate_allowed","admission_code","admission_reason",
            "direction","option_side","entry_type","trend_strength",
            "active_trade_count","previous_trade_id","previous_trade_status",
            "rsi_aligned","vwap_aligned","midpoint_aligned","context_fresh",
            "duplicate_signal","reversal_consumed","conditions_json","created_at",
            "updated_at",
        ]
        values = [
            decision_id,row["event_id"],row["signal_id"],row["instrument_key"],
            row["trading_date"],row["strategy_version"],int(row["candidate_allowed"]),
            row["admission_code"],row["admission_reason"],row["direction"],
            row["option_side"],row["entry_type"],row["trend_strength"],
            row["active_trade_count"],row["previous_trade_id"],
            row["previous_trade_status"],int(row["rsi_aligned"]),
            int(row["vwap_aligned"]),int(row["midpoint_aligned"]),
            int(row["context_fresh"]),int(row["duplicate_signal"]),
            int(row["reversal_consumed"]),conditions_json,now,now,
        ]
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO candidate_admission_decisions({','.join(columns)}) "
                f"VALUES({','.join('?' for _ in columns)})",
                values,
            )
            conn.commit()
        return decision_id

    def read_admission_decision(self, decision_id: str) -> dict[str, object] | None:
        row = self._read_one("candidate_admission_decisions", "decision_id", decision_id)
        if row is not None:
            row["conditions"] = json.loads(str(row.pop("conditions_json") or "{}"))
        return row

    def _read_one(self, table: str, key: str, value: str) -> dict[str, object] | None:
        self.initialize()
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT * FROM {table} WHERE {key}=? LIMIT 1",
                (value,),
            ).fetchone()
        return dict(row) if row else None
