from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import monotonic
from typing import Any

from .models import (
    DualPcrResearchSnapshot,
    MorningReference,
    OpeningOiBaseline,
    OptionOiCell,
    PcrBias,
    ResearchDataQuality,
    ResearchLatencyEvidence,
    ResearchState,
)
from .five_minute_history import FiveMinutePcrObservation, IST
from .one_minute_history import OneMinutePcrObservation
from .strike_pcr_tracker import StrikePcrRecommendationObservation
from .policy import MarketTrendResearchPolicy
from .preopen_spot import PreOpenSpotObservation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_trend_research_snapshots (
 snapshot_id TEXT PRIMARY KEY,
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 source_timestamp TEXT NOT NULL,
 evaluated_at TEXT NOT NULL,
 state TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_trend_research_latest
ON market_trend_research_snapshots(underlying, trading_date, evaluated_at DESC);
CREATE TABLE IF NOT EXISTS market_trend_research_references (
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 reference_timestamp TEXT NOT NULL,
 expiry TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 PRIMARY KEY(underlying, trading_date)
);
CREATE TABLE IF NOT EXISTS market_trend_research_oi_baselines (
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 baseline_timestamp TEXT NOT NULL,
 expiry TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 PRIMARY KEY(underlying,trading_date)
);
CREATE TABLE IF NOT EXISTS market_trend_research_source_snapshots (
 snapshot_key TEXT PRIMARY KEY,
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 source_timestamp TEXT NOT NULL,
 expiry TEXT NOT NULL,
 provider TEXT NOT NULL,
 spot REAL NOT NULL,
 request_ms REAL NOT NULL,
 normalization_ms REAL NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_trend_research_source_latest
ON market_trend_research_source_snapshots(underlying, trading_date, source_timestamp DESC);
CREATE TABLE IF NOT EXISTS market_trend_preopen_spot_observations (
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 provider TEXT NOT NULL,
 source_timestamp TEXT NOT NULL,
 captured_at TEXT NOT NULL,
 spot REAL NOT NULL,
 status TEXT NOT NULL,
 PRIMARY KEY(underlying, trading_date, provider, source_timestamp)
);
CREATE INDEX IF NOT EXISTS idx_market_trend_preopen_spot_latest
ON market_trend_preopen_spot_observations(
 underlying, trading_date, provider, source_timestamp DESC
);
CREATE TABLE IF NOT EXISTS market_trend_research_runtime_health (
 runtime_name TEXT PRIMARY KEY,
 heartbeat_at TEXT NOT NULL,
 last_success_at TEXT,
 last_failure_at TEXT,
 last_failure_reason TEXT,
 consecutive_failures INTEGER NOT NULL,
 dropped_obsolete_tasks INTEGER NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_trend_research_pcr_5m_history (
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 candle_close_timestamp TEXT NOT NULL,
 source_timestamp TEXT NOT NULL,
 overall_pcr REAL NOT NULL,
 overall_direction TEXT NOT NULL,
 quality_state TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(underlying, candle_close_timestamp)
);
CREATE INDEX IF NOT EXISTS idx_market_trend_research_pcr_5m_latest
ON market_trend_research_pcr_5m_history(
 underlying, trading_date, candle_close_timestamp DESC
);
CREATE TABLE IF NOT EXISTS market_trend_research_pcr_1m_history (
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 candle_close_timestamp TEXT NOT NULL,
 source_timestamp TEXT NOT NULL,
 overall_pcr REAL NOT NULL,
 overall_direction TEXT NOT NULL,
 quality_state TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(underlying, candle_close_timestamp)
);
CREATE INDEX IF NOT EXISTS idx_market_trend_research_pcr_1m_latest
ON market_trend_research_pcr_1m_history(
 underlying, trading_date, candle_close_timestamp DESC
);
CREATE TABLE IF NOT EXISTS market_trend_strike_pcr_recommendations (
 recommendation_id TEXT PRIMARY KEY,
 underlying TEXT NOT NULL,
 trading_date TEXT NOT NULL,
 expiry TEXT NOT NULL,
 strike REAL NOT NULL,
 side TEXT NOT NULL,
 status TEXT NOT NULL,
 opened_at TEXT NOT NULL,
 closed_at TEXT,
 entry_strike_pcr REAL NOT NULL,
 entry_overall_pcr REAL,
 entry_price REAL NOT NULL,
 entry_delta REAL,
 entry_iv REAL,
 entry_contract_vwap REAL,
 current_price REAL NOT NULL,
 peak_price REAL NOT NULL,
 peak_at TEXT NOT NULL,
 last_strike_pcr REAL NOT NULL,
 strike_signal TEXT NOT NULL,
 overall_pcr REAL,
 overall_signal TEXT NOT NULL,
 symbol TEXT,
 last_observed_at TEXT NOT NULL,
 authority TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_strike_pcr_one_active
ON market_trend_strike_pcr_recommendations(underlying, trading_date, expiry, strike)
WHERE status='ACTIVE';
CREATE INDEX IF NOT EXISTS idx_strike_pcr_recommendations_latest
ON market_trend_strike_pcr_recommendations(
 underlying, trading_date, last_observed_at DESC
);
"""


_RECOMMENDATION_ENTRY_GREEK_COLUMNS = (
    ("entry_delta", "REAL"),
    ("entry_iv", "REAL"),
    ("entry_contract_vwap", "REAL"),
)


def _ensure_recommendation_entry_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(market_trend_strike_pcr_recommendations)"
        ).fetchall()
    }
    for name, declaration in _RECOMMENDATION_ENTRY_GREEK_COLUMNS:
        if name not in columns:
            connection.execute(
                "ALTER TABLE market_trend_strike_pcr_recommendations "
                f"ADD COLUMN {name} {declaration}"
            )


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"unsupported research serialization type: {type(value).__name__}")


def _json(value: object) -> str:
    return json.dumps(value, default=_json_value, sort_keys=True, separators=(",", ":"))


def _payload(snapshot: DualPcrResearchSnapshot) -> str:
    payload = asdict(snapshot)
    policy = MarketTrendResearchPolicy()
    for panel_name in ("current_panel", "morning_panel"):
        panel = payload.get(panel_name)
        if not isinstance(panel, dict):
            continue
        aggregate = panel.get("aggregate")
        if not isinstance(aggregate, dict) or aggregate.get("direction_evidence") is not None:
            continue
        raw_classification = aggregate.get("classification", PcrBias.UNAVAILABLE)
        classification = (
            raw_classification
            if isinstance(raw_classification, PcrBias)
            else PcrBias(str(raw_classification))
        )
        aggregate["direction_evidence"] = asdict(
            policy.direction_evidence(
                aggregate.get("pcr"),
                classification=classification,
            )
        )
    return _json(payload)


def _utc_iso(value: datetime, *, field_name: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


class MarketTrendResearchRepository:
    def __init__(self, database_path: str | Path, *, retention: int = 500) -> None:
        self.path = Path(database_path)
        self.retention = retention

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(_SCHEMA)
        return connection

    def persist_once(
        self,
        snapshot: DualPcrResearchSnapshot,
        *,
        evaluation_started: float,
        database_read_ms: float,
        normalization_ms: float,
        calculation_ms: float,
        hard_deadline_ms: float,
        provider_request_ms: float = 0.0,
        dropped_obsolete_tasks: int = 0,
        consecutive_failures: int = 0,
    ) -> DualPcrResearchSnapshot:
        """Publish one externally visible record through one SQLite commit."""
        source_timestamp = _utc_iso(snapshot.source_timestamp, field_name="source_timestamp")
        evaluated_at = _utc_iso(snapshot.evaluated_at, field_name="evaluated_at")
        persistence_started = monotonic()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR REPLACE INTO market_trend_research_snapshots
                   (snapshot_id, underlying, trading_date, source_timestamp,
                    evaluated_at, state, payload_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    snapshot.snapshot_id,
                    snapshot.underlying,
                    snapshot.trading_date.isoformat(),
                    source_timestamp,
                    evaluated_at,
                    snapshot.quality.state.value,
                    _payload(snapshot),
                ),
            )
            connection.execute(
                """DELETE FROM market_trend_research_snapshots
                   WHERE snapshot_id IN (
                     SELECT snapshot_id FROM market_trend_research_snapshots
                     WHERE underlying=?
                     ORDER BY julianday(evaluated_at) DESC, evaluated_at DESC
                     LIMIT -1 OFFSET ?
                   )""",
                (snapshot.underlying, self.retention),
            )
            persistence_ms = (monotonic() - persistence_started) * 1000.0
            end_to_end_ms = (monotonic() - evaluation_started) * 1000.0
            final_state = ResearchState.TIMEOUT if end_to_end_ms > hard_deadline_ms else snapshot.quality.state
            quality = (
                ResearchDataQuality(
                    ResearchState.TIMEOUT,
                    snapshot.quality.source_age_seconds,
                    ("DEADLINE_EXCEEDED",),
                )
                if final_state is ResearchState.TIMEOUT
                else snapshot.quality
            )
            final_snapshot = replace(
                snapshot,
                quality=quality,
                latency=ResearchLatencyEvidence(
                    database_read_ms=database_read_ms,
                    normalization_ms=normalization_ms,
                    calculation_ms=calculation_ms,
                    persistence_ms=persistence_ms,
                    end_to_end_ms=end_to_end_ms,
                    provider_request_ms=provider_request_ms,
                    dropped_obsolete_tasks=dropped_obsolete_tasks,
                    consecutive_failures=consecutive_failures,
                ),
            )
            connection.execute(
                """UPDATE market_trend_research_snapshots
                   SET state=?, payload_json=? WHERE snapshot_id=?""",
                (
                    final_snapshot.quality.state.value,
                    _payload(final_snapshot),
                    final_snapshot.snapshot_id,
                ),
            )
            connection.commit()
        return final_snapshot

    def persist(self, snapshot: DualPcrResearchSnapshot) -> None:
        source_timestamp = _utc_iso(snapshot.source_timestamp, field_name="source_timestamp")
        evaluated_at = _utc_iso(snapshot.evaluated_at, field_name="evaluated_at")
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO market_trend_research_snapshots
                   (snapshot_id, underlying, trading_date, source_timestamp,
                    evaluated_at, state, payload_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    snapshot.snapshot_id,
                    snapshot.underlying,
                    snapshot.trading_date.isoformat(),
                    source_timestamp,
                    evaluated_at,
                    snapshot.quality.state.value,
                    _payload(snapshot),
                ),
            )
            connection.commit()

    def latest_projection(self, *, underlying: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    """SELECT payload_json FROM market_trend_research_snapshots
                       WHERE underlying=?
                       ORDER BY julianday(evaluated_at) DESC, evaluated_at DESC
                       LIMIT 1""",
                    (underlying,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return None if row is None else json.loads(row[0])

    def latest_projections(
        self,
        *,
        underlyings: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        """Read the newest projection for several underlyings in one query."""
        if not self.path.exists() or not underlyings:
            return {}
        placeholders = ",".join("?" for _ in underlyings)
        try:
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    f"""SELECT underlying, payload_json FROM (
                          SELECT underlying, payload_json,
                                 ROW_NUMBER() OVER (
                                   PARTITION BY underlying
                                   ORDER BY julianday(evaluated_at) DESC,
                                            evaluated_at DESC
                                 ) AS row_number
                          FROM market_trend_research_snapshots
                          WHERE underlying IN ({placeholders})
                        ) WHERE row_number=1""",
                    underlyings,
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return {}
            raise
        return {str(underlying): json.loads(payload) for underlying, payload in rows}

    def persist_five_minute_pcr_observation(
        self,
        observation: FiveMinutePcrObservation,
    ) -> bool:
        """Persist exactly one immutable PCR record per completed 5m candle."""
        candle_close = _utc_iso(
            observation.candle_close_timestamp,
            field_name="candle_close_timestamp",
        )
        source_timestamp = _utc_iso(
            observation.source_timestamp,
            field_name="source_timestamp",
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO market_trend_research_pcr_5m_history
                   (underlying, trading_date, candle_close_timestamp,
                    source_timestamp, overall_pcr, overall_direction,
                    quality_state, payload_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    observation.underlying,
                    observation.candle_close_timestamp.astimezone(IST).date().isoformat(),
                    candle_close,
                    source_timestamp,
                    observation.overall_pcr,
                    observation.overall_direction,
                    observation.quality_state,
                    _json(observation.payload()),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def five_minute_pcr_history(
        self,
        *,
        underlying: str,
        trading_date: date,
        limit: int = 75,
    ) -> list[dict[str, Any]]:
        """Read completed-candle PCR history newest first."""
        if limit < 1:
            raise ValueError("limit must be positive")
        if not self.path.exists():
            return []
        try:
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """SELECT payload_json
                       FROM market_trend_research_pcr_5m_history
                       WHERE underlying=? AND trading_date=?
                       ORDER BY candle_close_timestamp DESC
                       LIMIT ?""",
                    (underlying, trading_date.isoformat(), limit),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        return [json.loads(row[0]) for row in rows]

    def _distinct_trading_days(self, table: str, underlying: str) -> list[str]:
        if not self.path.exists():
            return []
        try:
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    f"SELECT DISTINCT trading_date FROM {table} "
                    "WHERE underlying=? ORDER BY trading_date DESC",
                    (underlying,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        return [str(row[0]) for row in rows if row[0]]

    def five_minute_pcr_trading_days(self, underlying: str) -> list[str]:
        """Distinct trading days with 5m PCR observations, newest first."""
        return self._distinct_trading_days(
            "market_trend_research_pcr_5m_history", underlying
        )

    def persist_one_minute_pcr_observation(
        self,
        observation: OneMinutePcrObservation,
    ) -> bool:
        """Persist exactly one immutable PCR record per completed 1m candle."""
        candle_close = _utc_iso(
            observation.candle_close_timestamp,
            field_name="candle_close_timestamp",
        )
        source_timestamp = _utc_iso(
            observation.source_timestamp,
            field_name="source_timestamp",
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO market_trend_research_pcr_1m_history
                   (underlying, trading_date, candle_close_timestamp,
                    source_timestamp, overall_pcr, overall_direction,
                    quality_state, payload_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    observation.underlying,
                    observation.candle_close_timestamp.astimezone(IST).date().isoformat(),
                    candle_close,
                    source_timestamp,
                    observation.overall_pcr,
                    observation.overall_direction,
                    observation.quality_state,
                    _json(observation.payload()),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def one_minute_pcr_history(
        self,
        *,
        underlying: str,
        trading_date: date,
        limit: int = 75,
    ) -> list[dict[str, Any]]:
        """Read completed-candle PCR history newest first."""
        if limit < 1:
            raise ValueError("limit must be positive")
        if not self.path.exists():
            return []
        try:
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """SELECT payload_json
                       FROM market_trend_research_pcr_1m_history
                       WHERE underlying=? AND trading_date=?
                       ORDER BY candle_close_timestamp DESC
                       LIMIT ?""",
                    (underlying, trading_date.isoformat(), limit),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        return [json.loads(row[0]) for row in rows]

    def one_minute_pcr_trading_days(self, underlying: str) -> list[str]:
        """Distinct trading days with 1m PCR observations, newest first."""
        return self._distinct_trading_days(
            "market_trend_research_pcr_1m_history", underlying
        )

    def strike_pcr_recommendation_trading_days(self, underlying: str) -> list[str]:
        """Distinct trading days with strike PCR recommendations, newest first."""
        return self._distinct_trading_days(
            "market_trend_strike_pcr_recommendations", underlying
        )

    def apply_strike_pcr_recommendations(
        self,
        observations: tuple[StrikePcrRecommendationObservation, ...],
    ) -> None:
        """Advance per-strike observational recommendation lifecycles atomically."""
        if not observations:
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _ensure_recommendation_entry_columns(connection)
            for item in observations:
                observed_at = _utc_iso(item.observed_at, field_name="observed_at")
                trading_date = item.observed_at.astimezone(IST).date().isoformat()
                active = connection.execute(
                    """SELECT recommendation_id, side, peak_price, peak_at
                       FROM market_trend_strike_pcr_recommendations
                       WHERE underlying=? AND trading_date=? AND expiry=?
                         AND strike=? AND status='ACTIVE'""",
                    (item.underlying, trading_date, item.expiry, item.strike),
                ).fetchone()
                desired_side = (
                    "CE" if item.recommendation == "BUY_CE"
                    else "PE" if item.recommendation == "BUY_PE"
                    else None
                )
                if active is not None and str(active[1]) != desired_side:
                    connection.execute(
                        """UPDATE market_trend_strike_pcr_recommendations
                           SET status='CLOSED', closed_at=?, last_observed_at=?,
                               last_strike_pcr=COALESCE(?, last_strike_pcr),
                               strike_signal=?, overall_pcr=?,
                               overall_signal=? WHERE recommendation_id=?""",
                        (
                            observed_at, observed_at, item.strike_pcr,
                            item.strike_signal, item.overall_pcr,
                            item.overall_signal, active[0],
                        ),
                    )
                    active = None
                if desired_side is None or item.strike_pcr is None:
                    continue
                bid = item.executable_bid
                ask = item.entry_ask
                if active is not None:
                    if bid is None or bid <= 0:
                        continue
                    old_peak = float(active[2])
                    peak = max(old_peak, bid)
                    peak_at = observed_at if bid > old_peak else str(active[3])
                    connection.execute(
                        """UPDATE market_trend_strike_pcr_recommendations
                           SET current_price=?, peak_price=?, peak_at=?,
                               last_strike_pcr=?, strike_signal=?, overall_pcr=?,
                               overall_signal=?, last_observed_at=?
                           WHERE recommendation_id=?""",
                        (
                            bid, peak, peak_at, item.strike_pcr,
                            item.strike_signal, item.overall_pcr,
                            item.overall_signal, observed_at, active[0],
                        ),
                    )
                    continue
                if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
                    continue
                identity = "|".join((
                    item.underlying, trading_date, item.expiry,
                    f"{item.strike:.4f}", desired_side, observed_at,
                ))
                recommendation_id = "PCR-" + sha256(identity.encode()).hexdigest()[:24]
                connection.execute(
                    """INSERT INTO market_trend_strike_pcr_recommendations
                       (recommendation_id, underlying, trading_date, expiry,
                        strike, side, status, opened_at, closed_at,
                        entry_strike_pcr, entry_overall_pcr, entry_price,
                        entry_delta, entry_iv, entry_contract_vwap,
                        current_price, peak_price, peak_at, last_strike_pcr,
                        strike_signal, overall_pcr, overall_signal, symbol,
                        last_observed_at, authority)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        recommendation_id, item.underlying, trading_date,
                        item.expiry, item.strike, desired_side, "ACTIVE",
                        observed_at, None, item.strike_pcr, item.overall_pcr,
                        ask, item.entry_delta, item.entry_iv,
                        item.entry_contract_vwap,
                        bid, bid, observed_at, item.strike_pcr,
                        item.strike_signal, item.overall_pcr,
                        item.overall_signal, item.symbol, observed_at,
                        item.authority,
                    ),
                )
            connection.commit()

    def strike_pcr_recommendations(
        self,
        *,
        underlying: str,
        trading_date: date,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read active recommendations first, followed by recent closed episodes."""
        if limit < 1:
            raise ValueError("limit must be positive")
        if not self.path.exists():
            return []
        try:
            with sqlite3.connect(self.path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """SELECT * FROM market_trend_strike_pcr_recommendations
                       WHERE underlying=? AND trading_date=?
                       ORDER BY CASE status WHEN 'ACTIVE' THEN 0 ELSE 1 END,
                                julianday(last_observed_at) DESC,
                                last_observed_at DESC LIMIT ?""",
                    (underlying, trading_date.isoformat(), limit),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        return [dict(row) for row in rows]

    def create_reference(self, reference: MorningReference) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO market_trend_research_references
                   (underlying, trading_date, reference_timestamp, expiry, payload_json)
                   VALUES (?,?,?,?,?)""",
                (
                    reference.underlying,
                    reference.trading_date.isoformat(),
                    reference.reference_timestamp.isoformat(),
                    reference.expiry.isoformat(),
                    _json(asdict(reference)),
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def persist_preopen_spot(self, observation: PreOpenSpotObservation) -> bool:
        """Persist immutable provider evidence; duplicate samples are harmless."""
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO market_trend_preopen_spot_observations
                   (underlying, trading_date, provider, source_timestamp,
                    captured_at, spot, status)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    observation.underlying,
                    observation.trading_date.isoformat(),
                    observation.provider,
                    _utc_iso(observation.source_timestamp, field_name="source_timestamp"),
                    _utc_iso(observation.captured_at, field_name="captured_at"),
                    observation.spot,
                    observation.status,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def latest_preopen_spots(
        self,
        *,
        underlying: str,
        trading_date: date,
    ) -> tuple[PreOpenSpotObservation, ...]:
        if not self.path.exists():
            return ()
        try:
            with sqlite3.connect(self.path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """SELECT underlying, trading_date, provider, source_timestamp,
                              captured_at, spot, status
                       FROM (
                         SELECT *, ROW_NUMBER() OVER (
                           PARTITION BY provider
                           ORDER BY julianday(source_timestamp) DESC,
                                    source_timestamp DESC
                         ) AS row_number
                         FROM market_trend_preopen_spot_observations
                         WHERE underlying=? AND trading_date=?
                       ) WHERE row_number=1
                       ORDER BY provider""",
                    (underlying, trading_date.isoformat()),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return ()
            raise
        return tuple(
            PreOpenSpotObservation(
                underlying=str(row["underlying"]),
                trading_date=date.fromisoformat(str(row["trading_date"])),
                provider=str(row["provider"]),
                source_timestamp=datetime.fromisoformat(str(row["source_timestamp"])),
                captured_at=datetime.fromisoformat(str(row["captured_at"])),
                spot=float(row["spot"]),
                status=str(row["status"]),
            )
            for row in rows
        )

    def load_reference(self, *, underlying: str, trading_date: date) -> dict[str, Any] | None:
        return self._load_daily(table="market_trend_research_references", underlying=underlying, trading_date=trading_date)

    def create_oi_baseline(self, baseline: OpeningOiBaseline) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO market_trend_research_oi_baselines
                   (underlying, trading_date, baseline_timestamp, expiry, payload_json)
                   VALUES (?,?,?,?,?)""",
                (
                    baseline.underlying,
                    baseline.trading_date.isoformat(),
                    baseline.baseline_timestamp.isoformat(),
                    baseline.expiry.isoformat(),
                    _json(asdict(baseline)),
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def load_oi_baseline(self, *, underlying: str, trading_date: date) -> dict[str, Any] | None:
        return self._load_daily(table="market_trend_research_oi_baselines", underlying=underlying, trading_date=trading_date)

    def _load_daily(self, *, table: str, underlying: str, trading_date: date) -> dict[str, Any] | None:
        if table not in {"market_trend_research_references", "market_trend_research_oi_baselines"}:
            raise ValueError("unsupported research table")
        if not self.path.exists():
            return None
        try:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    f"SELECT payload_json FROM {table} WHERE underlying=? AND trading_date=?",
                    (underlying, trading_date.isoformat()),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return None if row is None else json.loads(row[0])

    def persist_source_snapshot(
        self,
        *,
        snapshot_key: str,
        underlying: str,
        trading_date: date,
        source_timestamp: datetime,
        expiry: date,
        provider: str,
        spot: float,
        cells: tuple[OptionOiCell, ...],
        request_ms: float,
        normalization_ms: float,
    ) -> None:
        payload = {
            "underlying": underlying,
            "provider": provider,
            "source_timestamp": source_timestamp,
            "spot": spot,
            "expiry": expiry,
            "cells": [asdict(cell) for cell in cells],
            "request_ms": request_ms,
            "normalization_ms": normalization_ms,
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR REPLACE INTO market_trend_research_source_snapshots
                   (snapshot_key, underlying, trading_date, source_timestamp, expiry,
                    provider, spot, request_ms, normalization_ms, payload_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    snapshot_key,
                    underlying,
                    trading_date.isoformat(),
                    source_timestamp.isoformat(),
                    expiry.isoformat(),
                    provider,
                    spot,
                    request_ms,
                    normalization_ms,
                    _json(payload),
                ),
            )
            connection.execute(
                """DELETE FROM market_trend_research_source_snapshots
                   WHERE snapshot_key IN (
                     SELECT snapshot_key FROM market_trend_research_source_snapshots
                     WHERE underlying=? ORDER BY source_timestamp DESC
                     LIMIT -1 OFFSET ?
                   )""",
                (underlying, self.retention),
            )
            connection.commit()

    def recent_source_payloads(self, *, underlying: str, limit: int = 2) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        try:
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute(
                    """SELECT payload_json FROM market_trend_research_source_snapshots
                       WHERE underlying=? ORDER BY source_timestamp DESC LIMIT ?""",
                    (underlying, limit),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return ()
            raise
        return tuple(json.loads(row[0]) for row in rows)

    def persist_runtime_health(
        self,
        *,
        runtime_name: str,
        heartbeat_at: datetime,
        last_success_at: datetime | None,
        last_failure_at: datetime | None,
        last_failure_reason: str | None,
        consecutive_failures: int,
        dropped_obsolete_tasks: int,
    ) -> None:
        payload = {
            "runtime_name": runtime_name,
            "heartbeat_at": heartbeat_at,
            "last_success_at": last_success_at,
            "last_failure_at": last_failure_at,
            "last_failure_reason": last_failure_reason,
            "consecutive_failures": consecutive_failures,
            "dropped_obsolete_tasks": dropped_obsolete_tasks,
        }
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO market_trend_research_runtime_health
                   (runtime_name, heartbeat_at, last_success_at, last_failure_at,
                    last_failure_reason, consecutive_failures,
                    dropped_obsolete_tasks, payload_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    runtime_name,
                    heartbeat_at.isoformat(),
                    None if last_success_at is None else last_success_at.isoformat(),
                    None if last_failure_at is None else last_failure_at.isoformat(),
                    last_failure_reason,
                    consecutive_failures,
                    dropped_obsolete_tasks,
                    _json(payload),
                ),
            )
            connection.commit()

    def latest_runtime_health(self, *, runtime_name: str = "MARKET_TREND_RESEARCH") -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    """SELECT payload_json FROM market_trend_research_runtime_health
                       WHERE runtime_name=?""",
                    (runtime_name,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return None if row is None else json.loads(row[0])

    def create_anchor(self, **_: object) -> bool:
        raise ValueError("MORNING_ANCHOR_REPLACED_BY_SPLIT_LIFECYCLE")

    def load_anchor(self, **_: object) -> None:
        return None
